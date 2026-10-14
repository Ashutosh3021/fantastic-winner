"""Quality checks that are not about leaking (§12.4, §10.4).

Cheap, deterministic checks that catch the two failure modes that actually show
up in review: content that ignores the problem it was given (the generic-AI-text
risk, PLAN §13), and a hint that quietly gives the whole answer while claiming
to be a nudge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_WORD = re.compile(r"[\w']+")

# : Phrases that mean "this text is about algorithms in general", not this problem.
_GENERIC_MARKERS = (
    "in this problem",
    "for this problem",
    "this problem",
    "given the input",
    "the array",
    "the string",
    "the example",
)

_STOPWORDS = frozenset(
    [
        "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with",
        "is", "are", "be", "this", "that", "it", "as", "at", "by", "from",
        "we", "you", "given", "return", "if", "not", "but", "so", "your",
        "their", "our", "its", "can", "will", "should", "would", "could",
    ]
)

@dataclass
class QualityReport:
    ok: bool = True
    problems: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.ok = False
        self.problems.append(reason)

def _content_tokens(text: str) -> set[str]:
    return {
        word.lower()
        for word in _WORD.findall(text)
        if len(word) > 3 and word.lower() not in _STOPWORDS
    }

def check_specificity(text: str, *, problem_tokens: set[str]) -> QualityReport:
    """Does the explanation actually engage with *this* problem?

    A generic card reads fluently and teaches nothing specific, which is the
    exact risk PLAN §13 lists. We measure overlap with the problem's own title,
    statement and constraints and flag content that mentions none of it.
    """
    report = QualityReport()
    text = (text or "").strip()
    if len(text) < 40:
        report.fail("too_short")
        return report

    tokens = _content_tokens(text)
    if not tokens:
        report.fail("no_content_words")
        return report

    if not (tokens & problem_tokens):
        report.fail("not_specific_to_problem")

    lowered = text.lower()
    if not any(marker in lowered for marker in _GENERIC_MARKERS):
        report.fail("never_references_the_problem")

    return report

def check_answerable(prompt: str, *, answer_type: str, choices: list[str] | None) -> QualityReport:
    """A question the server will check must be checkable.

    Deterministic answer types need choices to compare against; without them the
    only possible verdict is a judge call, which costs tokens on an action the
    product prices at zero.
    """
    report = QualityReport()
    if len(prompt.strip()) < 10:
        report.fail("prompt_too_short")
    if answer_type in {"single_choice", "multi_choice", "order_steps"}:
        if not choices or len(choices) < 2:
            report.fail(f"{answer_type} requires at least two choices")
        elif len(set(choices)) != len(choices):
            report.fail("duplicate_choices")
    return report

def check_hint_not_a_solution(hint: str, *, step_explanation: str | None) -> QualityReport:
    """Hints 1 and 2 must nudge. Hint 3 may not pretend to nudge while solving."""
    report = QualityReport()
    text = (hint or "").strip()
    if not text:
        report.fail("empty_hint")
        return report
    if len(text) > 600:
        report.fail("hint_too_long")
    if step_explanation and text.strip() == step_explanation.strip():
        report.fail("hint_duplicates_step_explanation")
    return report

def check_humour(humour_line: str | None) -> QualityReport:
    """Humour is optional and filtered, not regenerated (§9.4).

    A rejected line is dropped, so a failure here is a soft signal.
    """
    report = QualityReport()
    if not humour_line:
        return report
    text = humour_line.strip()
    if len(text) > 200:
        report.fail("humour_too_long")
    lowered = text.lower()
    # Sarcasm aimed at the learner, or a joke about their mistake, is exactly
    # what -9.4 rules out.
    if any(marker in lowered for marker in ("you dummy", "you're stupid", "idiot", "lol you")):
        report.fail("humour_targets_the_learner")
    return report

def problem_tokens_from(*texts: str) -> set[str]:
    """Tokens that make a piece of writing recognisably about this problem."""
    tokens: set[str] = set()
    for text in texts:
        tokens |= _content_tokens(text or "")
    return tokens