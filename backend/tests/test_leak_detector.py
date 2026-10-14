"""The leak detector guards the product's main promise (§11.2).

Nothing the API returns may contain code or a complete algorithm, because the
learner is supposed to be the one who writes it. These tests pin both halves:
code is caught even when it is dressed up, and ordinary teaching prose is not
caught by mistake - a false positive here makes the tutor useless.
"""

from __future__ import annotations

import pytest

from app.validators.leak_detector import (
    contains_code,
    detect_leaks,
    is_complete_algorithm,
)


class TestContainsCode:
    def test_detects_a_fenced_block(self) -> None:
        assert contains_code("Here you go:\n```python\nprint(1)\n```") is True

    def test_detects_a_real_function_body(self) -> None:
        # The property that matters: a pasted solution is code, not prose.
        solution = (
            "def two_sum(nums, target):\n"
            "    seen = {}\n"
            "    for i, n in enumerate(nums):\n"
            "        if target - n in seen:\n"
            "            return [seen[target - n], i]\n"
            "        seen[n] = i"
        )
        assert contains_code(solution) is True

    def test_detects_a_real_loop_body(self) -> None:
        loop = "for i in range(len(nums)):\n    total += nums[i]\n    count += 1"
        assert contains_code(loop) is True

    def test_a_single_code_line_is_treated_as_a_mention(self) -> None:
        # Deliberate. "the loop visits every element" and "def solve(nums):"
        # can both be prose, and flagging them would strip real explanations.
        assert contains_code("Think about a helper like def solve(nums):") is False
        assert contains_code("A loop like for i in range(n) works.") is False

    @pytest.mark.parametrize(
        "text",
        [
            "We keep a running maximum as we scan.",
            "Start with an empty set and add each number.",
            "The loop visits every element once.",
            "Two Sum asks for two indices whose values add to the target.",
        ],
    )
    def test_plain_teaching_prose_is_not_code(self, text: str) -> None:
        # A false positive here would strip legitimate explanations and is the
        # more damaging failure of the two.
        assert contains_code(text) is False


class TestDetectLeaks:
    def test_clean_text_reports_clean(self) -> None:
        report = detect_leaks("We walk the list once, keeping the best seen so far.")
        assert report.clean is True
        assert report.reasons() == []

    def test_fenced_block_is_reported(self) -> None:
        report = detect_leaks("```python\nfor x in y:\n    pass\n```")
        assert report.clean is False
        assert report.reasons()

    def test_language_parameter_is_accepted(self) -> None:
        assert detect_leaks("nothing here", language="python").clean is True

    def test_reasons_are_stable_and_short(self) -> None:
        report = detect_leaks("```\nx\n```")
        for reason in report.reasons():
            assert isinstance(reason, str)
            assert 0 < len(reason) < 200


class TestCompleteAlgorithm:
    """Completeness is detected by explicit structural markers.

    It deliberately does not try to judge whether a paragraph "adds up to an
    algorithm": that judgement is what produces false positives, and a block
    wrongly flagged as a complete solution is regenerated and re-billed.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "Do it in this order: build the set, then scan, then return.",
            "Here is the full solution in words.",
            "This is the complete algorithm.",
            "First build a set. Then scan the array. Finally return both indices.",
        ],
    )
    def test_explicit_markers_are_caught(self, text: str) -> None:
        assert is_complete_algorithm(text) is True

    def test_a_single_step_is_not_complete(self) -> None:
        # One step of a solution must be allowed through; blocking it would make
        # micro-questions impossible.
        assert is_complete_algorithm("Add each number to a set as you go.") is False

    def test_multi_step_prose_without_markers_is_not_flagged(self) -> None:
        # The safe failure: a numbered-looking explanation that never says "in
        # this order" passes the STRICT check and is judged by the leak pass.
        text = (
            "Keep a set. Look at each number. Check its complement. "
            "Add it when it is not there."
        )
        assert is_complete_algorithm(text) is False

    def test_empty_text_is_not_complete(self) -> None:
        assert is_complete_algorithm("") is False