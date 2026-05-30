"""Unit tests for chat context assembly."""

from app.graphs.context import DEFAULT_SYSTEM_PROMPT, ContextAssembler


def test_context_assembler_composes_prefix_and_base_prompt() -> None:
    assembler = ContextAssembler(prefix="Use a noir voice.", base_prompt="Base prompt.")

    assert assembler.system_prompt == "Use a noir voice.\n\nBase prompt."


def test_context_assembler_omits_empty_prefix() -> None:
    assert ContextAssembler().system_prompt == DEFAULT_SYSTEM_PROMPT


def test_context_assembler_allows_explicit_system_prompt_override() -> None:
    assembler = ContextAssembler(prefix="Ignored", system_prompt="Override prompt.")

    assert assembler.system_prompt == "Override prompt."
