import functools
import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = Path(__file__).parent

# : A curated entry must have these keys. A missing one is a content bug that
# : would silently degrade a question, so it is loud rather than default.
_REQUIRED = ("id", "core_idea", "fallback_nudges", "fallback_step_notes")

@functools.lru_cache(maxsize=1)
def load_all() -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(KNOWLEDGE_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        entry_id = data.get("id") or path.stem
        missing = [key for key in _REQUIRED if not data.get(key)]
        if missing:
            # A knowledge entry without fallback content breaks -10.3 and -10.8,
            # which both promise the learner a question is never unanswerable.
            logger.error(
                "knowledge entry %s is missing %s; lazy-detail fallbacks are mandatory",
                entry_id,
                ", ".join(missing),
            )
            continue
        entries[str(entry_id)] = data
    return entries

def get(approach_id: str) -> dict[str, Any] | None:
    return load_all().get(approach_id)

def grounding_for(approach_id: str) -> str:
    """Render the grounding block that goes into a prompt (§15.4).

    Returns a short, explicit note when an approach has no curated entry: the
    model is told the gap rather than being left to invent the technique.
    """
    entry = get(approach_id)
    if entry is None:
        return (
            f"No curated grounding is available for '{approach_id}'. Rely on the problem "
            "text alone and keep the explanation at the level of the technique itself."
        )

    lines = [
        f"Technique: {entry.get('name', approach_id)}",
        f"Core idea: {' '.join(str(entry.get('core_idea', '')).split())}",
    ]
    signals = entry.get("signals") or []
    if signals:
        lines.append("It fits when: " + "; ".join(str(s) for s in signals[:5]) + ".")
    not_when = entry.get("not_when") or []
    if not_when:
        lines.append("It does not fit when: " + "; ".join(str(s) for s in not_when[:3]) + ".")
    mistakes = entry.get("common_beginner_mistakes") or []
    if mistakes:
        lines.append("Beginners commonly: " + "; ".join(str(s) for s in mistakes[:4]) + ".")
    steps = entry.get("typical_micro_steps") or []
    if steps:
        lines.append("Teaching steps, in order: " + "; ".join(str(s) for s in steps) + ".")
    return "\n".join(lines)

def fallback_nudges(approach_id: str, *, limit: int = 3) -> list[str]:
    entry = get(approach_id)
    if not entry:
        return [
            "Re-read the question and name, in one sentence, what the problem hands you.",
            "Ask yourself what the answer looks like before you ask how to compute it.",
        ]
    return [str(s) for s in (entry.get("fallback_nudges") or [])][:limit]

def fallback_step_notes(approach_id: str, *, limit: int = 4) -> list[str]:
    entry = get(approach_id)
    if not entry:
        return [
            "This step is about one idea at a time. Restate it in your own words before moving on.",
        ]
    return [str(s) for s in (entry.get("fallback_step_notes") or [])][:limit]

def analogy_seeds(approach_id: str, *, limit: int = 3) -> list[str]:
    entry = get(approach_id)
    if not entry:
        return []
    return [str(s) for s in (entry.get("analogy_seeds") or [])][:limit]

def known_approaches() -> set[str]:
    return set(load_all())

def validate_entries() -> list[str]:
    """Returns problems found; empty list means the library is healthy.

    Run in CI, because a broken grounding library degrades quality quietly: the
    system still works, it just teaches more generically than intended.
    """
    problems: list[str] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            problems.append(f"{path.name}: not valid YAML ({exc})")
            continue
        for key in _REQUIRED:
            if not data.get(key):
                problems.append(f"{path.name}: missing {key}")
    return problems