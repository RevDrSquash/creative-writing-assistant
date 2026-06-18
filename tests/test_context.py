"""Unit tests for chat context assembly."""

from app.graphs.context import DEFAULT_SYSTEM_PROMPT, ContextAssembler


def test_context_assembler_returns_base_prompt_by_default() -> None:
    assert ContextAssembler().system_prompt == DEFAULT_SYSTEM_PROMPT


def test_context_assembler_allows_custom_base_prompt() -> None:
    assembler = ContextAssembler(base_prompt="Base prompt.")

    assert assembler.system_prompt == "Base prompt."


def test_context_assembler_allows_explicit_system_prompt_override() -> None:
    assembler = ContextAssembler(system_prompt="Override prompt.")

    assert assembler.system_prompt == "Override prompt."
