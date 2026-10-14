"""Reveal gates (§3.1, §9, §10, §11).

These assertions are the product's core promise: a learner cannot get the
solution by clicking harder. Each test states the rule it defends so a future
change that loosens a gate fails here rather than in front of a user.
"""

from __future__ import annotations

from app.policies import reveal_boundary as boundary
from app.schemas.models import Verdict


class TestChecklistGate:
    def test_locked_before_any_progress(self) -> None:
        assert boundary.checklist_released(total_questions=5, passed=0) is False

    def test_locked_while_questions_remain(self) -> None:
        assert boundary.checklist_released(total_questions=5, passed=4) is False

    def test_released_only_when_every_question_is_passed(self) -> None:
        assert boundary.checklist_released(total_questions=5, passed=5) is True

    def test_empty_plan_never_releases(self) -> None:
        # The degenerate case that must not auto-open the checklist.
        assert boundary.checklist_released(total_questions=0, passed=0) is False
        assert boundary.checklist_released(total_questions=0, passed=9) is False

    def test_single_question_plan(self) -> None:
        assert boundary.checklist_released(total_questions=1, passed=1) is True
        assert boundary.checklist_released(total_questions=1, passed=0) is False


class TestHintGate:
    def test_third_hint_requires_two_prior_hints(self) -> None:
        assert boundary.hint3_released(hints_used=0) is False
        assert boundary.hint3_released(hints_used=1) is False
        assert boundary.hint3_released(hints_used=2) is True
        assert boundary.hint3_released(hints_used=3) is True


class TestStepExplanationGate:
    def test_withheld_before_the_attempt_cap(self) -> None:
        assert boundary.step_explanation_released(attempts=7, attempt_cap=8) is False

    def test_released_at_the_cap(self) -> None:
        assert boundary.step_explanation_released(attempts=8, attempt_cap=8) is True

    def test_released_when_asked_outright(self) -> None:
        # A learner who explicitly asks is not made to fail first.
        assert (
            boundary.step_explanation_released(
                attempts=0, attempt_cap=8, explicit_request=True
            )
            is True
        )


class TestAnalysisGate:
    def test_requires_every_question_passed(self) -> None:
        assert boundary.analysis_released(all_passed=True) is True
        assert boundary.analysis_released(all_passed=False) is False


class TestVerdictFeedback:
    """Feedback permission, not progress.

    Every verdict gets Socratic feedback - a learner who is wrong needs the
    nudge most. What advances a learner is :func:`checklist_released`, driven by
    passed_count, which is tested above.
    """

    def test_correct_shows_feedback(self) -> None:
        assert boundary.verdict_may_show_feedback(Verdict.CORRECT) is True

    def test_partial_shows_feedback(self) -> None:
        assert boundary.verdict_may_show_feedback(Verdict.PARTIAL) is True

    def test_incorrect_shows_feedback(self) -> None:
        assert boundary.verdict_may_show_feedback(Verdict.INCORRECT) is True

    def test_feedback_permission_does_not_unlock_anything(self) -> None:
        # Belt and braces: showing feedback must never advance the gate.
        for verdict in Verdict:
            assert boundary.verdict_may_show_feedback(verdict) is True
            assert (
                boundary.checklist_released(total_questions=3, passed=0) is False
            )


class TestApproachAllowlist:
    def test_is_not_empty(self) -> None:
        assert len(boundary.allowed_approaches()) > 0

    def test_includes_the_baseline(self) -> None:
        # Brute force is the guaranteed fallback for every problem.
        assert "brute_force" in boundary.allowed_approaches()

    def test_policies_resolve_for_known_artifacts(self) -> None:
        for artifact in ("concept", "micro_question", "checklist", "hint"):
            assert boundary.policies_for(artifact), f"no policy table for {artifact}"