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
from app.world.models import unique_slug
from app.world.store import get_world


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
    captured_configs: list[ModelConfig] = []

    def fake_create_agent(**kwargs: Any) -> str:
        prompts.append(kwargs["system_prompt"])
        return f"agent-{len(prompts)}"

    def fake_get_chat_model_for_config(
        config: ModelConfig, settings: Any = None, *, streaming: bool = True
    ) -> object:
        captured_configs.append(config)
        return object()

    monkeypatch.setattr(chat_agent_module, "_CHAT_AGENT", None)
    monkeypatch.setattr(chat_agent_module, "_CHAT_AGENT_CACHE_KEY", None)
    monkeypatch.setattr(
        chat_agent_module,
        "ModelSettings",
        lambda: SimpleNamespace(openrouter_api_key="sk-or-v1-test"),
    )
    monkeypatch.setattr(chat_agent_module, "get_model_config_repository", lambda: repo)
    monkeypatch.setattr(
        chat_agent_module, "get_chat_model_for_config", fake_get_chat_model_for_config
    )
    monkeypatch.setattr(chat_agent_module, "create_agent", fake_create_agent)

    first_agent = chat_agent_module.get_chat_agent()
    repo.config = repo.config.model_copy(update={"system_prompt_prefix": "Second prefix."})
    second_agent = chat_agent_module.get_chat_agent()

    assert first_agent == "agent-1"
    assert second_agent == "agent-2"
    assert prompts == [DEFAULT_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT]
    assert captured_configs[0].system_prompt_prefix == "First prefix."
    assert captured_configs[1].system_prompt_prefix == "Second prefix."


def test_chat_agent_with_propose_scene_tool_switches_open_scene(world_with_scene) -> None:
    from app.tools.story_bible import add_event, upsert_character

    upsert_character.invoke({"name": "Hero"})
    character_id = world_with_scene.story_bible.characters[-1].id
    add_event.invoke({"title": "Arrival"})
    event_id = world_with_scene.story_bible.timeline[-1].id
    tool_call = {
        "name": "propose_scene",
        "args": {
            "title": "Chapter Two",
            "premise": "Hero arrives.",
            "purpose": "Introduce hero.",
            "pov": "Third person",
            "character_ids": [character_id],
            "event_ids": [event_id],
        },
        "id": "tool-call-1",
        "type": "tool_call",
    }
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[tool_call]),
                AIMessage(content="Proposed the new scene."),
            ]
        )
    )
    agent = build_chat_agent(
        model=fake_model,
        assembler=ContextAssembler(system_prompt="System instructions"),
    )
    first_scene = world_with_scene.scenes[0]

    result = agent.invoke(
        {
            "messages": [HumanMessage(content="Start chapter two.")],
            "current_scene": first_scene.markdown,
            "current_scene_id": first_scene.id,
        }
    )

    new_scene = world_with_scene.scenes[-1]
    assert new_scene.title == "Chapter Two"
    assert new_scene.blueprint.premise == "Hero arrives."
    assert result["current_scene_id"] == new_scene.id
    assert result["current_scene"] == new_scene.markdown
    assert result["messages"][-1].content == "Proposed the new scene."


def test_chat_agent_with_update_scene_blueprint_tool(world_with_scene) -> None:
    from app.tools.story_bible import add_event

    add_event.invoke({"title": "Arrival"})
    event_id = get_world().story_bible.timeline[-1].id
    scene = world_with_scene.scenes[0]
    scene.blueprint.event_ids = [event_id]
    tool_call = {
        "name": "update_scene_blueprint",
        "args": {"premise": "Revised premise."},
        "id": "tool-call-1",
        "type": "tool_call",
    }
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                AIMessage(content="", tool_calls=[tool_call]),
                AIMessage(content="Updated the blueprint."),
            ]
        )
    )
    agent = build_chat_agent(
        model=fake_model,
        assembler=ContextAssembler(system_prompt="System instructions"),
    )

    result = agent.invoke(
        {
            "messages": [HumanMessage(content="Tighten the premise.")],
            "current_scene": scene.markdown,
            "current_scene_id": scene.id,
        }
    )

    assert scene.blueprint.premise == "Revised premise."
    assert result["messages"][-1].content == "Updated the blueprint."


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
    tool_calls = []
    assigned_ids: list[str] = []
    for index, title in enumerate(titles):
        args: dict = {"title": title}
        if index > 0:
            args["relations"] = [{"kind": "follows", "event_id": assigned_ids[index - 1]}]
        event_id = unique_slug("event_", title, set(assigned_ids))
        assigned_ids.append(event_id)
        tool_calls.append(
            {
                "name": "add_event",
                "args": args,
                "id": f"add-event-{index}",
                "type": "tool_call",
            }
        )
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
        isolated_world.story_bible.event_relations = []
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
