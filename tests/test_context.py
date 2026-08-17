"""Unit tests for chat context assembly."""

from app.graphs.context import (
    DEFAULT_SYSTEM_PROMPT,
    STORY_BIBLE_PRIMER,
    ContextAssembler,
    compose_story_bible_system_prompt,
)


def test_context_assembler_returns_base_prompt_by_default() -> None:
    assert ContextAssembler().system_prompt == DEFAULT_SYSTEM_PROMPT


def test_context_assembler_allows_custom_base_prompt() -> None:
    assembler = ContextAssembler(base_prompt="Base prompt.")

    assert assembler.system_prompt == "Base prompt."


def test_context_assembler_allows_explicit_system_prompt_override() -> None:
    assembler = ContextAssembler(system_prompt="Override prompt.")

    assert assembler.system_prompt == "Override prompt."


def test_default_system_prompt_embeds_story_bible_primer() -> None:
    assert STORY_BIBLE_PRIMER in DEFAULT_SYSTEM_PROMPT
    assert "Scene tools:" in DEFAULT_SYSTEM_PROMPT
    assert "read_story_bible" in DEFAULT_SYSTEM_PROMPT
    assert "read_world_state" in DEFAULT_SYSTEM_PROMPT
    assert "read_character_arc" in DEFAULT_SYSTEM_PROMPT


def test_story_bible_primer_covers_bible_parts() -> None:
    primer = STORY_BIBLE_PRIMER.lower()
    assert "narrative style" in primer
    assert "world facts" in primer
    assert "event-sourced" in primer
    assert "signals" in primer
    assert "identity" in primer
    assert "intimacies" in primer
    assert "minor" in primer
    assert "major" in primer
    assert "defining" in primer
    assert "derived state" in primer
    assert "timeline" in primer


def test_compose_story_bible_system_prompt_joins_usage() -> None:
    composed = compose_story_bible_system_prompt("Use intimacies, strength-weighted.")

    assert composed.startswith(STORY_BIBLE_PRIMER)
    assert composed.endswith("Use intimacies, strength-weighted.")
    assert "\n\nUse intimacies, strength-weighted." in composed
