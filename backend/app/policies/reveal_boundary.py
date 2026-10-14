"""The reveal boundary (§11).

This table is the whole definition of "CodeMentor never gives away the
solution". The validators read it, the routes read it, the tests read it, and
the Chrome Web Store listing is written from it (§11.2).

It exists as data rather than as a comment repeated in five places because the
product requirement is genuinely per-artifact: the checklist *is* the algorithm,
and no single global rule can both forbid and require it. Adding an artifact
means adding one row.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from ..schemas.models import ApproachId, Verdict


class Policy(StrEnum):
    """How strictly an artifact is leak-checked."""

    # : No code and no complete algorithm. The default for everything pre-attempt.
    STRICT = "STRICT"

    # : May describe *its own step* completely, but not the whole algorithm.
    # : Only reachable after the learner has demonstrably failed at it.
    STEP_SCOPED = "STEP_SCOPED"

    # : The artifact *is* the algorithm. Only reachable after every question for
    # : that approach is passed. Still checked for code.
    EARNED = "EARNED"

@dataclass(frozen=True)
class Artifact:
    """One AI-produced artifact and the rules that govern it."""

    name: str
    # : When the backend is allowed to release it at all.
    visible_when: str
    # : Policies this artifact is checked under, in order.
    policies: tuple[Policy, ...]
    # : May it ever contain code? No - across the entire product.
    code_ever: bool = False
    # : Only user-authored content may appear, and only on the analysis route.
    user_code_only: bool = False
    # : Visible to the client in full?
    client_visible: bool = True

STRICT = (Policy.STRICT,)
STEP_SCOPED = (Policy.STRICT, Policy.STEP_SCOPED)
EARNED = (Policy.STRICT, Policy.STEP_SCOPED, Policy.EARNED)

ARTIFACTS: dict[str, Artifact] = {
    "approach_list": Artifact(
        name="Approach list",
        visible_when="On problem detection",
        policies=STRICT,
    ),
    "concept_card": Artifact(
        name="Concept card",
        visible_when="After approach selection",
        policies=STRICT,
    ),
    "simplification_l1_l2": Artifact(
        name="Simplification level 1-2",
        visible_when="On request",
        policies=STRICT,
    ),
    "question_prompt": Artifact(
        name="Micro-question prompt",
        visible_when="After the previous question is passed",
        policies=STRICT,
    ),
    "hint_l1_l2": Artifact(
        name="Hint level 1-2",
        visible_when="On request",
        policies=STRICT,
    ),
    "judge_feedback": Artifact(
        name="Judge feedback",
        visible_when="On each answer",
        policies=STRICT,
    ),
    "diagram_text": Artifact(
        name="Diagram captions and data labels",
        visible_when="With the card or question above",
        policies=STRICT,
    ),
    "hint_l3": Artifact(
        name="Hint level 3 (near-answer)",
        visible_when="After hints 1-2 are used",
        policies=STEP_SCOPED,
    ),
    "step_explanation": Artifact(
        name="Step explanation",
        visible_when="After the attempt cap, or on explicit request",
        policies=STEP_SCOPED,
    ),
    "checklist": Artifact(
        name="Full-solution checklist",
        visible_when="After the last question is passed",
        policies=EARNED,
    ),
    "analysis_fragments": Artifact(
        name="Solution analysis",
        visible_when="After Solution Mode",
        policies=EARNED,
        user_code_only=True,
    ),
}

@dataclass(frozen=True)
class CheckDecision:
    allowed: bool
    reason: str = ""
    # : Policies actually applied, for the validator to run.
    applied: tuple[Policy, ...] = ()

def check(artifact_name: str, *, released: bool) -> CheckDecision:
    """Decide whether an artifact may be shown, and under which policies.

    ``released`` is the *timing* gate - the caller passes True only once the
    conditions in ``visible_when`` hold. The leak detector is the second line,
    not the first: it catches bad wording inside an artifact that is allowed to
    exist at all (§11.3).
    """
    artifact = ARTIFACTS.get(artifact_name)
    if artifact is None:
        return CheckDecision(
            allowed=False,
            reason=f"Unknown artifact '{artifact_name}' has no policy row; refusing by default.",
        )
    if not released:
        return CheckDecision(
            allowed=False,
            reason=f"{artifact.name} is not released yet ({artifact.visible_when}).",
            applied=artifact.policies,
        )
    return CheckDecision(allowed=True, applied=artifact.policies)

def policies_for(artifact_name: str) -> tuple[Policy, ...]:
    artifact = ARTIFACTS.get(artifact_name)
    if artifact is None:
        # Unknown artifact: apply the strictest possible reading.
        return STRICT
    return artifact.policies

# -- release predicates ---

def checklist_released(*, total_questions: int, passed: int) -> bool:
    """The checklist is earned, not merely requested (§11.2, §3.1 of PLAN.md).

    Two independent ways to earn it: pass every question, or pass one on a
    single-question plan (which is the same thing) - the degenerate case where a
    plan shape contained no questions must never auto-release.
    """
    if total_questions <= 0:
        return False
    return passed >= total_questions

def hint3_released(*, hints_used: int) -> bool:
    """Hint 3 requires two prior hints on a question you could not answer."""
    return hints_used >= 2

def step_explanation_released(
    *, attempts: int, attempt_cap: int, explicit_request: bool = False
) -> bool:
    """§10.8: after enough failures, or when the learner asks outright."""
    return explicit_request or attempts >= attempt_cap

def analysis_released(*, all_passed: bool) -> bool:
    return all_passed

# -- prompt-time and validator-time mapping ---

# : Which artifact a generated payload belongs to, per AI task.
TASK_ARTIFACT: dict[str, str] = {
    "approaches.v1": "approach_list",
    "concept.v1": "concept_card",
    "concept_simplify.v1": "simplification_l1_l2",
    "microq_shape.v1": "question_prompt",
    "microq_detail.v1": "hint_l3",
    "judge.v1": "judge_feedback",
    "analysis.v1": "analysis_fragments",
    "approach_signal.v1": "approach_list",
    "complexity_static.v1": "analysis_fragments",
}

def verdict_may_show_feedback(verdict: Verdict) -> bool:
    """Whether judge feedback may be shown for this verdict.

    Always true: feedback has to be Socratic whatever the verdict, because a
    learner who is wrong needs the nudge most of all.

    This is deliberately *not* the gate. Progress is gated by
    :func:`checklist_released`, driven by how many questions were passed - a
    name like "releasable" next to a reveal policy invites exactly that
    confusion, so it is spelled out here instead.
    """
    return verdict in {Verdict.CORRECT, Verdict.PARTIAL, Verdict.INCORRECT}

def allowed_approaches() -> frozenset[ApproachId]:
    return frozenset(ApproachId)

LeakCheckMode = Literal["STRICT", "STEP_SCOPED", "EARNED"]

def effective_mode(policies: tuple[Policy, ...]) -> LeakCheckMode:
    """The loosest policy in the set is the one that governs the check.

    An artifact checked under ``EARNED`` still gets the code check; it is exempt
    from the *algorithm-completeness* check, because by the time it becomes
    visible the learner has already written the algorithm as their own answers.
    """
    if Policy.EARNED in policies:
        return "EARNED"
    if Policy.STEP_SCOPED in policies:
        return "STEP_SCOPED"
    return "STRICT"