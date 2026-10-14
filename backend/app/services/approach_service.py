"""Approach discovery (§8).

The pipeline is the hybrid from §8.1: local signals computed here, the model
restricted to a fixed vocabulary, then a **post-processor** that guarantees the
invariants the UI depends on. The post-processor is not a nicety - Brute Force
being present, the recommended approach being non-Brute-Force, and the list
being capped at four are product requirements that a model cannot be trusted to
satisfy on every call.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..ai import knowledge
from ..ai.prompts import approaches as approaches_prompt
from ..core.logging import get_logger
from ..schemas.models import Approach, ApproachesResponse, ApproachId
from ..services.generator import (
    ContentGenerator,
    GenerateRequest,
    build_system,
    schema_for,
)

logger = get_logger(__name__)

MAX_OPTIMIZED = 3

@dataclass
class LocalSignals:
    """Computed locally so the prompt starts from facts, not from vibes."""

    size_band: str
    dominant_bound: int | None
    keyword_hits: dict[str, int]
    tag_hits: dict[str, int]

    def as_prompt_lines(self) -> str:
        lines: list[str] = []
        bound = self.dominant_bound if self.dominant_bound else "unknown"
        lines.append(f"largest parsed input bound: {bound} (band: {self.size_band})")
        if self.tag_hits:
            top = sorted(self.tag_hits.items(), key=lambda kv: -kv[1])[:6]
            lines.append("tag signals: " + ", ".join(f"{name} x{count}" for name, count in top))
        if self.keyword_hits:
            top = sorted(self.keyword_hits.items(), key=lambda kv: -kv[1])[:6]
            lines.append("keyword signals: " + ", ".join(f"{name} x{count}" for name, count in top))
        return "\n".join(lines)

_TAG_TO_APPROACH: dict[str, tuple[str, ...]] = {
    "hash table": ("hash_map",),
    "array": ("two_pointers", "prefix_sum"),
    "string": ("two_pointers", "sliding_window"),
    "two pointers": ("two_pointers",),
    "sliding window": ("sliding_window",),
    "binary search": ("binary_search",),
    "dynamic programming": ("dynamic_programming",),
    "greedy": ("greedy",),
    "math": ("math",),
    "bit manipulation": ("bit_manipulation",),
    "heap": ("heap", "priority_queue"),
    "depth-first search": ("dfs", "backtracking"),
    "breadth-first search": ("bfs",),
    "graph": ("bfs", "union_find"),
    "tree": ("dfs",),
    "union find": ("union_find",),
    "stack": ("stack", "monotonic_stack"),
    "prefix sum": ("prefix_sum",),
    "sorting": ("sorting",),
    "trie": ("trie",),
    "backtracking": ("backtracking", "dfs"),
}

_KEYWORD_TO_APPROACH: dict[str, tuple[str, ...]] = {
    "subarray": ("sliding_window", "prefix_sum"),
    "substring": ("sliding_window", "two_pointers"),
    "contiguous": ("sliding_window",),
    "consecutive": ("sliding_window", "hash_map"),
    "shortest": ("two_pointers", "binary_search"),
    "longest": ("sliding_window", "two_pointers"),
    "distinct": ("hash_map", "sliding_window"),
    "duplicate": ("hash_map", "set"),
    "sorted": ("two_pointers", "binary_search"),
    "pairs": ("hash_map", "two_pointers"),
    "all combinations": ("backtracking",),
    "subsets": ("backtracking", "bit_manipulation"),
    "permutations": ("backtracking",),
    "path": ("dfs", "bfs"),
    "grid": ("dfs", "bfs"),
    "matrix": ("prefix_sum", "union_find"),
    "interval": ("sorting", "heap"),
    "overlap": ("intervals", "sorting"),
    "frequency": ("hash_map",),
    "sum of subarray": ("prefix_sum",),
    "fibonacci": ("dynamic_programming", "recursion"),
}

def compute_signals(problem: dict[str, Any]) -> LocalSignals:
    bounds = problem.get("constraint_bounds") or []
    dominant = None
    for bound in bounds:
        value = bound.get("max") if isinstance(bound, dict) else None
        if value and (dominant is None or value > dominant):
            dominant = int(value)

    band = "unknown"
    if dominant is not None:
        if dominant <= 20:
            band = "tiny"
        elif dominant <= 1_000:
            band = "small"
        elif dominant <= 100_000:
            band = "medium"
        else:
            band = "large"

    tag_hits: dict[str, int] = {}
    for tag in problem.get("tags") or []:
        for needle, approaches in _TAG_TO_APPROACH.items():
            if needle in str(tag).lower():
                for approach in approaches:
                    tag_hits[approach] = tag_hits.get(approach, 0) + 1

    text = " ".join(
        [
            str(problem.get("statement_text", "")),
            str(problem.get("title", "")),
        ]
    ).lower()

    keyword_hits: dict[str, int] = {}
    for needle, approaches in _KEYWORD_TO_APPROACH.items():
        if needle in text:
            for approach in approaches:
                keyword_hits[approach] = keyword_hits.get(approach, 0) + 1

    return LocalSignals(
        size_band=band,
        dominant_bound=dominant,
        keyword_hits=keyword_hits,
        tag_hits=tag_hits,
    )

def post_process(raw: dict[str, Any]) -> ApproachesResponse:
    """Enforce the invariants the approach list depends on (§8.2)."""
    entries: list[Approach] = []
    seen: set[str] = set()

    for item in raw.get("approaches", []) or []:
        if not isinstance(item, dict):
            continue
        identifier = str(item.get("id", ""))
        if identifier not in {a.value for a in ApproachId} or identifier in seen:
            continue  # drop ids outside the enum
        try:
            approach = Approach.model_validate(item)
        except Exception as exc:
            # Dropping a malformed approach is the right call - one bad entry must
            # not cost the learner the whole list - but never silently: a shape
            # regression in the prompt would otherwise look like a shorter menu.
            logger.info("dropping malformed approach %s: %s", identifier, exc)
            continue
        if approach.expected_complexity is None:
            approach.expected_complexity = None
        seen.add(identifier)
        entries.append(approach)

    # Brute Force is guaranteed present exactly once.
    if "brute_force" not in seen:
        entries.append(
            Approach(
                id=ApproachId.BRUTE_FORCE,
                name="Brute Force",
                confidence=0.5,
                simple_reason="Try every possibility first. This is the baseline you "
                "compare against.",
                when_to_use="Use this to understand the problem before you optimise it.",
                difficulty_for_beginner="easy",
                expected_complexity=None,
            )
        )

    brute = next((a for a in entries if a.id == ApproachId.BRUTE_FORCE), None)
    optimized = [a for a in entries if a.id != ApproachId.BRUTE_FORCE]
    optimized.sort(key=lambda a: -a.confidence)
    optimized = optimized[:MAX_OPTIMIZED]

    ordered = ([brute] if brute else []) + optimized

    # Recommended is the best non-Brute-Force option, unless there is only one.
    recommended = ordered[1] if len(ordered) > 1 else ordered[0]

    return ApproachesResponse(
        problem_type=str(raw.get("problem_type") or "algorithm problem")[:120],
        target_complexity_hint=(
            str(raw.get("target_complexity_hint"))[:40]
            if raw.get("target_complexity_hint")
            else None
        ),
        approaches=ordered,
        recommended_first=recommended.id,
    )

class ApproachService:
    task_id = "approaches.v1"

    def __init__(self, generator: ContentGenerator) -> None:
        self.generator = generator

    async def list_approaches(
        self, problem: dict[str, Any], *, client_ip: str | None = None
    ) -> ApproachesResponse:
        signals = compute_signals(problem)
        allowed = [a.value for a in ApproachId]

        # Signals first: the model should read the constraints before it is told
        # what to produce.
        user = (
            f"<local_signals>\n{signals.as_prompt_lines()}\n</local_signals>\n\n"
            + approaches_prompt(problem, allowed_ids=allowed)
        )

        request = GenerateRequest(
            task_id=self.task_id,
            slug=str(problem.get("slug", "")),
            statement_text=str(problem.get("statement_text", "")),
            constraints_text=str(problem.get("constraints_text", "")),
            approach_id="",
            language="en",
            mode="beginner",
            schema=schema_for(ApproachesResponse),
            adapter=ApproachesResponse.model_validate,
            tier="balanced",
            temperature=0.2,
            max_tokens=900,
            deadline_s=15.0,
        )
        outcome = await self.generator.generate(
            request,
            system=build_system(language="en", mode="beginner"),
            user=user,
            client_ip=client_ip,
        )
        return post_process(_as_dict(outcome.payload))

def _as_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    dumped: dict[str, Any] = payload.model_dump(by_alias=True)
    return dumped

__all__ = [
    "ApproachService",
    "LocalSignals",
    "compute_signals",
    "knowledge",
    "post_process",
]