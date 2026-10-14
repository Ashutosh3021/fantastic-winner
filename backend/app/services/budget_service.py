"""Spend, budgets and the cost kill-switch (§16.4, §16.7, §16.9, §22.3).

Credits meter *learning depth*. They do not meter *our bill*, and a zero-credit
action still costs tokens: reading a concept card, simplifying it, answering a
question, re-running an analysis. So there are four independent guards, none of
which is "the credit balance":

* **L1b per-IP AI budget** - the only control that survives "make five
  accounts", because five accounts share one source IP.
* **L3 per-user AI token budget**, ramped for accounts under 24 hours old.
* **Analysis caps** per (user, session, window), so "one learner, one problem,
  re-run four times a minute forever" is bounded.
* **L5 daily spend cap** with a degraded cache-only mode.

Response copy is deliberately soft. Households and campuses share IPs, and the
learner must not feel blamed for their flatmate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core.config import Settings
from ..core.errors import DegradedMode, IpBudgetExceeded, UsageGuard
from ..core.logging import get_logger
from ..repositories.sql import encode
from ..repositories.store import IpBudgetRepository, SpendRepository, now_iso
from .auth_service import Identity

logger = get_logger(__name__)

_IP_FRIENDLY = (
    "You've used a lot of CodeMentor on this network. Try again in a few minutes."
)
_USER_FRIENDLY = "You've done a lot of learning. Give it a few minutes and try again."

def ip_hash(client_ip: str | None) -> str:
    """IPs are hashed before storage: they are personal data, and they churn."""
    if not client_ip:
        return "unknown"
    return hashlib.sha256(f"cm-ip:{client_ip}".encode()).hexdigest()[:32]

@dataclass
class BudgetDecision:
    allowed: bool
    retry_after: int = 0

class BudgetService:
    def __init__(self, settings: Settings, spend: SpendRepository, ip_budget: IpBudgetRepository):
        self.settings = settings
        self.spend = spend
        self.ip_budget = ip_budget

    # -- L5 global cost safety ---

    async def degraded_mode(self) -> bool:
        """True when uncached generation must be refused (§16.9)."""
        if self.settings.degraded_mode:
            return True
        cap = self.settings.daily_spend_cap_usd
        if cap <= 0:
            return False
        day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        spent, _tokens = await self.spend.spend_since(since_iso=_iso(day_start))
        if spent >= cap:
            logger.warning("daily spend cap reached: %.4f / %.4f", spent, cap)
            return True
        if spent >= cap * self.settings.spend_alert_fraction:
            logger.warning("spend alert: %.4f of %.4f", spent, cap)
        return False

    async def require_not_degraded(self) -> None:
        if await self.degraded_mode():
            raise DegradedMode(
                "The mentor is resting to keep costs down. Saved concepts and your journal "
                "still work."
            )

    # -- L1b per-IP AI budget ---

    async def charge_ip(self, *, client_ip: str, tokens: int) -> None:
        """Record a generation and refuse the ones past the budget.

        Applied to every AI-generating request **regardless of authentication**.
        Authenticated and anonymous traffic draw from the same bucket, which is
        the entire point.
        """
        config = self.settings.ip_budget
        window_s = self.settings.credits.window_hours * 3600
        key = ip_hash(client_ip)

        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        daily = await self.ip_budget.daily_calls(ip_hash=key, day_start=_iso(today))
        if daily >= config.ai_calls_per_day:
            raise IpBudgetExceeded(_IP_FRIENDLY, retry_after_sec=3600)

        row = await self.ip_budget.record_call(ip_hash=key, tokens=tokens, window_s=window_s)
        if row is None:
            return
        calls = int(row.get("ai_calls") or 0)
        used_tokens = int(row.get("ai_tokens") or 0)

        if calls > config.ai_calls_per_5min:
            raise IpBudgetExceeded(_IP_FRIENDLY, retry_after_sec=300)
        if used_tokens > config.ai_tokens_per_window:
            raise IpBudgetExceeded(_IP_FRIENDLY, retry_after_sec=900)

    # -- L3 per-user AI budget ---

    async def charge_user(self, *, identity: Identity, tokens: int) -> None:
        config = self.settings.user_budget
        window_start = _iso(datetime.now(UTC) - timedelta(hours=self.settings.credits.window_hours))
        used = await self.spend.tokens_for_user_since(
            user_id=identity.user_id, since_iso=window_start
        )

        limit = config.ai_tokens_per_window
        if identity.is_new_account:
            # The ramp makes bulk signup expensive fast, and is invisible to an
            # honest learner because a real learner does not burn 150k tokens in
            # their first day.
            limit = config.new_account_token_budget

        if used + tokens > limit:
            raise UsageGuard(_USER_FRIENDLY, retry_after_sec=600)

    # -- analysis caps (-14.5) ---

    async def check_analysis_allowance(
        self, *, identity: Identity, session_id: str, problem_url: str, cached: bool
    ) -> None:
        """A cache hit costs nothing and awards nothing, so it is never capped.

        The uncached case is capped per (user, session, window). A distinct-
        problem cap alone did **not** cap calls - one learner could re-run
        analysis on edited code indefinitely at the most expensive per-call cost
        in the system, and every one of those runs also wrote a mistake row, a
        progress update, a review update, XP and an event.
        """
        if cached:
            return

        config = self.settings.user_budget
        window_s = self.settings.credits.window_hours * 3600
        window_start = _iso(datetime.now(UTC) - timedelta(seconds=window_s))

        per_user = await self.spend.gw.query_one(
            "SELECT COUNT(*) AS n FROM analysis_results "
            f"WHERE user_id = {encode(identity.user_id)} "
            f"AND created_at >= {encode(window_start)}"
        )
        if per_user and int(per_user["n"]) >= config.analyses_per_problem_per_window:
            raise UsageGuard(_USER_FRIENDLY, retry_after_sec=900)

        per_session = await self.spend.gw.query_one(
            "SELECT COUNT(*) AS n FROM analysis_results "
            f"WHERE session_id = {encode(session_id)} "
            f"AND created_at >= {encode(window_start)}"
        )
        if per_session and int(per_session["n"]) >= config.analyses_per_session_per_window:
            raise UsageGuard(
                "You've analysed this problem a few times already. "
                "Try again after your credits reset.",
                retry_after_sec=900,
            )
        del problem_url

def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")

async def sum_spend_since(spend: SpendRepository, *, since_iso: str) -> dict[str, Any]:
    cost, tokens = await spend.spend_since(since_iso=since_iso)
    return {"cost_usd": cost, "tokens": tokens, "since": since_iso, "at": now_iso()}