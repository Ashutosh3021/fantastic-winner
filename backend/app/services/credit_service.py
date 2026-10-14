"""Credit service: claim, reserve, settle, rollback (§16.5).

This is the module where the design changed most, and the change is the point.
v1 used reserve → commit/rollback driven by a **read** ("has this idempotency
key been processed?"), with the AI call sitting between the read and the write.
Two tabs issuing the same key at the same instant both pass the read, both call
the AI, one wins the counter update, and the other rolls back and returns 503 -
for a request that actually succeeded on the other tab.

v2 replaces the read with a **write-time claim**. The INSERT into
``credit_claims`` *is* the idempotency guard, because the key is the primary key.
Concurrent identical requests produce exactly one winner and one clean loser
that reads the winner's state. There is no read-then-write window, and the AI
call cannot be entered twice for the same key.

The reserve is a single conditional UPDATE whose affected-row count *is* the
answer:

    UPDATE usage_limits
       SET question_credits_used = question_credits_used + :n
     WHERE user_id = :u
       AND window_end > :now
       AND question_credits_used + :n <= question_credits_limit

``changes == 1`` means reserved. ``changes == 0`` means the window had expired or
the learner is short, and nothing was mutated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.config import CreditConfig
from ..core.errors import Conflict, CreditsExhausted, GenerationInProgress, InsufficientCredits
from ..core.logging import get_logger
from ..repositories.gateway import PyronitesGateway
from ..repositories.sql import encode, in_list, safe_identifier
from ..repositories.store import new_id, now_iso

logger = get_logger(__name__)

CLAIM_RESERVED = "reserved"
CLAIM_COMMITTED = "committed"
CLAIM_ROLLED_BACK = "rolled_back"

@dataclass(frozen=True)
class UsageSnapshot:
    used: int
    limit: int
    window_start: str
    window_end: str
    active_sessions: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

@dataclass(frozen=True)
class ClaimResult:
    """What ``claim()`` decided, and what the caller must do next."""

    # : True when this request owns the claim and may proceed to spend credits.
    acquired: bool
    # : State of an existing claim when ``acquired`` is False.
    existing_state: str | None = None
    existing_session_id: str | None = None
    existing_cached_key: str | None = None
    # : Set when the reserve itself failed; the claim is already rolled back.
    reserve_error: str | None = None
    shortfall: int = 0
    reset_at: str | None = None

    @property
    def retryable(self) -> bool:
        return self.existing_state == CLAIM_RESERVED

class CreditService:
    def __init__(
        self,
        gateway: PyronitesGateway,
        config: CreditConfig,
    ) -> None:
        self.gw = gateway
        self.config = config

    # -- windows ---

    def window_bounds(self, *, now: datetime | None = None) -> tuple[str, str]:
        """A window runs exactly ``window_hours`` from its start (§16.5).

        A rolling window was considered and rejected: it is fairer per credit
        but much harder to explain, and the product's own copy ("Resets at
        4:54 PM") describes a fixed window.
        """
        moment = now or datetime.now(UTC)
        start = moment
        end = moment + timedelta(hours=self.config.window_hours)
        return _iso(start), _iso(end)

    async def ensure_window(self, *, user_id: str) -> None:
        """Create this user's active window if they do not have one.

        The partial unique index makes concurrent creation impossible to fork:
        the second insert fails loudly, which is the behaviour we want (§17.3).
        """
        start, end = self.window_bounds()
        exists = await self.gw.query_one(
            f"SELECT id FROM {safe_identifier('usage_limits')} "
            f"WHERE user_id = {encode(user_id)} AND window_end > {encode(now_iso())} LIMIT 1"
        )
        if exists:
            return
        try:
            await self.gw.execute(
                [
                    "INSERT INTO usage_limits "
                    "(id, user_id, window_start, window_end, question_credits_used, "
                    "question_credits_limit, active_sessions, ai_tokens_used, analyses_used, "
                    "created_at) VALUES ("
                    f"{encode(new_id())}, {encode(user_id)}, {encode(start)}, {encode(end)}, "
                    f"0, {encode(self.config.credits_per_window)}, 0, 0, 0, {encode(now_iso())})"
                ]
            )
        except Exception:
            if await self.gw.query_one(
                f"SELECT id FROM {safe_identifier('usage_limits')} "
                f"WHERE user_id = {encode(user_id)} AND window_end > {encode(now_iso())} LIMIT 1"
            ):
                return
            raise

    async def usage(self, *, user_id: str) -> UsageSnapshot:
        await self.ensure_window(user_id=user_id)
        row = await self.gw.query_one(
            f"SELECT question_credits_used, question_credits_limit, window_start, window_end, "
            f"active_sessions FROM {safe_identifier('usage_limits')} "
            f"WHERE user_id = {encode(user_id)} AND window_end > {encode(now_iso())} "
            "ORDER BY window_end DESC LIMIT 1"
        )
        if row is None:
            # The window expired between ensure and read; start a fresh one.
            start, end = self.window_bounds()
            return UsageSnapshot(0, self.config.credits_per_window, start, end)

        return UsageSnapshot(
            used=int(row["question_credits_used"] or 0),
            limit=int(row["question_credits_limit"] or self.config.credits_per_window),
            window_start=str(row["window_start"]),
            window_end=str(row["window_end"]),
            active_sessions=int(row["active_sessions"] or 0),
        )

    # -- claims ---

    async def claim(
        self,
        *,
        idempotency_key: str,
        user_id: str,
        reserve_n: int,
        session_id: str | None = None,
    ) -> ClaimResult:
        """Take ownership of a credit spend, or report who already owns it."""
        try:
            await self.gw.execute(
                [
                    f"INSERT INTO {safe_identifier('credit_claims')} "
                    "(idempotency_key, user_id, state, reserved_n, actual_n, session_id, "
                    "cached_key, created_at, updated_at) VALUES ("
                    f"{encode(idempotency_key)}, {encode(user_id)}, {encode(CLAIM_RESERVED)}, "
                    f"{encode(reserve_n)}, NULL, {encode(session_id)}, NULL, "
                    f"{encode(now_iso())}, {encode(now_iso())})"
                ]
            )
        except Exception:
            existing = await self.gw.query_one(
                f"SELECT state, session_id, cached_key FROM {safe_identifier('credit_claims')} "
                f"WHERE idempotency_key = {encode(idempotency_key)}"
            )
            if existing is None:
                raise
            return ClaimResult(
                acquired=False,
                existing_state=str(existing["state"]),
                existing_session_id=(
                    str(existing["session_id"]) if existing.get("session_id") else None
                ),
                existing_cached_key=(
                    str(existing["cached_key"]) if existing.get("cached_key") else None
                ),
            )

        await self._ledger(
            idempotency_key=idempotency_key,
            user_id=user_id,
            session_id=session_id,
            operation="reserve",
            delta=-reserve_n,
            reason="claim",
        )

        return await self._reserve(
            idempotency_key=idempotency_key,
            user_id=user_id,
            session_id=session_id,
            reserve_n=reserve_n,
        )

    async def _reserve(
        self, *, idempotency_key: str, user_id: str, session_id: str | None, reserve_n: int
    ) -> ClaimResult:
        await self.ensure_window(user_id=user_id)
        snapshot = await self.usage(user_id=user_id)

        # The conditional update. One statement, one answer.
        batch = await self.gw.execute(
            [
                f"UPDATE {safe_identifier('usage_limits')} "
                f"SET question_credits_used = question_credits_used + {encode(reserve_n)} "
                f"WHERE user_id = {encode(user_id)} "
                f"AND window_end > {encode(now_iso())} "
                f"AND question_credits_used + {encode(reserve_n)} <= question_credits_limit"
            ]
        )
        if batch.changes() == 1:
            return ClaimResult(acquired=True)

        shortfall = max(0, reserve_n - snapshot.remaining)
        await self.rollback(
            idempotency_key=idempotency_key,
            user_id=user_id,
            session_id=session_id,
            reason="insufficient_credits",
        )
        return ClaimResult(
            acquired=False,
            existing_state=CLAIM_ROLLED_BACK,
            reserve_error="insufficient_credits",
            shortfall=shortfall,
            reset_at=snapshot.window_end,
        )

    async def settle(
        self,
        *,
        idempotency_key: str,
        user_id: str,
        session_id: str | None,
        actual_n: int,
        cached_key: str | None = None,
    ) -> None:
        """Commit the claim at its true cost.

        A plan that turned out to have four questions instead of five keeps the
        fifth credit: credits meter questions generated, not questions reserved.
        """
        reserved = await self._reserved_n(idempotency_key)
        refund = max(0, reserved - actual_n)

        statements = [
            f"UPDATE {safe_identifier('credit_claims')} SET state = {encode(CLAIM_COMMITTED)}, "
            f"actual_n = {encode(actual_n)}, cached_key = {encode(cached_key)}, "
            f"updated_at = {encode(now_iso())} "
            f"WHERE idempotency_key = {encode(idempotency_key)}"
        ]
        if refund:
            statements.append(
                f"UPDATE {safe_identifier('usage_limits')} "
                f"SET question_credits_used = MAX(0, question_credits_used - {encode(refund)}) "
                f"WHERE user_id = {encode(user_id)}"
            )

        await self.gw.execute(statements)
        await self._ledger(
            idempotency_key=idempotency_key,
            user_id=user_id,
            session_id=session_id,
            operation="settle",
            delta=refund,
            reason="settle",
        )

    async def rollback(
        self,
        *,
        idempotency_key: str,
        user_id: str,
        session_id: str | None,
        reason: str,
    ) -> None:
        """Refund in full. A failure must never cost the learner (§21)."""
        reserved = await self._reserved_n(idempotency_key)
        statements = [
            f"UPDATE {safe_identifier('credit_claims')} SET state = {encode(CLAIM_ROLLED_BACK)}, "
            f"updated_at = {encode(now_iso())} "
            f"WHERE idempotency_key = {encode(idempotency_key)}"
        ]
        if reserved:
            statements.append(
                f"UPDATE {safe_identifier('usage_limits')} "
                f"SET question_credits_used = MAX(0, question_credits_used - {encode(reserved)}) "
                f"WHERE user_id = {encode(user_id)}"
            )
        await self.gw.execute(statements)
        await self._ledger(
            idempotency_key=idempotency_key,
            user_id=user_id,
            session_id=session_id,
            operation="rollback",
            delta=reserved,
            reason=reason,
        )

    async def _reserved_n(self, idempotency_key: str) -> int:
        row = await self.gw.query_one(
            f"SELECT reserved_n FROM {safe_identifier('credit_claims')} "
            f"WHERE idempotency_key = {encode(idempotency_key)}"
        )
        return int(row["reserved_n"] or 0) if row else 0

    async def _ledger(
        self,
        *,
        idempotency_key: str,
        user_id: str,
        session_id: str | None,
        operation: str,
        delta: int,
        reason: str,
    ) -> None:
        """Append-only audit. Never read to decide whether to charge."""
        statement = (
            f"INSERT OR IGNORE INTO {safe_identifier('credit_ledger')} "
            "(id, user_id, session_id, idempotency_key, operation, delta, reason, created_at) "
            f"VALUES ({encode(new_id())}, {encode(user_id)}, {encode(session_id)}, "
            f"{encode(idempotency_key)}, {encode(operation)}, {encode(delta)}, "
            f"{encode(reason)}, {encode(now_iso())})"
        )
        await self.gw.execute([statement])

    # -- reconciliation ---

    async def reconcile(self, *, user_id: str) -> dict[str, Any]:
        """Compare the fast counter against the claim ledger.

        This is what makes "credits reconcile" a checkable statement rather than
        a hope (ARCHITECTURE §28). Any drift is a bug worth a page.
        """
        snapshot = await self.usage(user_id=user_id)
        row = await self.gw.query_one(
            f"SELECT COALESCE(SUM(CASE WHEN state = {encode(CLAIM_COMMITTED)} "
            f"THEN reserved_n ELSE 0 END), 0) AS committed, "
            f"COALESCE(SUM(CASE WHEN state = {encode(CLAIM_COMMITTED)} "
            f"THEN COALESCE(actual_n, 0) ELSE 0 END), 0) AS actual "
            f"FROM {safe_identifier('credit_claims')} "
            f"WHERE user_id = {encode(user_id)}"
        )
        committed = int(row["committed"] or 0) if row else 0
        actual = int(row["actual"] or 0) if row else 0
        return {
            "counter": snapshot.used,
            "committed_reserved": committed,
            "committed_actual": actual,
            "agrees": snapshot.used == actual,
        }

def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

def raise_for_claim(result: ClaimResult, *, requested: int, window: UsageSnapshot) -> None:
    """Translate a non-acquired claim into the right typed error (§16.10)."""
    if result.retryable:
        raise GenerationInProgress(
            "That request is already being generated.", retry_after_sec=5
        )
    if result.existing_state == CLAIM_COMMITTED:
        # A duplicate of a *completed* request: the caller should return the
        # stored result, which it does by reading its claim.
        return
    if result.reserve_error == "insufficient_credits":
        raise InsufficientCredits(
            f"You need {result.shortfall} more question credits for that.",
            shortfall=result.shortfall,
            reset_at=result.reset_at,
        )
    raise CreditsExhausted(
        "You've used all your question credits for this window.",
        reset_at=window.window_end,
    )

def active_session_check(count: int, limit: int, sessions: list[dict[str, Any]]) -> None:
    if count >= limit:
        raise Conflict(
            "You already have the maximum number of active problems.",
            extra={"active_sessions": sessions[:limit]},
        )

def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def session_ids(rows: list[dict[str, Any]]) -> str:
    """``IN (...)`` list for a set of ids, with the empty case handled."""
    return in_list([str(row.get("id")) for row in rows if row.get("id")])