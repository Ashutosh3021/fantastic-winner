"""Static complexity reconciliation, XP maths and cache keys (§13.1.2, §19.4, §15.7).

Small pure functions, but each one feeds a number a beginner trusts, so they are
pinned rather than left to inspection.
"""

from __future__ import annotations

from app.cache.store import ContentCache
from app.services.projector import XP_ATTEMPT, XP_PASS, level_for_xp, xp_for_level
from app.services.static_analysis import analyse, reconcile


class TestStaticAnalysis:
    def test_python_is_parsed_exactly(self) -> None:
        code = "for i in range(n):\n    for j in range(n):\n        total += 1"
        facts = analyse(code, language="python")
        assert facts.method == "ast"
        assert facts.max_loop_depth == 2

    def test_recursion_is_detected(self) -> None:
        code = "def f(n):\n    return f(n - 1)"
        assert analyse(code, language="python").recurses is True

    def test_memoised_recursion_is_distinguished(self) -> None:
        code = "from functools import lru_cache\n\n@lru_cache\ndef f(n):\n    return f(n - 1)"
        facts = analyse(code, language="python")
        assert facts.recurses is True
        assert facts.memoised_recursion is True

    def test_empty_code_is_unavailable_not_wrong(self) -> None:
        assert analyse("", language="python").method == "unavailable"

    def test_broken_python_falls_back_and_says_so(self) -> None:
        facts = analyse("def (", language="python")
        assert facts.method == "heuristic"
        assert facts.notes, "a parse failure must be reported, not hidden"

    def test_other_languages_use_the_heuristic(self) -> None:
        facts = analyse("for (int i = 0; i < n; i++) {}", language="cpp")
        assert facts.method == "heuristic"


class TestReconciliation:
    def test_agreement_is_high_confidence(self) -> None:
        facts = analyse("for i in range(n):\n    total += i", language="python")
        _, confidence, estimated = reconcile(ai_class="O(n)", facts=facts)
        assert confidence == "high"
        assert estimated is False

    def test_large_disagreement_is_flagged_not_averaged(self) -> None:
        facts = analyse(
            "def f(n):\n    return f(n - 1)", language="python"
        )
        time_class, confidence, estimated = reconcile(ai_class="O(1)", facts=facts)
        assert confidence == "low"
        assert estimated is True
        assert time_class == "O(1)", "the model's call is kept, but marked uncertain"

    def test_small_disagreement_is_medium(self) -> None:
        facts = analyse("for i in range(n):\n    for j in range(n):\n        total += 1",
                        language="python")
        _, confidence, _ = reconcile(ai_class="O(n log n)", facts=facts)
        assert confidence in ("medium", "low")


class TestNMax:
    def test_reads_a_bound_from_the_constraints(self) -> None:
        from app.services.analysis_service import parse_n_max

        assert parse_n_max("2 <= n <= 10^5").value == 100_000
        assert parse_n_max("2 <= n <= 10^5").source == "constraints"

    def test_falls_back_to_a_plausible_bare_number(self) -> None:
        from app.services.analysis_service import parse_n_max

        parsed = parse_n_max("at most 50000 elements")
        assert parsed.value == 50000
        assert parsed.source == "assumed"

    def test_ignores_absurd_numbers(self) -> None:
        from app.services.analysis_service import parse_n_max

        # A test count or a modulus must not be mistaken for n.
        assert parse_n_max("<= 100000000000").source == "assumed"

    def test_no_constraints_still_yields_a_usable_value(self) -> None:
        from app.services.analysis_service import parse_n_max

        parsed = parse_n_max("")
        assert parsed.value > 0
        assert parsed.source == "assumed"


class TestBudgetOps:
    def test_grows_with_the_class(self) -> None:
        from app.services.analysis_service import budget_ops

        assert budget_ops("O(n)", 1000) < budget_ops("O(n^2)", 1000)
        assert budget_ops("O(n^2)", 1000) < budget_ops("O(n^3)", 1000)

    def test_is_always_positive(self) -> None:
        from app.services.analysis_service import budget_ops

        for cls in ("O(1)", "O(log n)", "O(n)", "O(n log n)", "O(n^2)", "O(2^n)"):
            assert budget_ops(cls, 1000) > 0


class TestLevels:
    def test_level_one_starts_at_zero_xp(self) -> None:
        assert xp_for_level(1) == 0

    def test_levels_are_monotonic(self) -> None:
        for level in range(1, 12):
            assert xp_for_level(level) < xp_for_level(level + 1)

    def test_level_for_xp_round_trips(self) -> None:
        for level in range(1, 12):
            assert level_for_xp(xp_for_level(level)) == level

    def test_no_xp_is_level_one(self) -> None:
        assert level_for_xp(0) == 1

    def test_xp_values_are_monotonic(self) -> None:
        assert level_for_xp(99) == 1
        assert level_for_xp(100) >= 2


class TestXpAwards:
    def test_passing_is_worth_more_than_attempting(self) -> None:
        assert XP_PASS > XP_ATTEMPT


class TestCacheKeys:
    def test_same_input_yields_same_key(self) -> None:
        a = ContentCache.server_content_hash("statement", "constraints")
        b = ContentCache.server_content_hash("statement", "constraints")
        assert a == b

    def test_different_constraints_yield_different_keys(self) -> None:
        # The regression this pins: the invisible-character class once matched
        # ordinary letters, every normalised string came out empty, and all
        # learners shared one cache row.
        assert ContentCache.server_content_hash("s", "n <= 10^4") != (
            ContentCache.server_content_hash("s", "n <= 10^5")
        )

    def test_different_statements_yield_different_keys(self) -> None:
        assert ContentCache.server_content_hash("two sum", "x") != (
            ContentCache.server_content_hash("three sum", "x")
        )

    def test_whitespace_does_not_change_the_key(self) -> None:
        assert ContentCache.server_content_hash("Two  Sum", "x") == (
            ContentCache.server_content_hash("Two Sum", "x")
        )

    def test_zero_width_characters_do_not_change_the_key(self) -> None:
        assert ContentCache.server_content_hash("Two Sum", "x") == (
            ContentCache.server_content_hash("Two\u200b Sum", "x")
        )

    def test_case_is_significant_by_design(self) -> None:
        # Not normalised away: lowercasing would orphan every cached row already
        # in the datastore for no gain the learner would notice.
        assert ContentCache.server_content_hash("Two Sum", "x") != (
            ContentCache.server_content_hash("two sum", "x")
        )