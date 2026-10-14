"""Static complexity facts (§13.1.2 step 2).

A deterministic pass that reports only what is *syntactically observable* -
nesting depth, recursion, sorting, hash structures - and never guesses the
complexity class. The AI estimate is then reconciled against it, and a
disagreement larger than one step sets ``confidence: low`` rather than
averaging the two opinions into something neither of them said.

For Python this uses the stdlib ``ast``, which is exact. For other languages it
falls back to a brace/indent-aware line scan, which is approximate - and says
so, by reporting ``method: "heuristic"`` so the caller can discount it.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from typing import Any

_HASH_NAMES = {"set", "dict", "map", "hashset", "hashmap", "object"}

@dataclass
class StaticFacts:
    language: str
    method: str  # "ast" | "heuristic" | "unavailable"
    max_loop_depth: int = 0
    recurses: bool = False
    memoised_recursion: bool = False
    sorts: bool = False
    uses_hash_structure: bool = False
    line_count: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "method": self.method,
            "max_loop_depth": self.max_loop_depth,
            "recurses": self.recurses,
            "memoised_recursion": self.memoised_recursion,
            "sorts": self.sorts,
            "uses_hash_structure": self.uses_hash_structure,
            "line_count": self.line_count,
        }

_LOOP_NODES = (ast.For, ast.AsyncFor, ast.While)
_HASH_CALLS = {"set", "dict", "Counter", "defaultdict", "deque"}
_SORT_CALLS = {"sort", "sorted", "sort_values", "sortBy"}
_MEMO_MARKERS = ("cache", "memo", "lru_cache", "@cache", "tabulation")

def _is_hash_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id in _HASH_CALLS
    return isinstance(func, ast.Attribute) and func.attr in _HASH_NAMES

def _function_facts(tree: ast.AST) -> StaticFacts:
    facts = StaticFacts(language="python", method="ast")

    def walk(node: ast.AST, depth: int, inside_function: bool) -> None:
        if isinstance(node, _LOOP_NODES):
            facts.max_loop_depth = max(facts.max_loop_depth, depth + 1)
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
            if name in _SORT_CALLS:
                facts.sorts = True
            if _is_hash_call(node):
                facts.uses_hash_structure = True
        for child in ast.iter_child_nodes(node):
            walk(child, depth + 1 if isinstance(node, _LOOP_NODES) else depth, inside_function)

    def visit(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            facts.recurses = any(
                isinstance(child, ast.Call)
                and getattr(child.func, "id", "") == node.name
                for child in ast.walk(node)
            )
            if facts.recurses:
                decorated = [getattr(d, "id", getattr(d, "attr", "")) for d in node.decorator_list]
                source = ast.dump(node)
                facts.memoised_recursion = any(
                    marker in source or marker in " ".join(str(d) for d in decorated)
                    for marker in _MEMO_MARKERS
                )
        walk(node, 0, isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)))
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return facts

_BRACE_LOOP = re.compile(r"\b(for|while)\b")
_BRACE_OPEN = re.compile(r"[{\[(]")
_BRACE_CLOSE = re.compile(r"[}\])]")

def _heuristic_facts(code: str, language: str) -> StaticFacts:
    facts = StaticFacts(language=language, method="heuristic")
    depth = 0
    best = 0

    for raw in code.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "//", "*", "/*")):
            continue

        opens = len(_BRACE_OPEN.findall(line))
        closes = len(_BRACE_CLOSE.findall(line))
        if _BRACE_LOOP.search(line):
            facts.max_loop_depth = max(facts.max_loop_depth, depth + 1)
        depth = max(0, depth + opens - closes)
        best = max(best, depth)

        if re.search(r"\b(set|new Set|new Map|unordered_map|dict)\s*[(\[<]", line):
            facts.uses_hash_structure = True
        if re.search(r"\b(sorted|sort|\.sort\()", line):
            facts.sorts = True

    facts.recurses = bool(re.search(r"\b([A-Za-z_]\w*)\s*\([^)]*\)\s*\{[^}]*\1\s*\(", code))
    facts.memoised_recursion = bool(
        re.search(r"@cache|@lru_cache|memo\.|memo\[", code)
    )
    if facts.recurses and not facts.memoised_recursion:
        facts.notes.append("recursion without a visible memo table")
    del best
    return facts

def analyse(code: str, *, language: str) -> StaticFacts:
    """Observable structural facts. Never throws."""
    if not code or not code.strip():
        return StaticFacts(language=language, method="unavailable")

    if language.startswith("python"):
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            facts = _heuristic_facts(code, language)
            facts.notes.append(f"python parse failed at line {exc.lineno}; used the line scan")
            return facts
        facts = _function_facts(tree)
        facts.line_count = len(code.splitlines())
        return facts

    facts = _heuristic_facts(code, language)
    facts.line_count = len(code.splitlines())
    return facts

# : Ordered coarsest-to-finest, used to measure "differ by more than one step".
_ORDER = [
    "O(1)",
    "O(log n)",
    "O(n)",
    "O(n log n)",
    "O(n^2)",
    "O(n^3)",
    "O(2^n)",
    "O(n!)",
]

def _rank(label: str) -> int:
    try:
        return _ORDER.index(label)
    except ValueError:
        return 2  # unknown forms are treated as linear, and noted as such

def reconcile(
    *, ai_class: str, facts: StaticFacts
) -> tuple[str, str, bool]:
    """Return ``(class, confidence, estimated)``.

    ``estimated`` means the two passes disagreed by more than one step, in which
    case the UI says so rather than presenting a number it is not sure of
    (§13.1.2).
    """
    ai_rank = _rank(ai_class)
    facts_rank = _infer_from_structure(facts)
    delta = abs(ai_rank - facts_rank)

    if delta > 1:
        return ai_class, "low", True
    if facts.method == "unavailable":
        return ai_class, "low", False
    if delta == 0:
        return ai_class, "high", False
    return ai_class, "medium", False

def _infer_from_structure(facts: StaticFacts) -> int:
    """A deliberately coarse floor from structure alone."""
    depth = facts.max_loop_depth
    if facts.recurses and not facts.memoised_recursion:
        return _ORDER.index("O(2^n)")
    if depth >= 3:
        return _ORDER.index("O(n^3)")
    if depth == 2:
        return _ORDER.index("O(n^2)")
    if depth == 1:
        if facts.sorts:
            return _ORDER.index("O(n log n)")
        return _ORDER.index("O(n)")
    if facts.sorts:
        return _ORDER.index("O(log n)")
    return _ORDER.index("O(1)")