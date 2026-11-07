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
    ConceptCard,
    ConceptResponse,
    CreateSessionRequest,
    CurrentQuestion,
    GenerateQuestionsResponse,
    HintResponse,
    PatchSessionRequest,
    ProblemData,
    RevealResponse,
    SessionState,
    SessionSummary,
    SimplifiedConcept,
    SimplifyResponse,
)
from ...services.answer_service import AnswerContext
from ...services.concept_service import MAX_SIMPLIFICATION_LEVELS
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

    # Resume must be possible at the limit: the cap applies to *new* problems,
    # not to reopening one the learner already has in flight.
    existing = await container.sessions.active_for(identity.user_id, body.slug)
    if existing is None:
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

    switched = body.approach_id is not None and body.approach_id != bundle.approach_id
    if switched:
        if body.status == "completed":
            await container.learning.close(
                session_id, user_id=caller.identity.user_id
            )
        updated = await container.learning.switch_approach(
            bundle, approach_id=str(body.approach_id)
        )
        if body.status is not None and body.status != "completed":
            updated = await container.learning.update_progress(
                session_id, status=body.status
            )
        return await container.learning.summary(updated)

    if body.status == "completed":
        await container.learning.close(session_id, user_id=caller.identity.user_id)
        refreshed = await container.sessions.require(session_id)
        return await container.learning.summary(refreshed)
    if body.status is not None:
        updated = await container.learning.update_progress(
            session_id, status=body.status
        )
        return await container.learning.summary(updated)
    return await container.learning.summary(bundle.session)


# ── concept ────────────────────────────────────────────────────────────────


@router.post("/sessions/{session_id}/concept", response_model=ConceptResponse)
async def read_concept(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
) -> ConceptResponse:
    """Return the concept card. This is part of the plan, not a credit event.

    Credits meter micro-questions and analysis (§10.1). Charging for the concept
    made a required step cost twice, and a client retry with a fresh
    Idempotency-Key could not be recognised as the same request. The card is
    cached on the session so revisiting it is a database read.
    """
    enforce_rate_limit(container, caller, route_class="heavy")
    identity = caller.identity
    identity.require_verified(enforced=container.settings.auth.require_verified_email)
    await container.budget.require_not_degraded()

    bundle = await container.learning.load(session_id, user_id=identity.user_id)
    cached = (bundle.content or {}).get("concept_json")
    if cached:
        card = ConceptCard.model_validate_json(cached)
    else:
        problem = await container.learning.problem_view(bundle)
        card = await container.concept.build_card(
            problem=problem,
            approach_id=bundle.approach_id,
            approach_name=bundle.approach_id,
            language=bundle.language,
            mode=bundle.mode,
            client_ip=caller.client_ip,
        )
        carried = {
            key: bundle.content.get(key)
            for key in ("plan_json", "checklist_json", "simplify_json", "simplify_level")
            if bundle.content and bundle.content.get(key) is not None
        }
        await container.session_content.upsert_version(
            session_id=session_id,
            approach_id=bundle.approach_id,
            version=int((bundle.content or {}).get("version", 0) or 0) + 1
            if bundle.content
            else 1,
            prompt_version="v1",
            content_version="v1",
            concept_json=card.model_dump_json(by_alias=True),
            **carried,
        )
    return ConceptResponse(session_id=session_id, card=card)


