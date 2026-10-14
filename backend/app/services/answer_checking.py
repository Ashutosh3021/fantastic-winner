"""Answer checking (§10.5, §10.6).

Deterministic first, AI judge second. Answering a question is a **0-credit**
action, so every call we avoid here is a call we do not pay for, and every
verdict we avoid guessing is a verdict a beginner can trust.

The answer type decides who checks:

* ``single_choice`` / ``multi_choice`` / ``order_steps`` / ``fill_blank`` /
  ``predict_state`` - exact or normalised comparison, no AI at all.
* ``short_text`` - the fast-tier judge against the rubric.

``fill_blank`` uses a small synonym table. That table is deliberately
conservative: a synonym the learner invents is a *partial* verdict with a nudge,
not a wrong answer, because telling a beginner they are wrong when they are
right is the single worst thing this product can do.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ..schemas.models import AnswerType, MistakeType, Verdict

#: Coverage of the expected key needed to call an answer partial rather than
#: wrong. Deliberately generous: a false "wrong" costs the learner more than a
#: generous "partial" does.
COVERAGE_PARTIAL = 0.5


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace.

    Deliberately does *not* strip leading articles. "a b" is a legitimate pair of
    tokens and an earlier version of this returned "b" for it, silently eating a
    word the learner had actually typed. The phrase matchers tolerate a leading
    article anyway, so nothing is lost by not guessing here.
    """
    folded = unicodedata.normalize("NFKD", text or "").lower().strip()
    folded = re.sub(r"[^\w\s]", " ", folded)
    return re.sub(r"\s+", " ", folded).strip()


def token_overlap(a: str, b: str) -> float:
    left = set(normalise(a).split())
    right = set(normalise(b).split())
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def coverage(answer: str, expected: str) -> float:
    """How much of ``expected`` the answer accounts for.

    Asymmetric on purpose. Jaccard punishes a learner for adding words, so
    "the largest number we have seen" scored 0.29 against "largest seen so far"
    and was marked wrong when the idea was plainly there. Coverage asks the
    question that matters instead: did they hit the parts we asked for?
    """
    left = set(normalise(answer).split())
    right = set(normalise(expected).split())
    if not left or not right:
        return 0.0
    return len(left & right) / len(right)
@dataclass
class CheckResult:
    verdict: Verdict
    matched_key_points: list[int] = field(default_factory=list)
    mistake_type: MistakeType | None = None
    # : Present when the AI judge produced one; never contains code.
    feedback: str = ""
    used_ai: bool = False

# -- synonyms for fill_blank ---

_SYNONYMS: dict[str, tuple[str, ...]] = {
    "left": ("left", "l", "start", "beginning", "first", "leftedge"),
    "right": ("right", "r", "end", "last", "rightedge"),
    "set": ("set", "hashset", "setof", "hashset"),
    "dict": ("dict", "dictionary", "map", "hashmap", "object"),
    "list": ("list", "array", "vector", "listof"),
    "count": ("count", "counter", "counts", "frequency", "freq"),
    "max": ("max", "maximum", "largest", "best", "biggest"),
    "min": ("min", "minimum", "smallest"),
    "sum": ("sum", "total", "accumulate", "running"),
    "index": ("index", "idx", "position", "i"),
    "increment": ("increment", "inc", "increase", "advance", "next"),
    "decrement": ("decrement", "dec", "decrease", "back"),
    "true": ("true", "yes"),
    "false": ("false", "no"),
    "top": ("top", "stack", "peek", "last"),
    "first": ("first", "front", "head", "start"),
}

def matches_synonym(answer: str, expected: str) -> bool:
    cleaned = normalise(answer).replace(" ", "")
    target = normalise(expected).replace(" ", "")
    if not target:
        return False
    if cleaned == target:
        return True
    family = _SYNONYMS.get(target, ())
    if cleaned in family:
        return True
    # A learner who wrote the whole expected phrase has answered correctly even
    # if it contains the target word.
    return target in cleaned and len(cleaned) <= len(target) + 12

# -- deterministic checks ---

