"""Unit tests for Phase 2 chat context assembly."""

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


def test_assemble_is_idempotent() -> None:
    assembler = ContextAssembler(system_prompt="System instructions")
    assembled_once = assembler.assemble([HumanMessage(content="Hello")])

    assembled_twice = assembler.assemble(assembled_once)

    assert [type(message) for message in assembled_twice] == [SystemMessage, HumanMessage]
    assert sum(isinstance(message, SystemMessage) for message in assembled_twice) == 1
    assert assembled_twice[0].content == "System instructions"
    assert assembled_twice[1].content == "Hello"
