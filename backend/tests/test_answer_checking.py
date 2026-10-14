"""Deterministic answer checking (§10.5).

Answering a question is free, so the checker must be right without spending
anything. These tests pin the rules that decide a verdict, and the Socratic
property that feedback never states the answer.
"""

from __future__ import annotations

import pytest

from app.schemas.models import AnswerType, MistakeType, Verdict
from app.services.answer_checking import (
    check_fill_blank,
    check_order_steps,
    deterministic_check,
    matches_synonym,
    normalise,
    nudge_for,
    token_overlap,
)


class TestNormalisation:
    def test_case_and_punctuation_are_ignored(self) -> None:
        assert normalise("Left, index!") == normalise("left index")

    def test_articles_are_preserved(self) -> None:
        # An earlier version stripped a leading article and turned "a b" into
        # "b", silently deleting a token the learner had typed.
        assert normalise("a b") == "a b"
        assert normalise("the maximum") == "the maximum"

    def test_whitespace_collapses(self) -> None:
        assert normalise("  a   b  ") == "a b"


class TestSynonyms:
    @pytest.mark.parametrize(
        ("answer", "expected"),
        [
            ("largest", "max"),
            ("HashMap", "dict"),
            ("counter", "count"),
            ("idx", "index"),
        ],
    )
    def test_common_substitutions_are_accepted(self, answer: str, expected: str) -> None:
        assert matches_synonym(answer, expected) is True

    def test_unrelated_word_is_rejected(self) -> None:
        assert matches_synonym("queue", "max") is False


class TestFillBlank:
    def test_exact_answer_is_correct(self) -> None:
        result = check_fill_blank(answer="hash map", key_points=["hash map"])
        assert result.verdict == Verdict.CORRECT

    def test_synonym_is_correct(self) -> None:
        result = check_fill_blank(answer="counter", key_points=["count"])
        assert result.verdict == Verdict.CORRECT

    def test_overlapping_wording_is_partial_not_wrong(self) -> None:
        # Telling a beginner who is nearly right that they are wrong is the worst
        # failure this product has.
        result = check_fill_blank(
            answer="the largest number we have seen", key_points=["largest seen so far"]
        )
        assert result.verdict in (Verdict.CORRECT, Verdict.PARTIAL)

    def test_unrelated_answer_is_incorrect_with_a_mistake_type(self) -> None:
        result = check_fill_blank(answer="purple", key_points=["largest seen so far"])
        assert result.verdict == Verdict.INCORRECT
        assert result.mistake_type is not None

    def test_empty_answer_is_incorrect(self) -> None:
        result = check_fill_blank(answer="  ", key_points=["set"])
        assert result.verdict == Verdict.INCORRECT


class TestOrderSteps:
    def test_canonical_order_is_correct(self) -> None:
        result = check_order_steps(
            order=[0, 1, 2],
            choices=["a", "b", "c"],
            key_points=["first", "then", "finally"],
        )
        assert result.verdict == Verdict.CORRECT

    def test_incomplete_permutation_is_rejected(self) -> None:
        result = check_order_steps(
            order=[0, 0, 1], choices=["a", "b", "c"], key_points=["x", "y", "z"]
        )
        assert result.verdict == Verdict.INCORRECT

    def test_a_swapped_pair_is_partial(self) -> None:
        result = check_order_steps(
            order=[1, 0, 2],
            choices=["a", "b", "c"],
            key_points=["first", "then", "finally"],
        )
        assert result.verdict == Verdict.PARTIAL
        assert result.mistake_type == MistakeType.OFF_BY_ONE

    def test_wildly_wrong_order_is_incorrect(self) -> None:
        result = check_order_steps(
            order=[2, 1, 0],
            choices=["a", "b", "c"],
            key_points=["first", "then", "finally"],
        )
        assert result.verdict == Verdict.INCORRECT


class TestDeterministicRouting:
    def test_short_text_is_left_to_the_judge(self) -> None:
        result = deterministic_check(
            answer_type=AnswerType.SHORT_TEXT,
            answer="because",
            choice_indexes=None,
            order=None,
            choices=None,
            key_points=["a"],
        )
        assert result is None, "short_text must fall through to the AI judge"

    def test_choice_types_never_reach_the_judge(self) -> None:
        for answer_type in (
            AnswerType.SINGLE_CHOICE,
            AnswerType.MULTI_CHOICE,
            AnswerType.FILL_BLANK,
            AnswerType.ORDER_STEPS,
        ):
            result = deterministic_check(
                answer_type=answer_type,
                answer="x",
                choice_indexes=[0],
                order=None,
                choices=["x", "y"],
                key_points=["x"],
            )
            assert result is not None, f"{answer_type} should be decided deterministically"


class TestNudges:
    def test_correct_gets_praise(self) -> None:
        from app.services.answer_checking import CheckResult

        assert nudge_for(CheckResult(Verdict.CORRECT))

    def test_feedback_never_contains_code(self) -> None:
        from app.services.answer_checking import CheckResult
        from app.validators.leak_detector import contains_code

        for verdict in Verdict:
            for mistake in MistakeType:
                text = nudge_for(CheckResult(verdict, mistake_type=mistake))
                assert not contains_code(text), f"leak in nudge for {verdict}/{mistake}"

    def test_nudge_is_not_empty(self) -> None:
        from app.services.answer_checking import CheckResult

        for verdict in Verdict:
            for mistake in MistakeType:
                assert nudge_for(CheckResult(verdict, mistake_type=mistake)).strip()


class TestTokenOverlap:
    def test_identical_is_one(self) -> None:
        assert token_overlap("set", "set") == 1.0

    def test_disjoint_is_zero(self) -> None:
        assert token_overlap("set", "queue") == 0.0

    def test_partial_is_between(self) -> None:
        score = token_overlap("largest seen", "largest value so far")
        assert 0.0 < score < 1.0

    def test_empty_input_is_zero_not_an_error(self) -> None:
        assert token_overlap("", "set") == 0.0