def check_single_choice(
    *, chosen: list[int] | None, choices: list[str] | None, key_points: list[str]
) -> CheckResult:
    if not chosen or not choices:
        return CheckResult(Verdict.INCORRECT, mistake_type=MistakeType.OTHER)
    if len(chosen) == 1:
        index = chosen[0]
        if 0 <= index < len(choices) and matches_synonym(
            choices[index], key_points[0] if key_points else choices[index]
        ):
            return CheckResult(Verdict.CORRECT, matched_key_points=[0])
        return CheckResult(Verdict.INCORRECT, mistake_type=MistakeType.WRONG_DATA_STRUCTURE)

    # Several chosen: correct only if the whole intended set was picked.
    expected = {index for index, text in enumerate(choices) if any(
        matches_synonym(text, point) for point in key_points
    )}
    return CheckResult(
        Verdict.CORRECT if set(chosen) == expected and expected else Verdict.PARTIAL,
        matched_key_points=sorted(expected & set(chosen)),
        mistake_type=None if set(chosen) == expected else MistakeType.WRONG_DATA_STRUCTURE,
    )

def check_multi_choice(
    *, chosen: list[int] | None, choices: list[str] | None, key_points: list[str]
) -> CheckResult:
    if not choices:
        return CheckResult(Verdict.INCORRECT, mistake_type=MistakeType.OTHER)
    chosen_set = set(chosen or [])
    expected = {
        index
        for index, text in enumerate(choices)
        if any(matches_synonym(text, point) for point in key_points)
    }
    if not expected:
        return CheckResult(Verdict.PARTIAL)
    if chosen_set == expected:
        return CheckResult(Verdict.CORRECT, matched_key_points=sorted(expected))
    overlap = chosen_set & expected
    if overlap:
        return CheckResult(
            Verdict.PARTIAL,
            matched_key_points=sorted(overlap),
            mistake_type=MistakeType.MISSED_EDGE_CASE,
        )
    return CheckResult(Verdict.INCORRECT, mistake_type=MistakeType.WRONG_DATA_STRUCTURE)

def check_order_steps(
    *, order: list[int] | None, choices: list[str] | None, key_points: list[str]
) -> CheckResult:
    if not choices or not order:
        return CheckResult(Verdict.INCORRECT, mistake_type=MistakeType.OTHER)
    if sorted(order) != list(range(len(choices))):
        return CheckResult(Verdict.INCORRECT, mistake_type=MistakeType.WRONG_CONDITION)

# Canonical order is the order the choices were generated in. The rubric's key
# points are already listed in that order, so nothing needs inferring: an earlier
    # version sorted the key points *alphabetically* to recover the sequence, which
    # turned ["first", "then", "finally"] into the order [2, 0, 1] and marked
    # every correct answer wrong.
    canonical = list(range(len(choices)))

    if order == canonical:
        return CheckResult(Verdict.CORRECT)
    # Distance is the number of adjacent swaps needed, i.e. the inversion count.
    # Summing absolute displacements would score a single swap as 2 and call it
    # wrong, when swapping two neighbours really is one step away.
    inversions = sum(
        1
        for i in range(len(order))
        for j in range(i + 1, len(order))
        if order[i] > order[j]
    )
    if inversions <= 1:
        return CheckResult(Verdict.PARTIAL, mistake_type=MistakeType.OFF_BY_ONE)
    return CheckResult(Verdict.INCORRECT, mistake_type=MistakeType.WRONG_CONDITION)

def check_fill_blank(*, answer: str, key_points: list[str]) -> CheckResult:
    cleaned = normalise(answer)
    if not cleaned:
        return CheckResult(Verdict.INCORRECT, mistake_type=MistakeType.OTHER)
    matched = [
        index for index, point in enumerate(key_points) if matches_synonym(answer, point)
    ]
    if matched:
        return CheckResult(Verdict.CORRECT, matched_key_points=matched)
    # Not an exact hit, but the learner's wording covers one of the points:
    # partial with a nudge, never a flat "wrong".
    for index, point in enumerate(key_points):
        if coverage(answer, point) >= COVERAGE_PARTIAL:
            return CheckResult(
                Verdict.PARTIAL,
                matched_key_points=[index],
                mistake_type=MistakeType.MISUNDERSTOOD_GOAL,
            )
    return CheckResult(Verdict.INCORRECT, mistake_type=MistakeType.MISUNDERSTOOD_GOAL)

