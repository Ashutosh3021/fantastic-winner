"""Read models for the learner's own history: progress, mistakes, reviews, cards.

Everything here is a *projection*. None of it is written during a request; it
is all produced by :mod:`app.services.projector` from the attempt log. That has
one consequence worth stating plainly: a learner who has just answered a
question may not see it in ``/progress`` for a second or two, because the
projector has not run yet.

That is the correct trade. Blocking the answer on a stats recompute would make
every answer slower to buy a number nobody is waiting on, and computing it
inline would let XP and the attempt log disagree permanently.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from math import exp
from typing import Any

from ..core.config import CreditConfig
from ..core.errors import NotFound
from ..repositories.gateway import PyronitesGateway
from ..repositories.sql import safe_identifier
from ..repositories.store import (
    MistakeRepository,
    PreferencesRepository,
    SavedCardRepository,
    UserRepository,
    new_id,
    now_iso,
)
from ..schemas.models import (
    ConceptProgressRow,
    DailyActivity,
    MistakeEntry,
    MistakeList,
    MistakeType,
    Preferences,
    ProgressResponse,
    ReviewItem,
    ReviewQueueResponse,
    SavedCard,
    SavedCardsResponse,
    Usage,
    Weakness,
)

#: Recency weight on a mistake. A mistake from three months ago is less worth
#: re-drilling than one from last week, so weighting decays instead of counting.
_HALF_LIFE_DAYS = 21.0


class ProgressService:
    def __init__(
        self,
        gateway: PyronitesGateway,
        *,
        users: UserRepository,
        preferences: PreferencesRepository,
        mistakes: MistakeRepository,
        saved_cards: SavedCardRepository,
        credit_config: CreditConfig,
    ) -> None:
        self.gw = gateway
        self.users = users
        self.preferences = preferences
        self.mistakes = mistakes
        self.saved_cards = saved_cards
        self.credit_config = credit_config

    # ── identity and preferences ─────────────────────────────────────────────

    async def me(
        self,
        user_id: str,
        *,
        usage: dict[str, Any],
        ai_key: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFound("Account not found")
        prefs = await self.preferences.get(user_id) or {}
        return {
            "id": str(user["id"]),
            "email": str(user.get("email", "")),
            "email_verified": bool(user.get("email_verified_at")),
            "created_at": str(user.get("created_at", "")),
            "preferences": Preferences.model_validate(prefs),
            "usage": usage,
            "planTier": max(0, min(1, int(user.get("plan_tier") or 0))),
            "aiKey": ai_key,
        }

    async def preferences_for(self, user_id: str) -> Preferences:
        row = await self.preferences.get(user_id)
        return Preferences.model_validate(row) if row else Preferences()

    async def save_preferences(self, user_id: str, patch: dict[str, Any]) -> Preferences:
        """Upsert the learner's preferences.

        ``prefs_version`` is bumped on every write so the extension can tell a
        local preference change from a server-side one and re-sync.
        """
        current = await self.preferences.get(user_id) or {}
        merged = {**current, **{k: v for k, v in patch.items() if v is not None}}
        merged["prefs_version"] = int(current.get("prefs_version", 0) or 0) + 1
        merged["updated_at"] = now_iso()

        if current:
            await self.preferences.update(user_id, merged)
        else:
            await self.preferences.insert({**merged, "user_id": user_id}, row_id=user_id)
        return Preferences.model_validate(merged)

    async def delete_account(self, user_id: str) -> None:
        """Remove the learner's rows.

        PyroCore is the system of record for identity, so the *account* is not
        deleted here; this drops everything CodeMentor holds and leaves the
        sign-in working, which is what the extension's "delete my data" promises.
        """
        for table in (
            "problem_sessions",
            "session_content",
            "micro_question_attempts",
            "mistakes",
            "concept_progress",
            "review_queue",
            "saved_cards",
            "user_stats",
            "user_stats_events",
            "credit_ledger",
            "credit_claims",
            "user_preferences",
            "user_ai_credentials",
            "cm_auth_tokens",
            "content_cache",
        ):
            await self.gw.execute(
                [
                    f"DELETE FROM {safe_identifier(table)} WHERE "
                    + ("user_id = " + _lit(user_id)
                       if table not in {"user_preferences", "cm_auth_tokens"}
                       else "id = " + _lit(user_id))
                ]
            )

    # ── usage ────────────────────────────────────────────────────────────────

    async def usage(self, *, snapshot: Any, active_sessions: int,
                    max_active_sessions: int) -> Usage:
        return Usage(
            question_credits_used=snapshot.used,
            question_credits_limit=snapshot.limit,
            window_start=snapshot.window_start,
            window_end=snapshot.window_end,
            active_sessions=active_sessions,
            max_active_sessions=max_active_sessions,
            min_plan_credits=self.credit_config.min_plan_questions,
        )

    # ── progress ─────────────────────────────────────────────────────────────

    async def progress(self, user_id: str) -> ProgressResponse:
        stats = await self._stats_row(user_id)
        mastery_rows = await self.gw.query_all(
            f"SELECT concept, practice_count, mastery, last_practiced_at "
            f"FROM {safe_identifier('concept_progress')} "
            f"WHERE user_id = {_lit(user_id)} ORDER BY mastery ASC, practice_count DESC"
        )
        activity = await self._activity(user_id)
        mistakes = await self.mistakes.for_user(user_id, limit=200)
        due = await self._due_reviews(user_id)

        mastery = [
            ConceptProgressRow(
                concept=str(row["concept"]),
                practice_count=int(row.get("practice_count", 0) or 0),
                mastery=min(1.0, float(row.get("mastery", 0.0) or 0.0)),
                last_practiced_at=row.get("last_practiced_at"),
            )
            for row in mastery_rows
        ]

        return ProgressResponse(
            xp=int(stats.get("xp", 0) or 0),
            level=int(stats.get("level", 1) or 1),
            current_streak=int(stats.get("current_streak", 0) or 0),
            longest_streak=int(stats.get("longest_streak", 0) or 0),
            mastery=mastery,
            weaknesses=_weaknesses(mistakes),
            mistake_type_counts=_mistake_counts(mistakes),
            activity=activity,
            due_reviews=due,
        )

    async def _stats_row(self, user_id: str) -> dict[str, Any]:
        row = await self.gw.query_one(
            f"SELECT xp, level, current_streak, longest_streak, "
            f"last_active_local_date FROM {safe_identifier('user_stats')} "
            f"WHERE user_id = {_lit(user_id)}"
        )
        return row or {}

    async def _activity(self, user_id: str) -> list[DailyActivity]:
        """Activity per day, with gaps filled.

        The chart draws a continuous week, so a day with no answers must appear as
        zero rather than be missing: a gap in the data would read as "we do not
        know" instead of "you did nothing that day".
        """
        rows = await self.gw.query_all(
            f"SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS n "
            f"FROM {safe_identifier('user_stats_events')} "
            f"WHERE user_id = {_lit(user_id)} AND event = 'question_xp' "
            "GROUP BY day ORDER BY day DESC LIMIT 120"
        )
        by_day = {str(row["day"]): int(row["n"]) for row in rows}
        today = datetime.now(UTC).date()
        out: list[DailyActivity] = []
        for offset in range(6, -1, -1):
            day = (today - timedelta(days=offset)).isoformat()
            out.append(DailyActivity(date=day, passed_questions=by_day.get(day, 0)))
        return out

    async def _due_reviews(self, user_id: str) -> int:
        row = await self.gw.query_one(
            f"SELECT COUNT(*) AS n FROM {safe_identifier('review_queue')} "
            f"WHERE user_id = {_lit(user_id)} AND review_due_at <= {_lit(now_iso())}"
        )
        return int((row or {}).get("n", 0) or 0)

    # ── mistakes, reviews, cards ─────────────────────────────────────────────

    async def mistake_list(self, user_id: str, *, limit: int = 50) -> MistakeList:
        rows = await self.mistakes.for_user(user_id, limit=limit + 1)
        has_more = len(rows) > limit
        return MistakeList(
            items=[_mistake_entry(row) for row in rows[:limit]],
            has_more=has_more,
        )

    async def review_queue(self, user_id: str) -> ReviewQueueResponse:
        rows = await self.gw.query_all(
            f"SELECT id, concept, review_due_at, priority, box FROM "
            f"{safe_identifier('review_queue')} WHERE user_id = {_lit(user_id)} "
            "ORDER BY review_due_at ASC LIMIT 50"
        )
        return ReviewQueueResponse(
            items=[
                ReviewItem(
                    id=str(row["id"]),
                    concept=str(row["concept"]),
                    review_due_at=str(row["review_due_at"]),
                    priority=str(row.get("priority", "normal")),
                    box=int(row.get("box", 1) or 1),
                )
                for row in rows
            ]
        )

    async def saved_cards_for(self, user_id: str) -> SavedCardsResponse:
        rows = await self.saved_cards.for_user(user_id)
        items: list[SavedCard] = []
        for row in rows:
            content = await self._card_content(row)
            if content is None:
                continue
            items.append(
                SavedCard(
                    id=str(row["id"]),
                    slug=str(row.get("slug", "")),
                    title=str(content.get("title", "")),
                    approach_id=str(row.get("approach_id", "brute_force")),
                    kind=str(row.get("card_type", "concept")),
                    created_at=str(row.get("created_at", "")),
                )
            )
        return SavedCardsResponse(items=items)

    async def _card_content(self, row: dict[str, Any]) -> dict[str, Any] | None:
        raw = row.get("content_json")
        if not raw:
            return None
        try:
            content = json.loads(str(raw))
        except json.JSONDecodeError:
            return None
        return content if isinstance(content, dict) else None


# ── helpers ────────────────────────────────────────────────────────────────


def _lit(value: str) -> str:
    from ..repositories.sql import encode

    return encode(value)


def _mistake_entry(row: dict[str, Any]) -> MistakeEntry:
    return MistakeEntry(
        id=str(row["id"]),
        concept=str(row.get("concept", "brute_force")),
        mistake_type=MistakeType(str(row.get("mistake_type", "other"))),
        short_explanation=str(row.get("short_explanation", ""))[:500],
        problem_url=str(row.get("problem_url", ""))[:500],
        source=str(row.get("source", "judge")),
        created_at=str(row.get("created_at", "")),
    )


def _mistake_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("mistake_type", "other"))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _weaknesses(rows: list[dict[str, Any]]) -> list[Weakness]:
    """Group mistakes by (concept, mistake_type) and weight by recency."""
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    now = datetime.now(UTC)

    for row in rows:
        concept = str(row.get("concept", "unknown"))
        mistake = str(row.get("mistake_type", "other"))
        bucket = buckets.setdefault(
            (concept, mistake),
            {"count": 0.0, "problems": set(), "last": ""},
        )
        created = str(row.get("created_at", ""))
        age_days = _age_days(created, now)
        bucket["count"] += _decay(age_days)
        url = str(row.get("problem_url", ""))
        if url:
            bucket["problems"].add(url)
        if created > bucket["last"]:
            bucket["last"] = created

    out: list[Weakness] = []
    for (concept, mistake), bucket in buckets.items():
        if not bucket["problems"]:
            # A mistake with no problem behind it cannot be shown as a distinct
            # weakness; the model requires at least one, and inventing a count
            # would overstate the case.
            continue
        out.append(
            Weakness(
                concept=concept,
                mistake_type=MistakeType(mistake),
                weighted_count=round(float(bucket["count"]), 3),
                distinct_problems=len(bucket["problems"]),
                last_seen_at=str(bucket["last"]),
            )
        )
    out.sort(key=lambda w: w.weighted_count, reverse=True)
    return out[:8]


def _age_days(created_iso: str, now: Any) -> float:
    if not created_iso:
        return 365.0
    try:
        when = datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
    except ValueError:
        return 365.0
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    delta = float((now - when).total_seconds() / 86400.0)
    return max(0.0, delta)


def _decay(age_days: float) -> float:
    """Exponential recency weight. Recent mistakes count roughly twice old ones."""
    weight: float = exp(-age_days / _HALF_LIFE_DAYS)
    return weight


__all__ = ["ProgressService", "new_id"]
