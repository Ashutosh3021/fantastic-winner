"""The grounded teaching library.

A malformed content file used to raise inside ``grounding_for``, so a concept
card 500'd before any model call. These tests keep that from shipping again.
"""

from __future__ import annotations

from pathlib import Path

from app.ai import knowledge


def test_every_shipped_entry_parses_and_has_required_content() -> None:
    assert knowledge.validate_entries() == []


def test_known_approach_renders_grounding() -> None:
    text = knowledge.grounding_for("sliding_window")

    assert "Sliding Window" in text
    assert "window" in text.lower()
    assert "No curated grounding" not in text


def test_unknown_approach_degrades_instead_of_raising() -> None:
    text = knowledge.grounding_for("not_a_real_approach")

    assert "No curated grounding" in text


def test_a_broken_file_is_skipped_not_fatal(
    monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / "broken.yaml").write_text(
        "id: broken\nsignals:\n  - \"longest\", \"shortest\"\n", encoding="utf-8"
    )
    (tmp_path / "good.yaml").write_text(
        "id: good\ncore_idea: keep it simple\n"
        "fallback_nudges:\n  - reread\nfallback_step_notes:\n  - one step\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(knowledge, "KNOWLEDGE_DIR", tmp_path)
    knowledge.load_all.cache_clear()

    try:
        loaded = knowledge.load_all()
    finally:
        knowledge.load_all.cache_clear()

    assert "good" in loaded
    assert "broken" not in loaded
