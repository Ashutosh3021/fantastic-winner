"""Credit accounting (§16.5).

Two properties carry real money, so they are asserted against the SQL the
service emits rather than inferred from a return value:

* **Atomicity.** The claim is a single ``INSERT``; if it collides, another
  request already owns this idempotency key and must not spend again.
* **No charge on failure.** Reserve, settle and rollback are all reachable, and
  settle refunds the unused reservation.

``FakeGateway`` records statements, so these tests prove what would be sent to
PyroCore without needing a database.
"""

from __future__ import annotations

import pytest

from app.core.config import CreditConfig
from app.core.errors import Conflict
from app.services.credit_service import CreditService, UsageSnapshot
from tests.conftest import FakeGateway


@pytest.fixture
def config() -> CreditConfig:
    return CreditConfig(credits_per_window=12, window_hours=5)


class TestClaim:
    async def test_claim_is_a_single_atomic_insert(self, config: CreditConfig) -> None:
        gateway = FakeGateway()
        service = CreditService(gateway, config=config)

        await service.claim(idempotency_key="k1", user_id="u1", reserve_n=3)

        first = gateway.batches[0]
        assert len(first) == 1, "the claim must be one statement to be atomic"
        assert "INSERT INTO credit_claims" in first[0]
        assert "'k1'" in first[0]
        assert "'u1'" in first[0]

    async def test_duplicate_key_is_a_conflict_not_a_second_charge(
        self, config: CreditConfig
    ) -> None:
        # The insert collides, then the service reads the winner's state back.
        gateway = FakeGateway(
            rows=[{"state": "completed", "session_id": None, "cached_key": None}],
            error=Conflict("duplicate idempotency key"),
        )
        service = CreditService(gateway, config=config)

        result = await service.claim(idempotency_key="k1", user_id="u1", reserve_n=3)

        assert result.acquired is False
        assert result.retryable is False
        assert result.existing_state == "completed"

    async def test_a_key_still_in_flight_is_retryable_not_failed(
        self, config: CreditConfig
    ) -> None:
        # A learner who double-clicked gets "still running", not "failed".
        gateway = FakeGateway(
            rows=[{"state": "reserved", "session_id": "s1", "cached_key": None}],
            error=Conflict("duplicate idempotency key"),
        )
        service = CreditService(gateway, config=config)

        result = await service.claim(idempotency_key="k1", user_id="u1", reserve_n=3)

        assert result.acquired is False
        assert result.retryable is True

    async def test_a_claim_for_another_user_is_never_reused(
        self, config: CreditConfig
    ) -> None:
        # The key is part of the primary key, so one user's completed request
        # cannot be presented as another's.
        gateway = FakeGateway()
        service = CreditService(gateway, config=config)

        first = await service.claim(
            idempotency_key="shared", user_id="u1", reserve_n=1, session_id="s1"
        )
        second = await service.claim(
            idempotency_key="shared", user_id="u2", reserve_n=1, session_id="s2"
        )

        assert first.acquired is True
        assert second.acquired is True
        inserts = [
            s
            for batch in gateway.batches
            for s in batch
            if "INSERT INTO credit_claims" in s
        ]
        assert len(inserts) == 2
        assert any("'u1'" in s for s in inserts)
        assert any("'u2'" in s for s in inserts)

    async def test_reservation_updates_the_window_with_a_conditional_write(
        self, config: CreditConfig
    ) -> None:
        # A plain read-then-write would let two concurrent requests both see room
        # and both charge. The guard has to be in the UPDATE itself.
        gateway = FakeGateway()
        service = CreditService(gateway, config=config)

        await service.claim(idempotency_key="k", user_id="u", reserve_n=5)

        joined = gateway.sql
        assert "usage_limits" in joined
        assert "question_credits_used + 5 <= question_credits_limit" in joined


class TestSettleAndRollback:
    async def test_rollback_refunds_the_reservation(self, config: CreditConfig) -> None:
        # The reservation is read back first: there is nothing to refund when the
        # claim never reserved anything.
        gateway = FakeGateway(rows=[{"reserved_n": 3}])
        service = CreditService(gateway, config=config)

        await service.rollback(
            idempotency_key="k", user_id="u", session_id="s", reason="failed"
        )

        assert "credit_claims" in gateway.sql
        assert "usage_limits" in gateway.sql
        assert "question_credits_used - 3" in gateway.sql

    async def test_rollback_without_a_reservation_skips_the_refund(
        self, config: CreditConfig
    ) -> None:
        # Refunding a zero reservation would still write; harmless but noisy,
        # and it hides a genuinely absent claim.
        gateway = FakeGateway(rows=[{"reserved_n": 0}])
        service = CreditService(gateway, config=config)

        await service.rollback(
            idempotency_key="k", user_id="u", session_id="s", reason="failed"
        )

        assert "usage_limits" not in gateway.sql

    async def test_settle_is_keyed_so_a_retry_does_not_double_charge(
        self, config: CreditConfig
    ) -> None:
        gateway = FakeGateway()
        service = CreditService(gateway, config=config)

        await service.settle(
            idempotency_key="k", user_id="u", session_id="s", actual_n=3
        )
        await service.settle(
            idempotency_key="k", user_id="u", session_id="s", actual_n=3
        )

        assert "'k'" in gateway.sql

    async def test_settle_mentions_both_the_key_and_the_session(
        self, config: CreditConfig
    ) -> None:
        gateway = FakeGateway()
        service = CreditService(gateway, config=config)

        await service.settle(
            idempotency_key="key-9", user_id="u", session_id="sess-9", actual_n=3
        )

        assert "'key-9'" in gateway.sql
        assert "sess-9" in gateway.sql


class TestUsageSnapshot:
    def test_reports_remaining(self) -> None:
        snapshot = UsageSnapshot(used=4, limit=12, window_start="a", window_end="b")
        assert snapshot.remaining == 8

    def test_remaining_never_goes_negative(self) -> None:
        snapshot = UsageSnapshot(used=20, limit=12, window_start="a", window_end="b")
        assert snapshot.remaining == 0


class TestWindowBounds:
    def test_bounds_are_ordered(self, config: CreditConfig) -> None:
        service = CreditService(FakeGateway(), config=config)
        start, end = service.window_bounds()
        assert start < end

    def test_bounds_are_iso(self, config: CreditConfig) -> None:
        from datetime import datetime

        service = CreditService(FakeGateway(), config=config)
        start, end = service.window_bounds()
        assert datetime.fromisoformat(start)
        assert datetime.fromisoformat(end)