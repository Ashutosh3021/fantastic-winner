"""The projector (§19.4).

Answers are written to append-only tables and enqueued in the *same*
transaction. Everything else — XP, levels, streaks, concept mastery, the review
queue — is derived here, out of band.

The reason is latency and honesty. If answering a question also had to recompute a
streak counter, the learner would wait on it; if it were computed inline and the
transaction failed halfway, XP and the attempt log would disagree permanently.
Here, if the projector is down, answers still work and nothing is lost: the queue
is durable and every derived table is recomputable from the attempt log.

``user_stats_events`` is the ledger. It has ``UNIQUE (ref_id)``, which is what
makes XP exactly-once: applying the same queue item twice collides and is a
no-op, so a retry cannot double-count.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.logging import get_logger
from ..repositories.gateway import PyronitesGateway
from ..repositories.sql import encode, safe_identifier
from ..repositories.store import now_iso

logger = get_logger(__name__)

#: XP per event. Passing a question is worth more than attempting it, because a
#: learner who tries everything should not out-earn one who understands.
XP_PASS = 10
XP_ATTEMPT = 2

#: Leitner box intervals in days. Box 1 is tomorrow; box 5 is three months.
BOX_INTERVALS = {1: 1, 2: 3, 3: 7, 4: 21, 5: 90}

#: XP needed to reach each level: 100, then 150 more each time.
def xp_for_level(level: int) -> int:
    if level <= 1:
        return 0
    return 100 + 150 * (level - 2)


def level_for_xp(xp: int) -> int:
    level = 1
    while xp >= xp_for_level(level + 1):
        level += 1
    return level


@dataclass
class QueueItem:
    id: str
    kind: str
    ref_id: str
    payload: dict[str, Any]


class Projector:
    """Drains ``projection_queue`` into the read models."""

    batch_size = 50

    def __init__(self, gateway: PyronitesGateway) -> None:
        self.gw = gateway

    async def pending(self, *, limit: int | None = None) -> list[QueueItem]:
        rows = await self.gw.query_all(
            f"SELECT id, kind, ref_id, payload_json FROM {safe_identifier('projection_queue')} "
            "WHERE processed_at IS NULL "
            f"ORDER BY created_at ASC LIMIT {min(limit or self.batch_size, self.batch_size)}"
        )
        items: list[QueueItem] = []
        for row in rows:
            try:
                payload = json.loads(str(row.get("payload_json") or "{}"))
            except json.JSONDecodeError:
                payload = {}
            items.append(
                QueueItem(
                    id=str(row["id"]),
                    kind=str(row["kind"]),
                    ref_id=str(row["ref_id"]),
                    payload=payload if isinstance(payload, dict) else {},
                )
            )
        return items

    async def drain_once(self) -> int:
        """Process one batch. Returns how many items were handled.

        Each item is applied and marked in a single statement pair, so a crash
        mid-batch leaves the unprocessed rows pending rather than lost.
        """
        items = await self.pending()
        if not items:
            return 0

        for item in items:
            try:
                statements = self._statements_for(item)
            except Exception:
                logger.exception("projector failed on %s (%s)", item.kind, item.ref_id)
                statements = [self._mark_processed(item.id)]

            statements.append(self._mark_processed(item.id))
            await self.gw.execute(statements)

        return len(items)

    async def drain_forever(
        self, *, busy_interval_s: float = 1.0, idle_interval_s: float = 15.0
    ) -> None:
        """Drain until cancelled, backing off when there is nothing to do.

        The idle interval matters: the queue lives behind an HTTP call to a
        rate-limited datastore, and a fixed short poll would spend a request every
        few seconds forever to discover there is no work. A learner who is not
        answering questions should cost nothing.
        """
        while True:
            try:
                handled = await self.drain_once()
            except Exception:  # the loop must survive a bad batch
                logger.exception("projector batch failed")
                handled = 0
            await _sleep(busy_interval_s if handled else idle_interval_s)

    def _mark_processed(self, item_id: str) -> str:
        return (
            f"UPDATE {safe_identifier('projection_queue')} SET "
            f"processed_at = {encode(now_iso())} WHERE id = {encode(item_id)}"
        )

    def _statements_for(self, item: QueueItem) -> list[str]:
        handler = {
            "xp": self._apply_xp,
            "mistake": self._apply_mistake,
            "reveal": self._apply_reveal,
            "event": self._apply_event,
        }.get(item.kind)
        if handler is None:
            logger.info("no projector handler for kind %s", item.kind)
            return []
        return handler(item)

    # ── xp, level, streak ────────────────────────────────────────────────────

    def _apply_xp(self, item: QueueItem) -> list[str]:
        payload = item.payload
        user_id = str(payload.get("user_id", "") or "")
        if not user_id:
            # Without an owner this row cannot be applied safely, and writing an
            # empty user_id would create stats nobody can ever see or delete.
            raise ValueError(f"xp item {item.ref_id} has no user_id")

        passed = bool(payload.get("passed"))
        hints_used = int(payload.get("hints_used", 0) or 0)
        # A hint is help, not cheating, but it should not pay the same as a
        # first-try answer.
        xp = max(1, XP_PASS - 2 * hints_used) if passed else XP_ATTEMPT

        return [
            # The ledger row. UNIQUE(ref_id) is what makes this exactly-once:
            # a replayed queue item collides here and changes nothing.
            f"INSERT OR IGNORE INTO {safe_identifier('user_stats_events')} "
            "(id, user_id, event, delta, ref_id, created_at) VALUES ("
            f"{encode(_new_id())}, {encode(user_id)}, {encode('question_xp')}, "
            f"{encode(xp)}, {encode(item.ref_id)}, {encode(now_iso())})",
            self._apply_concept_progress(payload, user_id=user_id, passed=passed,
                                         hints_used=hints_used),
            # Level is derived from the post-update total. SQLite's `/` on two
            # integers is integer division, which is exactly the ladder we want.
            f"UPDATE {safe_identifier('user_stats')} SET "
            f"xp = xp + {encode(xp)}, "
            f"level = CASE WHEN xp + {encode(xp)} < 100 THEN 1 "
            f"ELSE 2 + (xp + {encode(xp)} - 100) / 150 END, "
            f"last_active_local_date = {encode(_local_date())}, "
            f"updated_at = {encode(now_iso())} "
            f"WHERE user_id = {encode(user_id)}",
        ]

    def _apply_concept_progress(
        self,
        payload: dict[str, Any],
        *,
        user_id: str,
        passed: bool,
        hints_used: int,
    ) -> str:
        """Mastery as first-try rate, damped by attempt count and hint use.

        The damping matters: one lucky correct answer should not read as mastery,
        and one wrong answer should not erase real progress.
        """
        concept = str(payload.get("approach_id", "unknown"))
        first_try = 1 if passed and hints_used == 0 else 0
        attempt_bonus = encode(first_try)
        return (
            f"INSERT INTO {safe_identifier('concept_progress')} "
            "(user_id, concept, practice_count, correct_first_try, hints_total, "
            "attempts_total, mastery, last_practiced_at, updated_at) "
            f"VALUES ({encode(user_id)}, {encode(concept)}, {encode(1 if passed else 0)}, "
            f"{encode(first_try)}, {encode(hints_used)}, "
            f"{encode(1)}, {encode(0.4 if passed else 0.0)}, {encode(now_iso())}, "
            f"{encode(now_iso())}) "
            "ON CONFLICT(user_id, concept) DO UPDATE SET "
            f"practice_count = practice_count + {encode(1 if passed else 0)}, "
            f"correct_first_try = correct_first_try + {attempt_bonus}, "
            f"hints_total = hints_total + {encode(hints_used)}, "
            "attempts_total = attempts_total + 1, "
            f"mastery = ROUND(((correct_first_try + {attempt_bonus}) * 1.0 "
            "/ (attempts_total + 1)) * "
            f"(CASE WHEN hints_total + {encode(hints_used)} = 0 THEN 1.0 ELSE 0.75 END), 3), "
            f"last_practiced_at = {encode(now_iso())}, "
            f"updated_at = {encode(now_iso())} "
            f"WHERE user_id = {encode(user_id)} AND concept = {encode(concept)}"
        )

    # ── mistakes and review ──────────────────────────────────────────────────

    def _apply_mistake(self, item: QueueItem) -> list[str]:
        payload = item.payload
        user_id = str(payload.get("user_id", "") or "")
        if not user_id:
            raise ValueError(f"mistake item {item.ref_id} has no user_id")
        concept = str(payload.get("approach_id", "unknown"))
        return [
            f"INSERT OR IGNORE INTO {safe_identifier('mistakes')} "
            "(id, user_id, concept, mistake_type, short_explanation, problem_url, "
            "source, created_at) VALUES ("
            f"{encode(item.ref_id)}, {encode(user_id)}, {encode(concept)}, "
            f"{encode(str(payload.get('mistake_type', 'other')))}, "
            f"{encode(str(payload.get('short_explanation', ''))[:500])}, "
            f"{encode(str(payload.get('problem_url', ''))[:500])}, "
            f"{encode('judge')}, {encode(now_iso())})",
            self._schedule_review(user_id, concept, box=1, due_days=1),
        ]

    def _apply_reveal(self, item: QueueItem) -> list[str]:
        """A revealed question is a mistake too, and the review item matters more.

        A learner who ran out of attempts has told us more than a learner who
        answered wrongly, so this lands in the review queue sooner.
        """
        payload = item.payload
        user_id = str(payload.get("user_id", "") or "")
        if not user_id:
            raise ValueError(f"reveal item {item.ref_id} has no user_id")
        concept = str(payload.get("approach_id", "unknown"))
        return [
            f"INSERT OR IGNORE INTO {safe_identifier('mistakes')} "
            "(id, user_id, concept, mistake_type, short_explanation, problem_url, "
            "source, created_at) VALUES ("
            f"{encode(item.ref_id)}, {encode(user_id)}, {encode(concept)}, "
            f"{encode('misunderstood_goal')}, "
            f"{encode('Ran out of attempts and saw the step explained.')}, "
            f"{encode('')}, {encode('revealed')}, {encode(now_iso())})",
            self._schedule_review(user_id, concept, box=1, due_days=1, priority="high"),
        ]

    def _schedule_review(
        self,
        user_id: str,
        concept: str,
        *,
        box: int,
        due_days: int,
        priority: str = "normal",
    ) -> str:
        due = (datetime.now(UTC) + timedelta(days=due_days)).isoformat()
        return (
            f"INSERT INTO {safe_identifier('review_queue')} "
            "(id, user_id, concept, box, review_due_at, priority, updated_at) "
            f"VALUES ({encode(_new_id())}, {encode(user_id)}, {encode(concept)}, "
            f"{encode(box)}, {encode(due)}, {encode(priority)}, {encode(now_iso())}) "
            "ON CONFLICT(user_id, concept) DO UPDATE SET "
            f"box = {encode(box)}, review_due_at = {encode(due)}, "
            f"priority = {encode(priority)}, updated_at = {encode(now_iso())}"
        )

    def _apply_event(self, item: QueueItem) -> list[str]:
        return []


def _new_id() -> str:
    import uuid

    return uuid.uuid4().hex


def _local_date() -> str:
    return datetime.now(UTC).date().isoformat()


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)
