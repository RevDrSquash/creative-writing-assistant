"""Unit tests for the Phase 2 LangGraph chat agent."""

from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

import app.graphs.chat_agent as chat_agent_module
from app.graphs.chat_agent import build_chat_agent
from app.graphs.context import DEFAULT_SYSTEM_PROMPT, ContextAssembler
from app.models.config import CHAT_NODE_ID, ModelConfig


class ToolAwareFakeChatModel(GenericFakeChatModel):
    def bind_tools(
        self,
        tools: Any,
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> "ToolAwareFakeChatModel":
        return self


class RecordingFakeChatModel(ToolAwareFakeChatModel):
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
    fake_model = ToolAwareFakeChatModel(messages=iter([AIMessage(content="Hello writer.")]))
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


def test_build_chat_agent_composes_config_prefix_into_model_input() -> None:
    RecordingFakeChatModel.recorded_messages = []
    fake_model = RecordingFakeChatModel(messages=iter([AIMessage(content="ok")]))
    agent = build_chat_agent(
        model=fake_model,
        assembler=ContextAssembler(prefix="Respond with lyrical restraint."),
    )

    agent.invoke({"messages": [HumanMessage(content="Hi")]})
    recorded = RecordingFakeChatModel.recorded_messages

    assert isinstance(recorded[0], SystemMessage)
    assert recorded[0].content == ("Respond with lyrical restraint.\n\n" + DEFAULT_SYSTEM_PROMPT)


def test_get_chat_agent_uses_resolved_config_and_rebuilds_on_prefix_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRepository:
        config = ModelConfig(
            id="custom",
            name="Custom",
            model="example/custom",
            system_prompt_prefix="First prefix.",
        )

        def resolve_model_config(self, node_id: str) -> ModelConfig:
            assert node_id == CHAT_NODE_ID
            return self.config

    repo = FakeRepository()
    prompts: list[str] = []

    def fake_create_agent(**kwargs: Any) -> str:
        prompts.append(kwargs["system_prompt"])
        return f"agent-{len(prompts)}"

    monkeypatch.setattr(chat_agent_module, "_CHAT_AGENT", None)
    monkeypatch.setattr(chat_agent_module, "_CHAT_AGENT_CACHE_KEY", None)
    monkeypatch.setattr(
        chat_agent_module,
        "ModelSettings",
        lambda: SimpleNamespace(openrouter_api_key="sk-or-v1-test"),
    )
    monkeypatch.setattr(chat_agent_module, "get_model_config_repository", lambda: repo)
    monkeypatch.setattr(chat_agent_module, "get_chat_model_for_config", lambda *args: object())
    monkeypatch.setattr(chat_agent_module, "create_agent", fake_create_agent)

    first_agent = chat_agent_module.get_chat_agent()
    repo.config = repo.config.model_copy(update={"system_prompt_prefix": "Second prefix."})
    second_agent = chat_agent_module.get_chat_agent()

    assert first_agent == "agent-1"
    assert second_agent == "agent-2"
    assert prompts == [
        "First prefix.\n\n" + DEFAULT_SYSTEM_PROMPT,
        "Second prefix.\n\n" + DEFAULT_SYSTEM_PROMPT,
    ]


def test_chat_agent_with_create_scene_tool_switches_open_scene(isolated_world) -> None:
    tool_call = {
        "name": "create_scene",
        "args": {"title": "Chapter 2", "summary": "A fresh start"},
        "id": "tool-call-1",
        "type": "tool_call",
    }
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[tool_call]),
                AIMessage(content="Created the new scene."),
            ]
        )
    )
    agent = build_chat_agent(
        model=fake_model,
        assembler=ContextAssembler(system_prompt="System instructions"),
    )
    first_scene = isolated_world.scenes[0]

    result = agent.invoke(
        {
            "messages": [HumanMessage(content="Start chapter two.")],
            "current_scene": first_scene.markdown,
            "current_scene_id": first_scene.id,
        }
    )

    new_scene = isolated_world.scenes[1]
    assert new_scene.title == "Chapter 2"
    assert result["current_scene_id"] == new_scene.id
    assert result["current_scene"] == ""
    assert result["messages"][-1].content == "Created the new scene."


