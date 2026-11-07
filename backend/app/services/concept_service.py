"""Concept cards and the simplification ladder (§9).

One AI call produces the card **and** its diagram, so the words and the picture
describe the same thing. Content depends only on problem, approach, language and
mode, so it is cached across users and revisiting a problem costs nothing.

"I still don't get it" has two levels and then stops. A third click nudges the
learner forward to the first micro-question instead of calling the AI again:
more levels stop helping, and the infinite button is how a learner learns to
spam it.
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import TypeAdapter, ValidationError

from ..ai import knowledge
from ..ai.prompts import concept as concept_prompt
from ..ai.prompts import concept_simplify as simplify_prompt
from ..ai.prompts import problem_block
from ..core.logging import get_logger
from ..schemas.models import (
    ConceptCard,
    LearningDiagramSpec,
    SimplifiedConcept,
)
from ..validators.diagram_sanity import validate_diagram
from ..validators.quality import check_humour, check_specificity, problem_tokens_from
from .generator import ContentGenerator, GenerateRequest, build_system, schema_for

MAX_SIMPLIFICATION_LEVELS = 2

logger = get_logger(__name__)

# : Resolves the discriminator tag on a learning diagram to its concrete model.
_DIAGRAM_ADAPTER: TypeAdapter[Any] = TypeAdapter(LearningDiagramSpec)

class ConceptService:
    task_id = "concept.v1"
    simplify_task_id = "concept_simplify.v1"

    def __init__(self, generator: ContentGenerator) -> None:
        self.generator = generator

    async def build_card(
        self,
        *,
        problem: dict[str, Any],
        approach_id: str,
        approach_name: str,
        language: str,
        mode: str,
        client_ip: str | None = None,
    ) -> ConceptCard:
        grounding = knowledge.grounding_for(approach_id)
        example_inputs = [
            str(example.get("input", "")) for example in problem.get("examples") or []
        ]

        user = concept_prompt(
            problem,
            approach_id=approach_id,
            grounding=grounding,
            diagram_schema={"_max_items": 12},
        )

        request = GenerateRequest(
            task_id=self.task_id,
            slug=str(problem.get("slug", "")),
            statement_text=str(problem.get("statement_text", "")),
            constraints_text=str(problem.get("constraints_text", "")),
            approach_id=approach_id,
            language=language,
            mode=mode,
            schema=schema_for(ConceptCard),
            adapter=ConceptCard.model_validate,
            tier="balanced",
            temperature=0.5,
            max_tokens=1_400,
            deadline_s=30.0,
            pool="generation",
            example_inputs=example_inputs,
        )

        outcome = await self.generator.generate(
            request,
            system=build_system(language=language, mode=mode),
            user=user,
            client_ip=client_ip,
        )

        card = self._finalise(outcome.payload, problem=problem, approach_name=approach_name)
        return card

    def _finalise(
        self, payload: Any, *, problem: dict[str, Any], approach_name: str
    ) -> ConceptCard:
        card = payload if isinstance(payload, ConceptCard) else ConceptCard.model_validate(payload)
        card.title = card.title or approach_name

        tokens = problem_tokens_from(
            str(problem.get("title", "")),
            str(problem.get("statement_text", "")),
            str(problem.get("constraints_text", "")),
        )

        specificity = check_specificity(
            f"{card.simple_explanation} {card.why_it_fits_this_problem}", problem_tokens=tokens
        )
        if not specificity.ok:
            # Specificity is a quality signal, not a leak. A weak card is still
            # delivered rather than blocking a learner on a heuristic.
            card.why_it_fits_this_problem = (
                f"{card.why_it_fits_this_problem} "
                f"(for {problem.get('title', 'this problem')} in particular)"
            )

        humour = check_humour(card.humour_line)
        if not humour.ok:
            # -9.4: a rejected line is dropped, never regenerated.
            card.humour_line = None

        card.diagram = self._diagram_or_none(card.diagram, problem=problem)
        # The ceiling is a property of the product, not of what the model chose
        # to emit. Leaving this at the schema default of 0 hid the simplify
        # affordance on every card.
        card.simplified_levels_available = MAX_SIMPLIFICATION_LEVELS
        return card

    def _diagram_or_none(
        self, diagram: Any, *, problem: dict[str, Any]
    ) -> LearningDiagramSpec | None:
        """A bad diagram costs a text-only card, never the whole concept card."""
        if diagram is None:
            return None
        example_inputs = [
            str(example.get("input", "")) for example in problem.get("examples") or []
        ]
        report = validate_diagram(diagram, example_inputs=example_inputs)
        if not report.ok:
            logger.info("diagram rejected: %s", "; ".join(report.problems[:3]))
            return None
        # A discriminated union is not a class, so it has no model_validate; the
        # adapter is what resolves the "kind" tag to a concrete model.
        raw = diagram if isinstance(diagram, dict) else diagram.model_dump(by_alias=True)
        try:
            return cast("LearningDiagramSpec", _DIAGRAM_ADAPTER.validate_python(raw))
        except ValidationError:
            logger.info("diagram failed union validation after passing sanity checks")
            return None

    async def simplify(
        self,
        *,
        problem: dict[str, Any],
        approach_id: str,
        card: ConceptCard,
        level: int,
        language: str,
        mode: str,
        client_ip: str | None = None,
    ) -> SimplifiedConcept:
        target = max(1, min(MAX_SIMPLIFICATION_LEVELS, level))
        previous = f"{card.simple_explanation}\n{card.why_it_fits_this_problem}"

        request = GenerateRequest(
            task_id=self.simplify_task_id,
            slug=str(problem.get("slug", "")),
            statement_text=str(problem.get("statement_text", "")),
            constraints_text=str(problem.get("constraints_text", "")),
            approach_id=approach_id,
            language=language,
            mode=mode,
            schema=schema_for(SimplifiedConcept),
            adapter=SimplifiedConcept.model_validate,
            tier="fast",
            temperature=0.5,
            max_tokens=600,
            deadline_s=15.0,
            variant=f"level{target}",
        )

        user = (
            f"{problem_block(problem)}\n\n" + simplify_prompt(previous, level=target,
                                                             approach_id=approach_id)
        )
        outcome = await self.generator.generate(
            request,
            system=build_system(language=language, mode=mode),
            user=user,
            client_ip=client_ip,
        )
        simplified = (
            outcome.payload
            if isinstance(outcome.payload, SimplifiedConcept)
            else SimplifiedConcept.model_validate(outcome.payload)
        )
        simplified.at_max_level = target >= MAX_SIMPLIFICATION_LEVELS
        return simplified

    @staticmethod
    def at_max_level(current: int) -> bool:
        return current >= MAX_SIMPLIFICATION_LEVELS