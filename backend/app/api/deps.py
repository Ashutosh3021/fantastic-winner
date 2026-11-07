"""Composition root.

Everything is constructed once here and shared. Two reasons this is a single
explicit object rather than FastAPI's usual per-request dependency graph:

* the PyroCore HTTP client and its connection pool must be created and closed
  exactly once, not per request;
* the projector is a background task that needs the same gateway the request
  path uses, so sharing is not an optimisation but a correctness requirement.

Nothing in here knows about HTTP. Routers depend on :class:`Container`, and
services depend on each other, never on FastAPI.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from types import SimpleNamespace

from ..ai.gateway import AIGateway
from ..cache.store import ContentCache
from ..core.config import Settings, get_settings
from ..core.logging import get_logger
from ..migrations.runner import run_migrations
from ..ratelimit.limiter import InProcessRateLimiter
from ..repositories.gateway import PyronitesGateway
from ..repositories.store import (
    AttemptRepository,
    AuthTokenRepository,
    ContentCacheRepository,
    EventRepository,
    HintStateRepository,
    IpBudgetRepository,
    LoginCodeRepository,
    MistakeRepository,
    PreferencesRepository,
    SavedCardRepository,
    SessionContentRepository,
    SessionRepository,
    SpendRepository,
    UserRepository,
)
from ..services.analysis_service import AnalysisService
from ..services.answer_service import AnswerService
from ..services.approach_service import ApproachService
from ..services.auth_service import AuthService
from ..services.budget_service import BudgetService
from ..services.concept_service import ConceptService
from ..services.credit_service import CreditService
from ..services.generator import ContentGenerator
from ..services.microq_service import MicroQuestionService
from ..services.progress_service import ProgressService
from ..services.projector import Projector
from ..services.session_service import SessionService

logger = get_logger(__name__)

#: Every route the extension calls lives under this prefix. It lives here, not in
#: ``app.main``, because the routers need it and importing it from main would be
#: circular: main imports the routers.
API_PREFIX = "/v1"

#: Process-wide container holder. A module-level ``SimpleNamespace`` rather than
#: a global, so tests can swap it and put the old one back.
_state = SimpleNamespace(container=None)


@dataclass
class Container:
    settings: Settings
    gateway: PyronitesGateway
    ai: AIGateway
    cache: ContentCache
    generator: ContentGenerator
    credits: CreditService
    budget: BudgetService
    rate_limiter: InProcessRateLimiter
    projector: Projector

    auth: AuthService
    users: UserRepository
    preferences: PreferencesRepository
    sessions: SessionRepository
    session_content: SessionContentRepository
    attempts: AttemptRepository
    hints: HintStateRepository
    mistakes: MistakeRepository
    saved_cards: SavedCardRepository
    events: EventRepository
    login_codes: LoginCodeRepository
    tokens: AuthTokenRepository
    spend: SpendRepository
    ip_budget: IpBudgetRepository
    cache_rows: ContentCacheRepository

    approaches: ApproachService
    concept: ConceptService
    microq: MicroQuestionService
    answers: AnswerService
    analysis: AnalysisService
    learning: SessionService
    progress: ProgressService

    _projector_task: asyncio.Task[None] | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Apply migrations, then start the projector.

        Migrations run at boot because the schema is the contract: a deploy that
        starts serving against an older schema fails in the first request that
        touches a new column, which is the worst possible moment to find out.
        """
        if self.settings.pyronites.auto_migrate:
            applied = await run_migrations(self.gateway)
            if applied:
                logger.info("migrations applied: %s", ", ".join(applied))
            else:
                logger.info("schema already current")

        # The projector is best-effort: if the loop cannot start, requests still
        # work and the queue drains on the next boot.
        try:
            self._projector_task = asyncio.create_task(
                self.projector.drain_forever(), name="projector"
            )
        except RuntimeError:
            logger.warning("no running loop; projector not started")

    async def stop(self) -> None:
        if self._projector_task is not None:
            self._projector_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._projector_task
            self._projector_task = None
        await self.ai.aclose()
        await self.gateway.aclose()


def build_container(settings: Settings | None = None) -> Container:
    settings = settings or get_settings()
    gateway = PyronitesGateway(settings)
    ai = AIGateway(settings)

    cache_rows = ContentCacheRepository(gateway)
    cache = ContentCache(gateway, settings.cache, repository=cache_rows)
    credits = CreditService(gateway, config=settings.credits)
    spend = SpendRepository(gateway)
    ip_budget = IpBudgetRepository(gateway)
    budget = BudgetService(settings, spend, ip_budget)
    rate_limiter = InProcessRateLimiter()
    generator = ContentGenerator(ai, cache, budget)
    projector = Projector(gateway)

    # One instance of each repository. They are thin wrappers over the shared
    # gateway, so duplicating them would only invite two objects disagreeing
    # about the same table.
    users = UserRepository(gateway)
    preferences = PreferencesRepository(gateway)
    sessions = SessionRepository(gateway)
    session_content = SessionContentRepository(gateway)
    attempts = AttemptRepository(gateway)
    hints = HintStateRepository(gateway)
    mistakes = MistakeRepository(gateway)
    saved_cards = SavedCardRepository(gateway)
    events = EventRepository(gateway)
    login_codes = LoginCodeRepository(gateway)
    tokens = AuthTokenRepository(gateway)

    microq = MicroQuestionService(generator)
    answers = AnswerService(
        gateway, microq=microq, attempts=attempts, config=settings.credits,
        generator=generator,
    )

    return Container(
        settings=settings,
        gateway=gateway,
        ai=ai,
        cache=cache,
        generator=generator,
        credits=credits,
        budget=budget,
        rate_limiter=rate_limiter,
        projector=projector,
        auth=AuthService(
            gateway,
            users=users,
            codes=login_codes,
            tokens=tokens,
            config=settings.auth,
        ),
        users=users,
        preferences=preferences,
        sessions=sessions,
        session_content=session_content,
        attempts=attempts,
        hints=hints,
        mistakes=mistakes,
        saved_cards=saved_cards,
        events=events,
        login_codes=login_codes,
        tokens=tokens,
        spend=spend,
        ip_budget=ip_budget,
        cache_rows=cache_rows,
        approaches=ApproachService(generator),
        concept=ConceptService(generator),
        microq=microq,
        answers=answers,
        analysis=AnalysisService(generator),
        learning=SessionService(
            sessions=sessions,
            content=session_content,
            attempts=attempts,
            hints=hints,
            microq=microq,
        ),
        progress=ProgressService(
            gateway,
            users=users,
            preferences=preferences,
            mistakes=mistakes,
            saved_cards=saved_cards,
            credit_config=settings.credits,
        ),
    )


def get_container() -> Container:
    """The process-wide container, built by the lifespan and closed on shutdown."""
    container: Container | None = getattr(_state, "container", None)
    if container is None:
        raise RuntimeError("container not initialised")
    return container


def set_container(container: Container | None) -> None:
    _state.container = container


__all__ = ["Container", "build_container", "get_container", "set_container"]
