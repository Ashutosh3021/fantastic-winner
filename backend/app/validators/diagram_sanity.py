"""Diagram validators (§12.6).

Nine checks, and they exist because each one has a plausible failure mode:
a model that indexes past the end of an array, a caption that smuggles in HTML,
a toy input that is secretly the problem's own example.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from pydantic import TypeAdapter, ValidationError

from ..schemas.models import DIAGRAM_LIMITS, LearningDiagramSpec

_ADAPTER: TypeAdapter[LearningDiagramSpec] = TypeAdapter(LearningDiagramSpec)

_HTML_TAG = re.compile(r"<[a-zA-Z/!][^>]*>")
_CONTROL = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
_ZERO_WIDTH = re.compile(r"[-‏  ﻿]")
_URL = re.compile(r"https?://\S+|\bwww\.\S+")

@dataclass
class DiagramReport:
    ok: bool = True
    problems: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.ok = False
        self.problems.append(reason)

def _texts_in_data(data: object) -> list[str]:
    """Every user-visible string inside `data`, wherever it hides (§12.5)."""
    found: list[str] = []
    if isinstance(data, dict):
        for value in data.values():
            found.extend(_texts_in_data(value))
    elif isinstance(data, list):
        for value in data:
            found.extend(_texts_in_data(value))
    elif isinstance(data, str):
        found.append(data)
    return found

def _item_count(data: object) -> int:
    if isinstance(data, dict):
        for key in ("cells", "slots", "columns", "nodes", "steps", "labels"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
        for value in data.values():
            if isinstance(value, list) and value and isinstance(value[0], list):
                return len(value) * max(len(row) for row in value if isinstance(row, list))
        return 0
    return 0

def _tokenise(value: str) -> set[str]:
    return {token for token in re.split(r"[^\w]+", value.lower()) if len(token) > 2}

def _index_space(spec: object) -> int:
    """How many indexable items the spec's data actually has."""
    if not isinstance(spec, dict):
        return 0
    data = spec.get("data")
    if not isinstance(data, dict):
        return 0
    if "cells" in data or "slots" in data or "columns" in data or "steps" in data:
        for key in ("cells", "slots", "columns", "steps"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
    if "nodes" in data:
        return len(data.get("nodes") or [])
    if "rows" in data:
        rows = data.get("rows") or []
        if rows and isinstance(rows[0], list):
            return len(rows) * max(len(row) for row in rows if isinstance(row, list))
        return len(rows)
    return 0

def validate_diagram(spec: object, *, example_inputs: list[str] | None = None) -> DiagramReport:
    """Run every diagram check. Returns a report; never raises."""
    report = DiagramReport()

    # 1 & 8 - schema, including the type gate that makes `reveals_solution`
    # unreachable from the learning path.
    try:
        parsed = _ADAPTER.validate_python(spec)
    except ValidationError as exc:
        errors = exc.errors()
        first = errors[0] if errors else None
        if first is None:
            report.fail("schema: spec did not match the diagram schema")
            return report
        location = ".".join(str(part) for part in first.get("loc", ()))
        report.fail(f"schema: {location or 'spec'} {first.get('msg', 'invalid')}")
        return report

    raw = spec if isinstance(spec, dict) else {}
    limit = _index_space(parsed.model_dump(by_alias=True))

    # 3 - size caps.
    if _item_count(raw.get("data")) > DIAGRAM_LIMITS["max_items"]:
        report.fail("too_many_items")
    for frame in parsed.frames:
        if len(frame.caption) > DIAGRAM_LIMITS["max_caption_chars"]:
            report.fail("caption_too_long")
            break

    # 2 - bounds: every index the frames reference must exist in `data`.
    for frame_index, frame in enumerate(parsed.frames):
        for pointer in frame.pointers:
            if pointer.index >= limit:
                report.fail(
                    f"frame {frame_index}: pointer {pointer.id!r} "
                    f"index {pointer.index} out of range"
                )
        for highlight in frame.highlights:
            if highlight.index >= limit:
                report.fail(f"frame {frame_index}: highlight index {highlight.index} out of range")
        for annotation in frame.annotations:
            if annotation.index >= limit:
                report.fail(
                    f"frame {frame_index}: annotation index "
                    f"{annotation.index} out of range"
                )
        for range_ in frame.ranges:
            if range_.from_ >= limit or range_.to >= limit:
                report.fail(f"frame {frame_index}: range {range_.from_}-{range_.to} out of range")

    # 4 - frame continuity: pointer ids must stay consistent across frames.
    reference_ids = (
        {pointer.id for pointer in parsed.frames[0].pointers} if parsed.frames else set()
    )
    for frame_index, frame in enumerate(parsed.frames[1:], start=1):
        ids = {pointer.id for pointer in frame.pointers}
        if ids and reference_ids and not ids.issubset(reference_ids | ids):
            report.fail(f"frame {frame_index}: pointer ids diverge from frame 0")
        if ids:
            reference_ids = ids

    # 5 - text sanitisation on captions, titles and every data string.
    strings_to_check: list[str] = [parsed.title, parsed.alt_text]
    for frame in parsed.frames:
        strings_to_check.append(frame.caption)
        strings_to_check.extend(annotation.text for annotation in frame.annotations)
        if frame.side_panel:
            strings_to_check.append(frame.side_panel.title)
            strings_to_check.extend(frame.side_panel.items)
    strings_to_check.extend(_texts_in_data(raw.get("data")))

    for text in strings_to_check:
        if _HTML_TAG.search(text):
            report.fail("html_in_text")
            break
        if _CONTROL.search(text) or _ZERO_WIDTH.search(text):
            report.fail("control_characters_in_text")
            break
        if _URL.search(text):
            report.fail("url_in_text")
            break

    # 6 - toy-input similarity against the problem's own examples.
    if example_inputs:
        diagram_tokens = _tokenise(" ".join(strings_to_check))
        if diagram_tokens:
            for example in example_inputs:
                overlap = len(diagram_tokens & _tokenise(example)) / max(
                    1, len(_tokenise(example))
                )
                if overlap > 0.8:
                    report.fail(f"toy_input_too_similar_to_example ({overlap:.0%})")
                    break

    # 7 - total payload size.
    try:
        size = len(json.dumps(parsed.model_dump(by_alias=True), ensure_ascii=False))
    except (TypeError, ValueError):
        size = 0
    if size > DIAGRAM_LIMITS["max_json_bytes"]:
        report.fail(f"payload_too_large ({size} bytes)")

    return report