def check_predict_state(*, answer: str, expected_state: list[str]) -> CheckResult:
    """Compare a predicted window state against the one computed at generation."""
    cleaned = normalise(answer).replace(" ", "")
    for expected in expected_state:
        if normalise(expected).replace(" ", "") == cleaned:
            return CheckResult(Verdict.CORRECT)
    for expected in expected_state:
        if token_overlap(answer, expected) >= 0.5:
            return CheckResult(
                Verdict.PARTIAL, mistake_type=MistakeType.OFF_BY_ONE
            )
    return CheckResult(Verdict.INCORRECT, mistake_type=MistakeType.OFF_BY_ONE)

def deterministic_check(
    *,
    answer_type: str,
    answer: str,
    choice_indexes: list[int] | None,
    order: list[int] | None,
    choices: list[str] | None,
    key_points: list[str],
    expected_state: list[str] | None = None,
) -> CheckResult | None:
    """Return ``None`` when no deterministic check applies and the judge is needed."""
    if answer_type == AnswerType.SINGLE_CHOICE:
        return check_single_choice(chosen=choice_indexes, choices=choices, key_points=key_points)
    if answer_type == AnswerType.MULTI_CHOICE:
        return check_multi_choice(chosen=choice_indexes, choices=choices, key_points=key_points)
    if answer_type == AnswerType.ORDER_STEPS:
        return check_order_steps(order=order, choices=choices, key_points=key_points)
    if answer_type == AnswerType.FILL_BLANK:
        return check_fill_blank(answer=answer, key_points=key_points)
    if answer_type == AnswerType.PREDICT_STATE:
        return check_predict_state(answer=answer, expected_state=expected_state or [])
    return None

# -- nudges ---

_NUDGE_CORRECT = [
    "That's it. Hold on to that.",
    "Exactly right.",
    "Yes - that is the idea.",
]

_NUDGE_PARTIAL = {
    MistakeType.OFF_BY_ONE:
        "You are one step away. Count the positions again from the start.",
    MistakeType.WRONG_DATA_STRUCTURE:
        "Close. Ask what question you need to answer at each step, then pick the "
        "structure that answers it fastest.",
    MistakeType.MISSED_EDGE_CASE:
        "You have part of it. Think about what happens at the edges of the input.",
    MistakeType.WRONG_CONDITION:
        "You have the right pieces. When exactly do you check whether to keep going?",
    MistakeType.MISUNDERSTOOD_GOAL:
        "Think about what the problem actually asks for, before how to compute it.",
    MistakeType.COMPLEXITY_ISSUE:
        "Think about how many times each item is visited.",
}

_NUDGE_INCORRECT = {
    MistakeType.OFF_BY_ONE:
        "Start again from the first item and write down the state after each step. "
        "Where does your answer first differ from the problem's?",
    MistakeType.WRONG_DATA_STRUCTURE:
        "Ask what you need to know at each step. Then ask which structure answers "
        "that question in one step.",
    MistakeType.MISSED_EDGE_CASE:
        "What happens with the smallest possible input, and with the largest?",
    MistakeType.WRONG_CONDITION:
        "Describe in words when you would stop. Then turn that sentence into code.",
    MistakeType.MISUNDERSTOOD_GOAL:
        "Re-read the first sentence of the problem. What is it asking you to return?",
    MistakeType.COMPLEXITY_ISSUE:
        "How many times does your loop run for the largest allowed input?",
    MistakeType.OTHER:
        "Take one more pass. Write the smallest example and step through it by hand.",
}

def nudge_for(result: CheckResult, *, fallback: str = "") -> str:
    """Socratic feedback. Asks or points; never states the answer (§10.6)."""
    if result.verdict == Verdict.CORRECT:
        return _NUDGE_CORRECT[0]
    if result.verdict == Verdict.PARTIAL:
        return _NUDGE_PARTIAL.get(result.mistake_type or MistakeType.OTHER, fallback or
                                  "You are close. What part of the step are you sure about?")
    return _NUDGE_INCORRECT.get(result.mistake_type or MistakeType.OTHER, _NUDGE_INCORRECT[
        MistakeType.OTHER
    ])

def detail_to_key_points(detail: dict[str, Any] | None) -> list[str]:
    if not detail:
        return []
    rubric = detail.get("rubric") or {}
    points = rubric.get("key_points") or []
    return [str(point) for point in points]

def hint_level_for(hints_used: int) -> int:
    return min(3, max(0, hints_used) + 1)

def reveal_threshold(attempts: int, cap: int) -> bool:
    return attempts >= cap