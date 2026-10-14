"""Problem sessions: the hub every learning route passes through (§6, §12).

A session is the unit of reveal state. It holds ``unlocked_index``,
``passed_count`` and the generated plan, and it is the thing that decides
whether a learner may see the checklist, a hint, or the next question. Putting
that decision in one place is what stops two routes from disagreeing about it.

The plan shape, the concept card and the analysis are *cached content* keyed on
(approach, language, mode, prompt version), stored per session with a version
number. Serving version N again must be free, so the generator is asked for the
content and the cache decides; this service only decides *which version* applies
and enforces the gates around it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from ..core.errors import ChecklistLocked, NotFound
from ..core.logging import get_logger
from ..policies import reveal_boundary as boundary
from ..repositories.store import (
    AttemptRepository,
    SessionContentRepository,
    SessionRepository,
    now_iso,
)
from ..schemas.models import (
    ChecklistItem,
    CurrentQuestion,
    SessionState,
    SessionStatus,
    SessionSummary,
)
from .microq_service import MicroQuestionService, PlanShape

logger = get_logger(__name__)


@dataclass
class SessionBundle:
    """Everything a request about one session needs, loaded once."""

    session: dict[str, Any]
    content: dict[str, Any] | None
    plan: PlanShape | None

    @property
    def id(self) -> str:
        return str(self.session["id"])

    @property
    def user_id(self) -> str:
        return str(self.session["user_id"])

    @property
    def approach_id(self) -> str:
        return str(self.session.get("selected_approach", ""))

    @property
    def language(self) -> str:
        return str(self.session.get("language", "python"))

    @property
    def mode(self) -> str:
        return str(self.session.get("mode", "beginner"))

    @property
    def unlocked_index(self) -> int:
        return int(self.session.get("unlocked_index", 0) or 0)

    @property
    def passed_count(self) -> int:
        return int(self.session.get("passed_count", 0) or 0)

    @property
    def question_count(self) -> int:
        return int(self.session.get("question_count", 0) or 0)


class SessionService:
    def __init__(
        self,
        *,
        sessions: SessionRepository,
        content: SessionContentRepository,
        attempts: AttemptRepository,
        microq: MicroQuestionService,
    ) -> None:
        self.sessions = sessions
        self.content = content
        self.attempts = attempts
        self.microq = microq

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def open_session(
        self,
        *,
        user_id: str,
        problem: dict[str, Any],
        approach_id: str,
        mode: str,
        language: str,
    ) -> dict[str, Any]:
        """Reuse the learner's active session for this problem if there is one.

        Re-entering the same problem should not reset progress, so the lookup is
        by (user, slug) among active sessions. The partial unique index in the
        schema is what makes the race safe when two tabs open at once.
        """
        slug = str(problem.get("slug", ""))
        existing = await self.sessions.active_for(user_id, slug)
        if existing is not None:
            return existing

        return await self.sessions.create(
            user_id=user_id,
            slug=slug,
            problem=problem,
            approach_id=approach_id,
            mode=mode,
            language=language,
        )

    async def update_progress(
        self, session_id: str, *, status: SessionStatus | None = None, **fields: Any
    ) -> dict[str, Any]:
        patch: dict[str, Any] = {k: v for k, v in fields.items() if v is not None}
        if status is not None:
            patch["status"] = status.value if hasattr(status, "value") else str(status)
        patch["updated_at"] = now_iso()
        updated = await self.sessions.update(session_id, patch)
        return updated or await self.sessions.require(session_id)

    async def close(self, session_id: str, *, user_id: str) -> None:
        """Mark a session complete. Idempotent: a second close is a no-op."""
        row = await self.sessions.get(session_id)
        if row is None or str(row.get("user_id")) != user_id:
            raise NotFound("Session not found")
        if row.get("status") == "completed":
            return
        await self.update_progress(session_id, status=SessionStatus.COMPLETED)

    # ── loading ──────────────────────────────────────────────────────────────

    async def load(self, session_id: str, *, user_id: str) -> SessionBundle:
        """Load a session the caller is allowed to touch.

        Ownership is checked here rather than in each route, because a missing
        check is exactly how one learner's session leaks into another's hands.
        """
        session = await self.sessions.get(session_id)
        if session is None or str(session.get("user_id")) != user_id:
            # Same error for "does not exist" and "not yours": a different
            # message would confirm that someone else's session id is real.
            raise NotFound("Session not found")

        content = await self.content.current(session_id)
        return SessionBundle(
            session=session,
            content=content,
            plan=self._plan_from(content),
        )

    @staticmethod
    def _plan_from(content: dict[str, Any] | None) -> PlanShape | None:
        if not content:
            return None
        shape = MicroQuestionService.shape_from_dict(content.get("plan_json"))
        return shape

    async def store_plan(
        self,
        bundle: SessionBundle,
        *,
        shape: PlanShape,
        prompt_version: str,
        content_version: str,
    ) -> None:
        await self.content.upsert_version(
            session_id=bundle.id,
            approach_id=bundle.approach_id,
            version=int(bundle.content.get("version", 0) or 0) + 1
            if bundle.content
            else 1,
            prompt_version=prompt_version,
            content_version=content_version,
            plan_json=MicroQuestionService.shape_to_dict(shape),
            checklist_json=json.dumps(shape.checklist, ensure_ascii=False),
        )
        # Question count is part of the reveal state, so it moves in the same
        # place the plan does rather than being derived per request.
        await self.update_progress(bundle.id, question_count=len(shape.questions))

    # ── projections ──────────────────────────────────────────────────────────

    async def summary(self, session: dict[str, Any]) -> SessionSummary:
        return SessionSummary(
            id=str(session["id"]),
            slug=str(session.get("slug", "")),
            problem_url=str(session.get("problem_url", "")),
            title=str(session.get("title", "")),
            selected_approach=str(session.get("selected_approach", "brute_force")),
            status=SessionStatus(str(session.get("status", "in_progress"))),
            unlocked_index=int(session.get("unlocked_index", 0) or 0),
            question_count=int(session.get("question_count", 0) or 0),
            passed_count=int(session.get("passed_count", 0) or 0),
            content_version=int(session.get("content_version", 1) or 1),
            mode=str(session.get("mode", "beginner")),
            language=str(session.get("language", "python")),
            updated_at=str(session.get("updated_at", "")),
        )

    async def state(self, bundle: SessionBundle) -> SessionState:
        """What ``GET /sessions/{id}`` returns.

        Everything revealed here is derived from durable state, not from the
        learner having scrolled somewhere. The checklist is gated on the
        checklist policy, and the analysis on the analysis policy, so a learner
        who never answers a question never sees either.
        """
        plan = bundle.plan
        question: CurrentQuestion | None = None
        if plan and plan.questions and bundle.unlocked_index >= 1:
            current = self._question_at(plan, min(bundle.unlocked_index, len(plan.questions)))
            attempts = await self.attempts.attempt_count(bundle.id, int(current.get("index", 1)))
            question = self.microq.project_question(
                current,
                total=len(plan.questions),
                attempts=attempts,
                hints_used=0,
            )

        total = len(plan.questions) if plan else 0
        checklist_unlocked = boundary.checklist_released(
            total_questions=total, passed=bundle.passed_count
        )

        return SessionState(
            session=await self.summary(bundle.session),
            question=question,
            checklist_unlocked=checklist_unlocked,
            analysis_unlocked=boundary.analysis_released(all_passed=checklist_unlocked),
        )

    async def checklist(self, bundle: SessionBundle) -> ChecklistItem:
        """The checklist, once it is allowed.

        Raises rather than returning empty: an empty checklist and a locked one
        look identical to the overlay, and the learner needs to know which it is.
        """
        if bundle.plan is None:
            raise ChecklistLocked("Generate the questions first.")

        if not boundary.checklist_released(
            total_questions=len(bundle.plan.questions), passed=bundle.passed_count
        ):
            raise ChecklistLocked(
                "The checklist opens as you work through the questions."
            )

        items = bundle.plan.checklist
        if not items:
            raw = (bundle.content or {}).get("checklist_json")
            if raw:
                items = [str(i) for i in json.loads(raw)]
        if not items:
            raise ChecklistLocked("The checklist is not ready yet.")

        return ChecklistItem(items=items[:12], approach_id=bundle.approach_id)

    @staticmethod
    def _question_at(plan: PlanShape, index: int) -> dict[str, Any]:
        for question in plan.questions:
            if int(question.get("index", 0)) == index:
                return question
        return plan.questions[0]

    async def attempt_count(self, session_id: str, index: int) -> int:
        return await self.attempts.attempt_count(session_id, index)

    async def problem_view(self, bundle: SessionBundle) -> dict[str, Any]:
        """Rebuild the problem payload the prompts and validators expect.

        The extension sends the problem on session creation; we keep the fields
        we need in the session row rather than trusting the client to resend them
        on every later call.
        """
        return {
            "slug": str(bundle.session.get("slug", "")),
            "url": str(bundle.session.get("problem_url", "")),
            "title": str(bundle.session.get("title", "")),
            "statement_text": str(bundle.session.get("statement_text", "")),
            "constraints_text": str(bundle.session.get("constraints_text", "")),
            "selected_approach": bundle.approach_id,
            "mode": bundle.mode,
            "difficulty": str(bundle.session.get("difficulty", "")),
        }
