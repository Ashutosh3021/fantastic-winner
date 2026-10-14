"""The leak detector (§11.4).

Design note, because this is where a well-meant change does real damage: the
v1 detector flagged individual language keywords - ``def``, ``class Solution``,
``for (``, ``return``. That heuristic cannot ship alongside Hindi and Odia.
PLAN §9.4 requires technical terms to stay English in translated content, so a
perfectly good Odia concept card contains the word ``return``. Each false
positive costs a full regeneration of a *heavy* call, and two failures return a
503 with no content at all - which breaks cost survivability and makes a
legitimate card undeliverable.

So the checks are scoped to **code structure**, not to words:

* a fenced code block
* LeetCode template tokens
* a code-structure signature (assignments, calls, returns and loop keywords
  clustered inside a two-line window, with indentation or brace consistency)
* an indented-block run
* numbered imperative pseudo-code, ``en`` only
* a URL

Every one of these is language-independent. The word ``return`` on its own is
prose. A line that looks like ``return left`` next to a line that looks like
``left = 0`` inside an indented block is code, in any surrounding language.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# -- unambiguous, language-independent signals ---

_FENCED_BLOCK = re.compile(r"```", re.MULTILINE)

# : Tokens that appear in LeetCode's own template, so they are never prose.
TEMPLATE_TOKENS = (
    "class Solution",
    "class Solution(object)",
    "def maxSubArray(self, nums:",
    "public class Solution",
    "func maxSubArray(nums []int)",
    "var maxSubArray = function(nums) {",
    "#include <bits/stdc++.h>",
    "from typing import List",
    "Solution().maxSubArray",
)

_URL = re.compile(r"https?://\S+|\bwww\.\S+")

# -- structural signals ---

# : Operations that, clustered together, read as a program rather than prose.
_ASSIGNMENT = re.compile(r"^\s*[\w.\[\]]+\s*(?:=|\+=|-=|\*=|/=)[^=]")
_CALL = re.compile(r"\b\w+\s*\([^)]*\)")
_RETURN = re.compile(r"^\s*return\b", re.IGNORECASE)
_LOOP_KEYWORD = re.compile(
    r"^\s*(?:for|while|foreach)\b|^\s*(?:if|elif)\b.*:\s*$", re.IGNORECASE
)
_DEF = re.compile(r"^\s*(?:def|function|func|fn)\s+\w+", re.IGNORECASE)

# : A line is "code-shaped" when it carries at least one strong operator.
_STRONG_OPERATOR = re.compile(
    r"(?:[;{}]\s*$)|(?:^\s*(?:return|def|function|func|fn)\b)|(?:=>)|(?:::\s*$)"
)

_INDENT = re.compile(r"^(?: {2,}|\t)")

@dataclass(frozen=True)
class LeakFinding:
    check: str
    detail: str
    excerpt: str = ""

@dataclass
class LeakReport:
    findings: list[LeakFinding] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.findings

    def reasons(self) -> list[str]:
        return [f"{f.check}: {f.detail}" for f in self.findings]

def normalise(text: str) -> str:
    """NFKC + invisible-character removal, so lookalikes cannot hide a signal."""
    stripped = "".join(
        ch for ch in text if unicodedata.category(ch) != "Cf" and ch not in "\x00"
    )
    return unicodedata.normalize("NFKC", stripped)

def _excerpt(lines: list[str], index: int, span: int = 2) -> str:
    lo = max(0, index - span)
    hi = min(len(lines), index + span + 1)
    return "\n".join(lines[lo:hi]).strip()[:240]

def _check_fenced_block(text: str, report: LeakReport) -> None:
    match = _FENCED_BLOCK.search(text)
    if match:
        report.findings.append(
            LeakFinding(
                "fenced_code_block",
                "output contains a fenced code block",
                match.group(0),
            )
        )

def _check_template_tokens(text: str, report: LeakReport) -> None:
    for token in TEMPLATE_TOKENS:
        if token in text:
            report.findings.append(
                LeakFinding("template_token", f"output contains {token!r}", token)
            )

def _check_urls(text: str, report: LeakReport) -> None:
    match = _URL.search(text)
    if match:
        report.findings.append(LeakFinding("url", "output contains a URL", match.group(0)))

def _code_shape_score(line: str) -> int:
    score = 0
    if _ASSIGNMENT.match(line):
        score += 1
    if _RETURN.match(line):
        score += 1
    if _LOOP_KEYWORD.match(line):
        score += 1
    if _DEF.match(line):
        score += 2
    if _CALL.search(line):
        score += 1
    if _INDENT.match(line):
        # Leading indentation is the signal that survives on an unfenced code
        # block, which models emit often enough to matter. Prose is not indented,
        # and an indented markdown bullet carries no assignment, call or return
        # to pair with it, so this adds no false positives of its own.
        score += 1
    return score

def _check_code_structure(text: str, report: LeakReport) -> None:
    """Two or more code-shaped lines inside a two-line window, with a body."""
    lines = text.splitlines()
    for index in range(len(lines)):
        window = lines[index : index + 3]
        if sum(1 for line in window if _code_shape_score(line) >= 2) < 2:
            continue
        # Structure needs a body: either indentation or a brace/semicolon shape.
        has_body = any(_INDENT.match(line) for line in window) or any(
            _STRONG_OPERATOR.search(line) for line in window
        )
        if has_body:
            report.findings.append(
                LeakFinding(
                    "code_structure",
                    "a run of lines reads as a program, not as prose",
                    _excerpt(lines, index),
                )
            )
            return

def _check_indented_run(text: str, report: LeakReport) -> None:
    """Three or more consecutive indented lines.

    This is the check most likely to touch prose, so it only fires when the
    lines also carry code markers. An indented bulleted paragraph in an Odia
    card does not.
    """
    lines = text.splitlines()
    run = 0
    for index, line in enumerate(lines):
        if not line.strip():
            run = 0
            continue
        indented = bool(_INDENT.match(line))
        marked = bool(_STRONG_OPERATOR.search(line)) or _code_shape_score(line) >= 2
        if indented and marked:
            run += 1
            if run >= 3:
                report.findings.append(
                    LeakFinding(
                        "indented_block_run",
                        "three or more consecutive lines form an indented code block",
                        _excerpt(lines, index),
                    )
                )
                return
        else:
            run = 0

_STEP_LINE = re.compile(
    r"^\s*(?:step\s*\d+\s*[:.)-]|step\s+\d+\b|\d+\s*[).]\s+\w+\s+\w+)",
    re.IGNORECASE,
)
_STEP_OPERATION = re.compile(
    r"\b(move|set|increment|decrement|append|return|loop|iterate|update|assign|"
    r"shift|grow|shrink|insert|remove|start|end|stop|mark|track|store|check|"
    r"compare|swap|extend|advance)\b",
    re.IGNORECASE,
)

def _check_imperative_pseudocode(text: str, report: LeakReport, *, language: str) -> None:
    """More than four consecutive "step N:" lines naming operations, in order.

    Scoped to English: this check is a language assumption, not a structural one,
    so it must not be applied to content it was never designed for.
    """
    if language != "en":
        return
    lines = text.splitlines()
    run = 0
    for index, line in enumerate(lines):
        if _STEP_LINE.match(line) and _STEP_OPERATION.search(line):
            run += 1
            if run > 4:
                report.findings.append(
                    LeakFinding(
                        "imperative_pseudocode",
                        "five or more numbered steps name operations in execution order, "
                        "which is the algorithm itself",
                        _excerpt(lines, index),
                    )
                )
                return
        else:
            run = 0

def detect_leaks(text: str, *, language: str = "en") -> LeakReport:
    """Run every applicable check. Returns a report; never raises."""
    report = LeakReport()
    if not text:
        return report

    cleaned = normalise(text)
    _check_fenced_block(cleaned, report)
    _check_template_tokens(cleaned, report)
    _check_urls(cleaned, report)
    _check_code_structure(cleaned, report)
    _check_indented_run(cleaned, report)
    _check_imperative_pseudocode(cleaned, report, language=language)
    return report

def contains_code(text: str) -> bool:
    """The code-only check that runs for *every* policy, `EARNED` included (§11.2)."""
    report = detect_leaks(text)
    return any(
        finding.check in ("fenced_code_block", "template_token", "code_structure")
        for finding in report.findings
    )

# -- the STRICT-only check: is this a complete algorithm? ---

_ALGORITHM_MARKERS = (
    re.compile(r"\bfirst,?\b.{0,80}\bthen\b.{0,80}\bfinally\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"^\s*1[.)]\s+\w+.{0,120}2[.)]\s+\w+", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bin this order\b|\bin exactly this order\b", re.IGNORECASE),
    re.compile(r"\bfollow these steps exactly\b", re.IGNORECASE),
    re.compile(r"\bfull (?:solution|algorithm)\b", re.IGNORECASE),
    re.compile(r"\bcomplete (?:solution|algorithm)\b", re.IGNORECASE),
    re.compile(r"\bpseudo-?code\b", re.IGNORECASE),
)

def is_complete_algorithm(text: str) -> bool:
    """Does this text specify the *whole* algorithm rather than one idea?

    Only meaningful under `STRICT`. `STEP_SCOPED` and `EARNED` artifacts are
    exempt - at the moment they become visible the learner has already produced
    the algorithm as their own answers, which is the entire justification
    (§11.2).
    """
    cleaned = normalise(text)
    return any(pattern.search(cleaned) for pattern in _ALGORITHM_MARKERS)