def test_chat_agent_surfaces_tool_failure_and_continues(isolated_world) -> None:
    tool_call = {
        "name": "upsert_world_fact",
        "args": {"title": "The Cabin", "text": "A squat cabin.", "fact_id": "cabin"},
        "id": "tool-call-1",
        "type": "tool_call",
    }
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[tool_call]),
                AIMessage(content="That fact id does not exist; I'll create it instead."),
            ]
        )
    )
    agent = build_chat_agent(
        model=fake_model,
        assembler=ContextAssembler(system_prompt="System instructions"),
    )

    result = agent.invoke({"messages": [HumanMessage(content="Record the cabin.")]})

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    assert "No world fact with id cabin" in str(tool_messages[0].content)
    assert result["messages"][-1].content == (
        "That fact id does not exist; I'll create it instead."
    )


async def test_chat_agent_surfaces_tool_failure_in_async_stream(isolated_world) -> None:
    tool_call = {
        "name": "read_character",
        "args": {"character_id": "missing"},
        "id": "tool-call-1",
        "type": "tool_call",
    }
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[tool_call]),
                AIMessage(content="No such character exists yet."),
            ]
        )
    )
    agent = build_chat_agent(
        model=fake_model,
        assembler=ContextAssembler(system_prompt="System instructions"),
    )

    updates = [
        payload
        async for _name, payload in agent.astream(
            {"messages": [HumanMessage(content="Describe the princess.")]},
            stream_mode=["updates"],
        )
    ]

    final_messages = [
        message
        for payload in updates
        for node_updates in payload.values()
        if isinstance(node_updates, dict)
        for message in node_updates.get("messages") or []
    ]
    tool_messages = [m for m in final_messages if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].status == "error"
    assert final_messages[-1].content == "No such character exists yet."


def _batched_add_event_message(titles: list[str]) -> AIMessage:
    tool_calls = [
        {
            "name": "add_event",
            "args": {"title": title},
            "id": f"add-event-{index}",
            "type": "tool_call",
        }
        for index, title in enumerate(titles)
    ]
    return AIMessage(content="", tool_calls=tool_calls)


def test_chat_agent_applies_batched_tool_calls_in_emission_order_sync(isolated_world) -> None:
    titles = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [_batched_add_event_message(titles), AIMessage(content="Added the timeline.")]
        )
    )
    agent = build_chat_agent(
        model=fake_model,
        assembler=ContextAssembler(system_prompt="System instructions"),
    )

    agent.invoke({"messages": [HumanMessage(content="Add the events.")]})

    assert [event.title for event in isolated_world.story_bible.timeline] == titles


async def test_chat_agent_applies_batched_tool_calls_in_emission_order_async(
    isolated_world,
) -> None:
    titles = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]

    # The tool node runs a batch concurrently, so a single pass can pass by
    # luck; repeat to make the ordering guarantee a reliable regression guard.
    for _ in range(10):
        isolated_world.story_bible.timeline = []
        fake_model = ToolAwareFakeChatModel(
            messages=iter(
                [_batched_add_event_message(titles), AIMessage(content="Added the timeline.")]
            )
        )
        agent = build_chat_agent(
            model=fake_model,
            assembler=ContextAssembler(system_prompt="System instructions"),
        )

        await agent.ainvoke({"messages": [HumanMessage(content="Add the events.")]})

        assert [event.title for event in isolated_world.story_bible.timeline] == titles


def test_chat_agent_with_replace_scene_text_tool_updates_state() -> None:
    tool_call = {
        "name": "replace_scene_text",
        "args": {
            "target": "The old door creaked.",
            "replacement": "The old door opened silently.",
        },
        "id": "tool-call-1",
        "type": "tool_call",
    }
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[tool_call]),
                AIMessage(content="I revised the sentence."),
            ]
        )
    )
    agent = build_chat_agent(
        model=fake_model,
        assembler=ContextAssembler(system_prompt="System instructions"),
    )

    result = agent.invoke(
        {
            "messages": [HumanMessage(content="Please revise the door sentence.")],
            "current_scene": "The old door creaked.",
        }
    )

    assert result["current_scene"] == "The old door opened silently."
    assert result["messages"][-1].content == "I revised the sentence."
