"""The micro-question engine (§10).

Two stages, and the split is the whole point. v1 generated five questions with
five rubrics, fifteen hints and five step explanations in one call. That did not
fit the response budget: five-question plans truncated, a truncated body failed
schema validation, the repair call truncated identically (truncation is a
function of the budget, not of the prompt), and the leak regeneration truncated
too. The learner who clicked "Start" watched three doomed generations and then
got an error card and a refund.

So: a **shape call** produces the questions and the checklist; **per-question
detail** is filled lazily the first time a question is judged, and in practice is
already cached from other learners.

Nothing here returns a rubric, ``common_wrong``, or ``step_explanation`` to the
client. :func:`project_question` is the only path from a plan to a
``CurrentQuestion``, and that model has no field for the hidden parts - so
"the client cannot read ahead" is a property of the type, not a convention.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, cast

from ..ai import knowledge
from ..ai.prompts import microq_detail as detail_prompt
from ..ai.prompts import microq_shape as shape_prompt
from ..core.errors import AiInvalidOutput, AppError
from ..policies import reveal_boundary as boundary
from ..schemas.models import (
    AnswerType,
    CurrentQuestion,
    HintResponse,
)
from ..validators.leak_detector import contains_code
from ..validators.quality import check_answerable, check_hint_not_a_solution
from .generator import ContentGenerator, GenerateRequest, build_system


@dataclass
class PlanShape:
    questions: list[dict[str, Any]] = field(default_factory=list)
    checklist: list[str] = field(default_factory=list)

@dataclass
class QuestionDetail:
    key_points: list[str] = field(default_factory=list)
    common_wrong: list[dict[str, Any]] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    step_explanation: str = ""
    # : Window states for ``predict_state``, computed at generation time so the
    # : check stays deterministic instead of paying for a judge call.
    expected_state: list[str] = field(default_factory=list)
    # : True when the detail call failed and these came from the knowledge base.
    degraded: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "rubric": {"key_points": self.key_points, "common_wrong": self.common_wrong},
            "hints": self.hints,
            "step_explanation": self.step_explanation,
            "expected_state": self.expected_state,
            "degraded": self.degraded,
        }

SHAPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "learning_goal": {"type": "string"},
                    "answer_type": {"type": "string"},
                    "choices": {"type": ["array", "null"], "items": {"type": "string"}},
                },
                "required": ["prompt", "learning_goal", "answer_type"],
            },
        },
        "checklist": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["questions", "checklist"],
}

DETAIL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "key_points": {"type": "array", "items": {"type": "string"}},
        "common_wrong": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "mistake_type": {"type": "string"},
                    "nudge": {"type": "string"},
                },
                "required": ["pattern", "mistake_type", "nudge"],
            },
        },
        "hints": {"type": "array", "items": {"type": "string"}},
        "step_explanation": {"type": "string"},
        "expected_state": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["key_points", "common_wrong", "hints", "step_explanation"],
}

# : The five structural slots -9 requires a checklist to cover, in the order a
# : learner works through them. Used only when generation *and* the knowledge base
# : both come up empty.
_FALLBACK_CHECKLIST = (
    "Pick the data structure that answers the question in one step.",
    "Name the variables you will keep as you go.",
    "Say what you do for each element.",
    "Say exactly when you stop.",
    "Say what you return at the end.",
)

class MicroQuestionService:
    task_id = "microq_shape.v1"
    detail_task_id = "microq_detail.v1"

    def __init__(
        self,
        generator: ContentGenerator,
        *,
        min_questions: int = 3,
        max_questions: int = 5,
    ) -> None:
        self.generator = generator
        self.min_questions = min_questions
        self.max_questions = max_questions

    # -- stage 1: the plan shape ---

    async def generate_shape(
        self,
        *,
        problem: dict[str, Any],
        approach_id: str,
        language: str,
        mode: str,
        client_ip: str | None = None,
    ) -> PlanShape:
        grounding = knowledge.grounding_for(approach_id)
        user = shape_prompt(
            problem,
            approach_id=approach_id,
            grounding=grounding,
            min_n=self.min_questions,
            max_n=self.max_questions,
            mode=mode,
        )

        request = GenerateRequest(
            task_id=self.task_id,
            slug=str(problem.get("slug", "")),
            statement_text=str(problem.get("statement_text", "")),
            constraints_text=str(problem.get("constraints_text", "")),
            approach_id=approach_id,
            language=language,
            mode=mode,
            schema=SHAPE_SCHEMA,
            adapter=self._validate_shape,
            tier="balanced",
            temperature=0.4,
            max_tokens=1_000,
            deadline_s=20.0,
            pool="generation",
        )
        outcome = await self.generator.generate(
            request,
            system=build_system(language=language, mode=mode),
            user=user,
            client_ip=client_ip,
        )
        shape: PlanShape = outcome.payload
        self._top_up_checklist(shape, approach_id=approach_id)
        return shape

    def _top_up_checklist(self, shape: PlanShape, *, approach_id: str) -> None:
        """Degrade the checklist from the knowledge base rather than fail.

        The checklist is the product's payoff - a plan without one is not a plan -
        so it must never be empty. This lives in the service rather than in
        ``_validate_shape`` because the adapter is called by the gateway with only
        the payload, and this needs ``approach_id``.
        """
        if len(shape.checklist) >= self.min_questions:
            return
        entry = knowledge.get(approach_id) or {}
        steps = [str(step) for step in (entry.get("typical_micro_steps") or [])][:12]
        if steps:
            shape.checklist = steps
        if not shape.checklist:
            # Last resort: the five structural slots -9 requires every checklist
            # to answer. Better an honest skeleton than an empty plan.
            shape.checklist = list(_FALLBACK_CHECKLIST)[:12]

    def _validate_shape(self, payload: Any) -> PlanShape:
        if not isinstance(payload, dict):
            raise ValueError("plan shape must be an object")
        raw_questions = payload.get("questions") or []
        if not isinstance(raw_questions, list) or not raw_questions:
            raise ValueError("plan shape needs at least one question")

        questions: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_questions[: self.max_questions], start=1):
            if not isinstance(raw, dict):
                continue
            answer_type = str(raw.get("answer_type", AnswerType.SHORT_TEXT))
            try:
                answer_type = AnswerType(answer_type)
            except ValueError:
                answer_type = AnswerType.SHORT_TEXT

            choices = raw.get("choices")
            choices = [str(c) for c in choices] if isinstance(choices, list) else None

            answerable = check_answerable(
                str(raw.get("prompt", "")),
                answer_type=str(answer_type),
                choices=choices,
            )
            if not answerable.ok and answer_type in {
                AnswerType.SINGLE_CHOICE,
                AnswerType.MULTI_CHOICE,
                AnswerType.ORDER_STEPS,
            }:
                # A choice question with no choices cannot be checked at all, so
                # it degrades to short text rather than becoming unanswerable.
                answer_type = AnswerType.SHORT_TEXT
                choices = None

            questions.append(
                {
                    "index": index,
                    "prompt": str(raw.get("prompt", "")).strip()[:1_000],
                    "learning_goal": str(raw.get("learning_goal", "")).strip()[:1_000],
                    "answer_type": answer_type.value,
                    "choices": choices,
                }
            )

        if not questions:
            raise ValueError("no usable questions")

        checklist = [
            str(item).strip()[:240]
            for item in (payload.get("checklist") or [])
            if str(item).strip()
        ][:12]

        for item in checklist:
            if contains_code(item):
                raise AiInvalidOutput("checklist contains code")

        return PlanShape(questions=questions, checklist=checklist)

    # -- stage 2: lazy per-question detail ---

    async def ensure_detail(
        self,
        *,
        problem: dict[str, Any],
        approach_id: str,
        question: dict[str, Any],
        prior_prompts: list[str],
        language: str,
        mode: str,
        client_ip: str | None = None,
    ) -> QuestionDetail:
        """Rubric, hints and step explanation for one question.

        Degrades rather than errors. A learner never sees "couldn't load
        question details"; they see a question with slightly less hand-holding,
        and a hidden hint button (§10.3).
        """
        grounding = knowledge.grounding_for(approach_id)
        user = detail_prompt(
            problem,
            approach_id=approach_id,
            grounding=grounding,
            question=question,
            prior_questions=prior_prompts,
        )

        request = GenerateRequest(
            task_id=self.detail_task_id,
            slug=str(problem.get("slug", "")),
            statement_text=str(problem.get("statement_text", "")),
            constraints_text=str(problem.get("constraints_text", "")),
            approach_id=approach_id,
            language=language,
            mode=mode,
            schema=DETAIL_SCHEMA,
            adapter=self._validate_detail,
            tier="fast",
            temperature=0.3,
            max_tokens=600,
            deadline_s=12.0,
            variant=f"q{question.get('index', 1)}",
        )

        try:
            outcome = await self.generator.generate(
                request,
                system=build_system(language=language, mode=mode),
                user=user,
                client_ip=client_ip,
            )
            return cast("QuestionDetail", outcome.payload)
        except AppError:
            return self._degraded_detail(approach_id)

    def _validate_detail(self, payload: Any) -> QuestionDetail:
        if not isinstance(payload, dict):
            raise ValueError("detail must be an object")
        hints = [str(h).strip()[:600] for h in (payload.get("hints") or []) if str(h).strip()][:3]
        step = str(payload.get("step_explanation") or "").strip()[:2_000]

        if contains_code(step) or any(contains_code(h) for h in hints):
            raise AiInvalidOutput("detail contains code")

        quality = check_hint_not_a_solution(hints[0] if hints else "", step_explanation=step)
        if not quality.ok and hints and step and hints[0].strip() == step.strip():
            hints = hints[1:]

        return QuestionDetail(
            key_points=[str(p).strip()[:200] for p in (payload.get("key_points") or [])][:6],
            common_wrong=[
                c for c in (payload.get("common_wrong") or []) if isinstance(c, dict)
            ][:6],
            hints=hints,
            step_explanation=step,
            expected_state=[
                str(s).strip()[:200]
                for s in (payload.get("expected_state") or [])
                if str(s).strip()
            ][:6],
        )

    def _degraded_detail(self, approach_id: str) -> QuestionDetail:
        """Knowledge-base fallback.

        §10.3 and §10.8 both promise the learner a question they can answer. The
        curated knowledge base is what makes that promise hold when generation
        fails, which is why every approach entry must carry these fields.
        """
        return QuestionDetail(
            key_points=knowledge.fallback_nudges(approach_id, limit=3),
            common_wrong=[],
            hints=[],
            step_explanation=" ".join(knowledge.fallback_step_notes(approach_id)),
            degraded=True,
        )

    # -- projection: what the client is allowed to see ---

    @staticmethod
    def project_question(
        question: dict[str, Any],
        *,
        total: int,
        attempts: int = 0,
        hints_used: int = 0,
        detail: QuestionDetail | None = None,
        revealed: bool = False,
    ) -> CurrentQuestion:
        """Build the client-facing view.

        Deliberately does not accept the rubric. Passing `detail` is enough for
        hints and the step explanation to be *available*, but the hidden parts
        have nowhere to land in the response model.
        """
        available = bool(detail and detail.hints and not detail.degraded)
        step = None
        if revealed and detail:
            step = detail.step_explanation or None

        return CurrentQuestion(
            index=int(question.get("index", 1)),
            total=total,
            prompt=str(question.get("prompt", "")),
            learning_goal=str(question.get("learning_goal", "")),
            answer_type=AnswerType(question.get("answer_type", AnswerType.SHORT_TEXT)),
            choices=question.get("choices"),
            hints_used=hints_used,
            attempts=attempts,
            hints_available=available,
            step_explanation=step,
            revealed=revealed,
        )

    @staticmethod
    def next_hint(
        detail: QuestionDetail | None, *, hints_used: int, index: int
    ) -> HintResponse:
        """Hints 1 and 2 are `STRICT`; hint 3 is `STEP_SCOPED` (§10.7).

        They come from the detail call, so asking for a hint costs no AI call and
        no credit.
        """
        released = boundary.hint3_released(hints_used=hints_used)
        level = 3 if released else min(3, hints_used + 1)
        text = ""
        if detail and 0 < level <= len(detail.hints):
            text = detail.hints[level - 1]
        if not text:
            text = (
                "Take one more pass at this step. Say out loud what it changes, then try again."
            )
        return HintResponse(index=index, level=level, text=text, is_last=level >= 3)

    @staticmethod
    def shape_to_dict(shape: PlanShape) -> str:
        return json.dumps(
            {"questions": shape.questions, "checklist": shape.checklist},
            ensure_ascii=False,
        )

    @staticmethod
    def shape_from_dict(raw: str | None) -> PlanShape | None:
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        return PlanShape(
            questions=list(data.get("questions") or []),
            checklist=list(data.get("checklist") or []),
        )