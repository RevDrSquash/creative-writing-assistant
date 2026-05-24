"""Unit tests for the Phase 2 LangGraph chat agent."""

from typing import Any, ClassVar

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.graphs.chat_agent import build_chat_agent
from app.graphs.context import DEFAULT_SYSTEM_PROMPT, ContextAssembler


class RecordingFakeChatModel(GenericFakeChatModel):
    recorded_messages: ClassVar[list[BaseMessage]] = []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        type(self).recorded_messages = list(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def test_build_chat_agent_invokes_fake_model() -> None:
    fake_model = GenericFakeChatModel(messages=iter([AIMessage(content="Hello writer.")]))
    agent = build_chat_agent(
        model=fake_model,
        assembler=ContextAssembler(system_prompt="System instructions"),
    )

    result = agent.invoke({"messages": [HumanMessage(content="Hi")]})

    assert result["messages"][-1].content == "Hello writer."


def test_build_chat_agent_prepends_system_prompt_to_model_input() -> None:
    RecordingFakeChatModel.recorded_messages = []
    fake_model = RecordingFakeChatModel(messages=iter([AIMessage(content="ok")]))
    agent = build_chat_agent(model=fake_model)

    result = agent.invoke({"messages": [HumanMessage(content="Hi")]})
    recorded = RecordingFakeChatModel.recorded_messages

    assert isinstance(recorded[0], SystemMessage)
    assert recorded[0].content == DEFAULT_SYSTEM_PROMPT
    assert isinstance(recorded[1], HumanMessage)
    assert recorded[1].content == "Hi"
    assert not any(isinstance(message, SystemMessage) for message in result["messages"])
