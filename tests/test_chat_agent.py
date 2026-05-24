"""Unit tests for the Phase 2 LangGraph chat agent."""

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.graphs.chat_agent import build_chat_agent
from app.graphs.context import DEFAULT_SYSTEM_PROMPT, ContextAssembler


def test_build_chat_agent_invokes_fake_model() -> None:
    fake_model = GenericFakeChatModel(messages=iter([AIMessage(content="Hello writer.")]))
    agent = build_chat_agent(model=fake_model)
    messages = ContextAssembler(system_prompt="System instructions").assemble(
        [HumanMessage(content="Hi")]
    )

    result = agent.invoke({"messages": messages})

    assert result["messages"][-1].content == "Hello writer."


def test_middleware_injects_system_prompt_before_human_message() -> None:
    fake_model = GenericFakeChatModel(messages=iter([AIMessage(content="Hello writer.")]))
    agent = build_chat_agent(model=fake_model, assembler=ContextAssembler())

    result = agent.invoke({"messages": [HumanMessage(content="Hi")]})

    assert [type(message) for message in result["messages"][:2]] == [
        SystemMessage,
        HumanMessage,
    ]
    assert sum(isinstance(message, SystemMessage) for message in result["messages"]) == 1
    assert result["messages"][0].content == DEFAULT_SYSTEM_PROMPT
    assert result["messages"][1].content == "Hi"
