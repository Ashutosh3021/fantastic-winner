"""Sessions and the learning flow: approaches, concept, questions, hints, answers.

This is where credits are spent and where the reveal boundary is enforced, so
the two rules that shape the file are:

* **Every state change that costs money is idempotency-keyed.** A learner who
  clicks "Start" on a slow connection must not be charged twice, and a retry
  must return the same artifact rather than a second plan.
* **A failure never costs a credit.** Claims are settled at the true cost and
  rolled back on error, so the refund path is in the same ``try`` as the spend
  rather than somewhere a developer might forget it.

The rubric, ``common_wrong`` and the step explanation never appear in a response
model. ``CurrentQuestion`` has no field for them, so "the client cannot read
ahead" is enforced by the type rather than by remembering to strip keys.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Path

from ...core.errors import (
    AppError,
    BadRequest,
    CreditsExhausted,
    DegradedMode,
    GenerationInProgress,
    InsufficientCredits,
    QuestionLocked,
    UsageGuard,
)
from ...core.logging import get_logger
from ...policies import reveal_boundary as boundary
from ...schemas.models import (
    AnalysisRequest,
    AnswerResponse,
    AnswerSubmission,
    ApproachesRequest,
    ApproachesResponse,
    ChecklistResponse,
    CreateSessionRequest,
    CurrentQuestion,
    GenerateQuestionsResponse,
    HintResponse,
    PatchSessionRequest,
    ProblemData,
    SessionState,
    SessionSummary,
)
from ...services.answer_service import AnswerContext
from ..dependencies import (
    CallerDep,
    ContainerDep,
    enforce_rate_limit,
    require_idempotency_key,
)

logger = get_logger(__name__)

router = APIRouter(tags=["learning"])


def _problem_dict(problem: ProblemData) -> dict[str, Any]:
    return problem.model_dump(by_alias=True)


@router.post("/problems/approaches", response_model=ApproachesResponse)
async def list_approaches(
    container: ContainerDep, caller: CallerDep, body: ApproachesRequest
) -> ApproachesResponse:
    enforce_rate_limit(container, caller, route_class="light")
    caller.identity.require_verified(
        enforced=container.settings.auth.require_verified_email
    )
    await container.budget.require_not_degraded()
    return await container.approaches.list_approaches(
        _problem_dict(body.problem), client_ip=caller.client_ip
    )


@router.post("/sessions", response_model=SessionSummary)
async def create_session(
    container: ContainerDep, caller: CallerDep, body: CreateSessionRequest
) -> SessionSummary:
    enforce_rate_limit(container, caller, route_class="light")
    identity = caller.identity
    identity.require_verified(
        enforced=container.settings.auth.require_verified_email
    )

    active = await container.sessions.count_in_progress(identity.user_id)
    if active >= container.settings.credits.max_active_sessions:
        from ...core.errors import ActiveSessionLimit

        raise ActiveSessionLimit(
            f"You have {active} problems open. Finish one before starting another."
        )

    problem = _problem_dict(body.problem)
    # Mode and language come from the learner's saved preferences, not from the
    # request, so a stale client cannot quietly change the difficulty a learner
    # is being taught at.
    prefs = await container.progress.preferences_for(identity.user_id)
    session = await container.learning.open_session(
        user_id=identity.user_id,
        problem=problem,
        approach_id=body.approach_id,
        mode=str(prefs.difficulty_mode),
        language=str(prefs.language),
    )
    # Keep the text the prompts need on the row; later routes must not have to
    # trust the client to resend the problem.
    await container.sessions.update(
        str(session["id"]),
        {
            "statement_text": problem.get("statement_text", ""),
            "constraints_text": problem.get("constraints_text", ""),
            "difficulty": str(problem.get("difficulty", "")),
        },
    )
    refreshed = await container.sessions.require(str(session["id"]))
    return await container.learning.summary(refreshed)


@router.get("/sessions", response_model=list[SessionSummary])
async def list_sessions(
    container: ContainerDep, caller: CallerDep
) -> list[SessionSummary]:
    enforce_rate_limit(container, caller, route_class="light")
    rows = await container.sessions.list_for(caller.identity.user_id)
    return [await container.learning.summary(row) for row in rows]


@router.get("/sessions/{session_id}", response_model=SessionState)
async def read_session(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
) -> SessionState:
    enforce_rate_limit(container, caller, route_class="light")
    bundle = await container.learning.load(session_id, user_id=caller.identity.user_id)
    return await container.learning.state(bundle)


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
async def patch_session(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
    body: PatchSessionRequest,
) -> SessionSummary:
    enforce_rate_limit(container, caller, route_class="light")
    bundle = await container.learning.load(session_id, user_id=caller.identity.user_id)

    if body.status == "completed":
        await container.learning.close(session_id, user_id=caller.identity.user_id)
    fields: dict[str, Any] = {}
    if body.approach_id is not None:
        fields["selected_approach"] = body.approach_id
    if body.status is not None:
        fields["status"] = body.status

    updated = await container.learning.update_progress(session_id, **fields)
    return await container.learning.summary(updated or bundle.session)


# ── concept ────────────────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/concept")
async def read_concept(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
) -> dict[str, Any]:
    enforce_rate_limit(container, caller, route_class="heavy")
    identity = caller.identity
    identity.require_verified(enforced=container.settings.auth.require_verified_email)
    await container.budget.require_not_degraded()

    bundle = await container.learning.load(session_id, user_id=identity.user_id)
    problem = await container.learning.problem_view(bundle)

    key = require_idempotency_key(caller)
    await _spend_credit(container, caller, key, session_id, reserve_n=1)

    card = await container.concept.build_card(
        problem=problem,
        approach_id=bundle.approach_id,
        approach_name=bundle.approach_id,
        language=bundle.language,
        mode=bundle.mode,
        client_ip=caller.client_ip,
    )
    return {"session_id": session_id, "card": card.model_dump(by_alias=True)}


@router.post("/sessions/{session_id}/concept/simplify")
async def simplify_concept(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
) -> dict[str, Any]:
    enforce_rate_limit(container, caller, route_class="heavy")
    identity = caller.identity
    identity.require_verified(enforced=container.settings.auth.require_verified_email)
    await container.budget.require_not_degraded()

    bundle = await container.learning.load(session_id, user_id=identity.user_id)
    problem = await container.learning.problem_view(bundle)

    card = await container.concept.build_card(
        problem=problem,
        approach_id=bundle.approach_id,
        approach_name=bundle.approach_id,
        language=bundle.language,
        mode=bundle.mode,
        client_ip=caller.client_ip,
    )

    current = int(bundle.content.get("simplify_level", 0) or 0) if bundle.content else 0
    level = min(current + 1, 2)
    simplified = await container.concept.simplify(
        problem=problem,
        approach_id=bundle.approach_id,
        card=card,
        level=level,
        language=bundle.language,
        mode=bundle.mode,
        client_ip=caller.client_ip,
    )
    await container.session_content.upsert_version(
        session_id=session_id,
        approach_id=bundle.approach_id,
        version=int((bundle.content or {}).get("version", 1) or 1),
        prompt_version="v1",
        content_version="v1",
        simplify_level=level,
    )
    return {
        "session_id": session_id,
        "simplified": simplified.model_dump(by_alias=True),
    }


# ── micro-questions ────────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/micro-questions", response_model=GenerateQuestionsResponse)
async def generate_questions(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
) -> GenerateQuestionsResponse:
    enforce_rate_limit(container, caller, route_class="heavy")
    identity = caller.identity
    identity.require_verified(enforced=container.settings.auth.require_verified_email)
    await container.budget.require_not_degraded()

    bundle = await container.learning.load(session_id, user_id=identity.user_id)
    problem = await container.learning.problem_view(bundle)

    plan = bundle.plan
    if plan is not None and plan.questions:
        # Serving an existing plan is free and must not re-charge: a reload is
        # not a new request for work.
        first = plan.questions[0]
        return GenerateQuestionsResponse(
            session_id=session_id,
            question=container.microq.project_question(
                first, total=len(plan.questions)
            ),
            credits_charged=0,
        )

    key = require_idempotency_key(caller)
    reserve = max(1, container.settings.credits.min_plan_questions)
    await _spend_credit(container, caller, key, session_id, reserve_n=reserve)

    try:
        shape = await container.microq.generate_shape(
            problem=problem,
            approach_id=bundle.approach_id,
            language=bundle.language,
            mode=bundle.mode,
            client_ip=caller.client_ip,
        )
        await container.learning.store_plan(
            bundle,
            shape=shape,
            prompt_version="v1",
            content_version="v1",
        )
    except AppError:
        await container.credits.rollback(
            idempotency_key=key,
            user_id=identity.user_id,
            session_id=session_id,
            reason="plan_failed",
        )
        raise

    # Credits meter questions generated, not questions reserved: a four-question
    # plan returns the fifth credit.
    await container.credits.settle(
        idempotency_key=key,
        user_id=identity.user_id,
        session_id=session_id,
        actual_n=len(shape.questions),
    )

    first = shape.questions[0]
    return GenerateQuestionsResponse(
        session_id=session_id,
        question=container.microq.project_question(first, total=len(shape.questions)),
        credits_charged=len(shape.questions),
    )


@router.get("/sessions/{session_id}/micro-questions/current", response_model=CurrentQuestion)
async def current_question(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
) -> CurrentQuestion:
    enforce_rate_limit(container, caller, route_class="light")
    bundle = await container.learning.load(session_id, user_id=caller.identity.user_id)
    state = await container.learning.state(bundle)
    if state.question is None:
        raise QuestionLocked("Generate the questions first.")
    return state.question


@router.post("/sessions/{session_id}/micro-questions/{index}/hint", response_model=HintResponse)
async def request_hint(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
    index: Annotated[int, Path(ge=1, le=50)],
) -> HintResponse:
    """Hints are free.

    They come from the detail that was generated when the question was judged, so
    asking costs no AI call and no credit. Charging here would teach a learner
    that asking for help is expensive, which is the opposite of what this product
    is for.
    """
    enforce_rate_limit(container, caller, route_class="light")
    bundle = await container.learning.load(session_id, user_id=caller.identity.user_id)
    plan = bundle.plan
    if plan is None or index > len(plan.questions):
        raise BadRequest("That question is not part of this plan.")

    question = container.answers.question_at(plan, index)
    if question is None:
        raise BadRequest("That question is not part of this plan.")
    detail = await container.microq.ensure_detail(
        problem=await container.learning.problem_view(bundle),
        approach_id=bundle.approach_id,
        question=question,
        prior_prompts=[str(q.get("prompt", "")) for q in plan.questions[: index - 1]],
        language=bundle.language,
        mode=bundle.mode,
        client_ip=caller.client_ip,
    )

    hints_used = await _hints_used(container, session_id, index)

    return container.microq.next_hint(detail, hints_used=hints_used, index=index)


async def _hints_used(container: ContainerDep, session_id: str, index: int) -> int:
    rows = await container.attempts.for_session(session_id)
    return sum(
        int(row.get("hints_used", 0) or 0)
        for row in rows
        if int(row.get("question_index", 0)) == index
    )


@router.post("/sessions/{session_id}/micro-questions/{index}/answer", response_model=AnswerResponse)
async def submit_answer(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
    index: Annotated[int, Path(ge=1, le=50)],
    submission: AnswerSubmission,
) -> AnswerResponse:
    """Answering is free; only generating questions costs credits (§10.1)."""
    enforce_rate_limit(container, caller, route_class="check")
    bundle = await container.learning.load(session_id, user_id=caller.identity.user_id)
    plan = bundle.plan
    if plan is None:
        raise QuestionLocked("Generate the questions first.")

    ctx = AnswerContext(
        session_id=session_id,
        user_id=caller.identity.user_id,
        unlocked_index=bundle.unlocked_index,
        passed_count=bundle.passed_count,
        plan=plan,
        problem=await container.learning.problem_view(bundle),
        approach_id=bundle.approach_id,
        language=bundle.language,
        mode=bundle.mode,
    )
    response, detail = await container.answers.submit(
        ctx=ctx,
        index=index,
        submission=submission.model_dump(by_alias=True),
        client_ip=caller.client_ip,
    )


    cap = container.settings.credits.attempt_cap
    if response.attempt_no > cap and response.next_question is None:
        # Past the cap the step explanation is released (§10.8): the learner has
        # tried, and continuing to fail teaches nothing.
        revealed = boundary.step_explanation_released(
            attempts=response.attempt_no, attempt_cap=cap
        )
        if revealed and detail.step_explanation:
            response.feedback = f"{response.feedback} {detail.step_explanation}"

    return response


@router.get("/sessions/{session_id}/checklist", response_model=ChecklistResponse)
async def read_checklist(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
) -> ChecklistResponse:
    enforce_rate_limit(container, caller, route_class="light")
    bundle = await container.learning.load(session_id, user_id=caller.identity.user_id)
    item = await container.learning.checklist(bundle)
    return ChecklistResponse(session_id=session_id, checklist=item)


# ── analysis ───────────────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/analysis")
async def analyse_code(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
    body: AnalysisRequest,
) -> dict[str, Any]:
    enforce_rate_limit(container, caller, route_class="analysis")
    identity = caller.identity
    identity.require_verified(enforced=container.settings.auth.require_verified_email)
    await container.budget.require_not_degraded()

    bundle = await container.learning.load(session_id, user_id=identity.user_id)
    await container.budget.check_analysis_allowance(
        identity=identity,
        session_id=session_id,
        problem_url=str(bundle.session.get("problem_url", "")),
        cached=False,
    )

    key = require_idempotency_key(caller)
    await _spend_credit(container, caller, key, session_id, reserve_n=0)

    language = body.language or bundle.language
    try:
        result = await container.analysis.analyse(
            code=body.code,
            editor_language=body.editor_language,
            language=language,
            problem=await container.learning.problem_view(bundle),
            session_id=session_id,
            client_ip=caller.client_ip,
        )
    except DegradedMode:
        await container.credits.rollback(
            idempotency_key=key,
            user_id=identity.user_id,
            session_id=session_id,
            reason="no_code",
        )
        raise
    except AppError:
        await container.credits.rollback(
            idempotency_key=key,
            user_id=identity.user_id,
            session_id=session_id,
            reason="analysis_failed",
        )
        raise

    await container.credits.settle(
        idempotency_key=key,
        user_id=identity.user_id,
        session_id=session_id,
        actual_n=0,
    )
    return result.model_dump(by_alias=True)


# ── credit helper ──────────────────────────────────────────────────────────


async def _spend_credit(
    container: ContainerDep,
    caller: CallerDep,
    key: str,
    session_id: str,
    *,
    reserve_n: int,
) -> None:
    """Claim the credits for one request, or explain why not.

    A retry with the same key does not re-charge: the claim row already exists and
    the cached artifact is returned instead.
    """
    claim = await container.credits.claim(
        idempotency_key=key,
        user_id=caller.identity.user_id,
        reserve_n=reserve_n,
        session_id=session_id,
    )
    if claim.acquired:
        return
    if claim.retryable:
        raise GenerationInProgress("That request is still running. Try again shortly.")
    if claim.reserve_error:
        raise UsageGuard("Could not reserve credits. Nothing was charged.")
    if claim.shortfall:
        raise InsufficientCredits(
            "Not enough credits for this.",
            reset_at=claim.reset_at,
            shortfall=claim.shortfall,
        )
    raise CreditsExhausted("You are out of credits for now.", reset_at=claim.reset_at)


__all__ = ["Body", "router"]