@router.post(
    "/sessions/{session_id}/concept/simplify", response_model=SimplifyResponse
)
async def simplify_concept(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
) -> SimplifyResponse:
    enforce_rate_limit(container, caller, route_class="heavy")
    identity = caller.identity
    identity.require_verified(enforced=container.settings.auth.require_verified_email)
    await container.budget.require_not_degraded()

    bundle = await container.learning.load(session_id, user_id=identity.user_id)
    content = bundle.content or {}
    current = int(content.get("simplify_level", 0) or 0)

    # The two-level ceiling is enforced here, not only in the prompt. A third
    # click returns the cached level-2 wording instead of spending another call.
    if current >= MAX_SIMPLIFICATION_LEVELS and content.get("simplify_json"):
        return SimplifyResponse(
            session_id=session_id,
            simplified=SimplifiedConcept.model_validate_json(content["simplify_json"]),
        )

    problem = await container.learning.problem_view(bundle)
    card_raw = content.get("concept_json")
    if card_raw:
        card = ConceptCard.model_validate_json(card_raw)
    else:
        card = await container.concept.build_card(
            problem=problem,
            approach_id=bundle.approach_id,
            approach_name=bundle.approach_id,
            language=bundle.language,
            mode=bundle.mode,
            client_ip=caller.client_ip,
        )

    level = min(current + 1, MAX_SIMPLIFICATION_LEVELS)
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
        version=int(content.get("version", 1) or 1),
        prompt_version="v1",
        content_version="v1",
        simplify_level=level,
        simplify_json=simplified.model_dump_json(by_alias=True),
        concept_json=content.get("concept_json"),
    )
    return SimplifyResponse(session_id=session_id, simplified=simplified)


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
        # not a new request for work. Return the question the learner is on,
        # not question 1, so reload does not rewind progress.
        state = await container.learning.state(bundle)
        if state.question is None:
            raise QuestionLocked("Generate the questions first.")
        return GenerateQuestionsResponse(
            session_id=session_id,
            question=state.question,
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

    # Read the durable count before the AI call; only advance after the detail
    # exists, so a failed generation does not consume a hint the learner never
    # saw.
    used = await container.learning.hints_used(session_id, index)
    detail = await container.microq.ensure_detail(
        problem=await container.learning.problem_view(bundle),
        approach_id=bundle.approach_id,
        question=question,
        prior_prompts=[str(q.get("prompt", "")) for q in plan.questions[: index - 1]],
        language=bundle.language,
        mode=bundle.mode,
        client_ip=caller.client_ip,
    )
    consumed = await container.hints.advance(session_id, index, floor=used)
    return container.microq.next_hint(
        detail, hints_used=max(0, consumed - 1), index=index
    )


@router.post(
    "/sessions/{session_id}/micro-questions/{index}/reveal",
    response_model=RevealResponse,
)
async def reveal_step(
    container: ContainerDep,
    caller: CallerDep,
    session_id: Annotated[str, Path(max_length=64)],
    index: Annotated[int, Path(ge=1, le=50)],
) -> RevealResponse:
    """Release the current step on explicit request (§10.8).

    This is not an answer and does not consume an attempt or a credit. It is the
    backend's half of the "I'm stuck" button; the client stops offering it once
    the cap has already released the same text through feedback.
    """
    enforce_rate_limit(container, caller, route_class="light")
    bundle = await container.learning.load(session_id, user_id=caller.identity.user_id)
    plan = bundle.plan
    if plan is None or bundle.current_index != index:
        raise QuestionLocked("That step is not unlocked yet.")

    question = container.answers.question_at(plan, index)
    if question is None:
        raise QuestionLocked("That step is not unlocked yet.")

    detail = await container.microq.ensure_detail(
        problem=await container.learning.problem_view(bundle),
        approach_id=bundle.approach_id,
        question=question,
        prior_prompts=[str(q.get("prompt", "")) for q in plan.questions[: index - 1]],
        language=bundle.language,
        mode=bundle.mode,
        client_ip=caller.client_ip,
    )
    released = boundary.step_explanation_released(
        attempts=0, attempt_cap=container.settings.credits.attempt_cap,
        explicit_request=True,
    )
    if not released or not detail.step_explanation:
        raise BadRequest("That step explanation is not available yet.")
    return RevealResponse(
        session_id=session_id,
        index=index,
        step_explanation=detail.step_explanation,
        revealed=True,
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
        unlocked_index=bundle.current_index,
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
