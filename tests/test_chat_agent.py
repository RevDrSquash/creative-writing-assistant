"""Unit tests for the Phase 2 LangGraph chat agent."""

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graphs.chat_agent import build_chat_agent
from app.graphs.context import ContextAssembler


def test_build_chat_agent_invokes_fake_model() -> None:
    fake_model = GenericFakeChatModel(messages=iter([AIMessage(content="Hello writer.")]))
    agent = build_chat_agent(model=fake_model)
    messages = ContextAssembler(system_prompt="System instructions").assemble(
        [HumanMessage(content="Hi")]
    )

    result = agent.invoke({"messages": messages})

    assert result["messages"][-1].content == "Hello writer."


def test_context_assembler_places_one_system_message_before_human_message() -> None:
    messages = ContextAssembler(system_prompt="System instructions").assemble(
        [HumanMessage(content="Hi")]
    )

    assert [type(message) for message in messages] == [SystemMessage, HumanMessage]
    assert sum(isinstance(message, SystemMessage) for message in messages) == 1
    assert messages[0].content == "System instructions"
    assert messages[1].content == "Hi"
