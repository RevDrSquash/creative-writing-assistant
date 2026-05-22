"""Unit tests for Phase 2 chat context assembly."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graphs.context import ContextAssembler


def test_assemble_empty_history_adds_system_prompt() -> None:
    assembler = ContextAssembler(system_prompt="System instructions")

    messages = assembler.assemble([])

    assert len(messages) == 1
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == "System instructions"


def test_assemble_preserves_chat_history_order() -> None:
    assembler = ContextAssembler(system_prompt="System instructions")
    history = [HumanMessage(content="Hello"), AIMessage(content="Hi there")]

    messages = assembler.assemble(history)

    assert [type(message) for message in messages] == [SystemMessage, HumanMessage, AIMessage]
    assert [message.content for message in messages] == [
        "System instructions",
        "Hello",
        "Hi there",
    ]


def test_storage_round_trip_preserves_roles_and_content() -> None:
    assembler = ContextAssembler()
    stored_messages = [
        {"role": "user", "content": "Draft a scene."},
        {"role": "assistant", "content": "Here is a scene."},
    ]

    messages = assembler.from_storage(stored_messages)

    assert assembler.to_storage(messages) == stored_messages


def test_from_storage_rejects_unknown_roles() -> None:
    assembler = ContextAssembler()

    with pytest.raises(ValueError, match="Unsupported stored chat message role"):
        assembler.from_storage([{"role": "system", "content": "Nope"}])
