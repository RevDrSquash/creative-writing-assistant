"""Unit tests for the scene-writing workflow, generation entry point, and propose_scene."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import ToolException
from langgraph.types import Command

from app.graphs.jobs import JobManager
from app.graphs.scene_generation import run_scene_generation
from app.graphs.scene_workflow import (
    OutlineBeats,
    OutlineCritique,
    SceneSummary,
    StanceList,
    StanceOutput,
    _author_stances_node,
    _draft_prose_node,
    _outline_node,
    _review_outline_node,
    _summary_node,
    build_scene_writer_graph,
    structured_fake_model,
)
from app.models.client import get_chat_model_for_node
from app.models.config import (
    GRAPH_NODES,
    SCENE_DRAFT_NODE_ID,
    SCENE_OUTLINE_NODE_ID,
    SCENE_OUTLINE_REVIEW_NODE_ID,
    SCENE_OUTLINE_REVISE_NODE_ID,
    SCENE_STANCES_NODE_ID,
    SCENE_SUMMARY_NODE_ID,
)
from app.tools.scene import propose_scene
from app.tools.story_bible import add_event, upsert_character
from app.world.models import Event, EventRelation, SceneBlueprint, World, blueprint_fingerprint
from app.world.scene import create_scene, scene_is_stale, set_scene_text
from app.world.store import get_world


class ToolAwareFakeChatModel(GenericFakeChatModel):
    def bind_tools(
        self,
        tools: Any,
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> ToolAwareFakeChatModel:
        return self


def _canvas_draft_model(prose: str = "Drafted scene prose.") -> ToolAwareFakeChatModel:
    return ToolAwareFakeChatModel(messages=iter([AIMessage(content=f"<canvas>{prose}</canvas>")]))


def _workflow_models(
    *,
    prose: str = "Drafted scene prose.",
    outline_beats: list[str] | None = None,
) -> dict[str, Any]:
    beats = outline_beats or ["Beat one.", "Beat two."]
    return {
        SCENE_STANCES_NODE_ID: structured_fake_model(
            StanceList(
                stances=[
                    StanceOutput(
                        character_id="char_hero",
                        mood=["Wary"],
                        intent="Investigate",
                        tactics="Ask careful questions",
                        stakes="Trust",
                    )
                ]
            )
        ),
        SCENE_OUTLINE_NODE_ID: structured_fake_model(OutlineBeats(beats=beats)),
        SCENE_OUTLINE_REVIEW_NODE_ID: structured_fake_model(
            OutlineCritique(critique="Tighten the opening beat.")
        ),
        SCENE_OUTLINE_REVISE_NODE_ID: structured_fake_model(
            OutlineBeats(beats=["Revised beat one.", "Revised beat two."])
        ),
        SCENE_DRAFT_NODE_ID: _canvas_draft_model(prose),
        SCENE_SUMMARY_NODE_ID: structured_fake_model(SceneSummary(summary="Hero investigates.")),
    }


def _seed_character() -> str:
    upsert_character.invoke({"name": "Hero"})
    return get_world().story_bible.characters[-1].id


def _seed_event(title: str = "Alpha") -> str:
    add_event.invoke({"title": title})
    return get_world().story_bible.timeline[-1].id


def _workflow_input(
    scene_id: str,
    max_revisions: int = 1,
    *,
    event_ids: list[str] | None = None,
    related_event_ids: list[str] | None = None,
    continuity_context: str = "",
) -> dict[str, Any]:
    return {
        "premise": "Brief premise.",
        "purpose": "Brief purpose.",
        "pov": "Third person",
        "character_ids": ["char_hero"],
        "event_ids": event_ids if event_ids is not None else [],
        "related_event_ids": related_event_ids if related_event_ids is not None else [],
        "constraints": "Keep it tense.",
        "arc": ["Setup", "Turn", "Payoff"],
        "notes": "Planning note.",
        "scene_id": scene_id,
        "continuity_context": continuity_context,
        "revision_count": 0,
        "max_revisions": max_revisions,
    }


class CapturingStructuredFakeModel:
    """Structured-output fake that records the prompt passed to invoke()."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.last_prompt = ""

    def with_structured_output(self, schema: type[Any], **kwargs: Any) -> Any:
        response = self.response
        capture = self

        class _Runnable:
            def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
                if input:
                    capture.last_prompt = input[0].content
                return response

        return _Runnable()

    def bind_tools(self, tools: Any, **kwargs: Any) -> CapturingStructuredFakeModel:
        return self

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any):
        from langchain_core.messages import AIMessage
        from langchain_core.outputs import ChatGeneration, ChatResult

        message = AIMessage(content="unused")
        return ChatResult(generations=[ChatGeneration(message=message)])

    @property
    def _llm_type(self) -> str:
        return "capturing-structured-fake"


def test_stances_node_persists_generated(isolated_world: World) -> None:
    character_id = _seed_character()
    scene = create_scene()
    models = {
        SCENE_STANCES_NODE_ID: structured_fake_model(
            StanceList(
                stances=[
                    StanceOutput(
                        character_id=character_id,
                        mood=["Uneasy"],
                        intent="Escape",
                        tactics="Lie",
                        stakes="Freedom",
                    )
                ]
            )
        )
    }
    state = _workflow_input(scene.id)
    state["character_ids"] = [character_id]
    state["premise"] = "Premise"
    state["purpose"] = "Purpose"
    _author_stances_node(models)(state)

    stances = get_world().get_scene(scene.id).generated.stances
    assert len(stances) == 1
    assert stances[0].character_id == character_id
    assert stances[0].mood == ["Uneasy"]


def test_outline_node_persists_generated_beats(isolated_world: World) -> None:
    scene = create_scene()
    models = {SCENE_OUTLINE_NODE_ID: structured_fake_model(OutlineBeats(beats=["Open.", "Close."]))}
    state = _workflow_input(scene.id)
    _outline_node(models)(state)

    assert get_world().get_scene(scene.id).generated.outline == ["Open.", "Close."]


def test_workflow_nodes_include_continuity_context_in_prompts(isolated_world: World) -> None:
    character_id = _seed_character()
    scene = create_scene()
    continuity_context = (
        "## Surrounding scene context\n\n"
        "Maintain continuity with the surrounding scenes.\n\n"
        "### Previous scene (full prose)\n"
        "Title: Earlier [id: scene_prev]\n\n"
        "She left the room."
    )
    state = _workflow_input(scene.id, continuity_context=continuity_context)
    state["character_ids"] = [character_id]

    stances_model = CapturingStructuredFakeModel(
        StanceList(
            stances=[
                StanceOutput(
                    character_id=character_id,
                    mood=["Focused"],
                    intent="Continue",
                    tactics="Observe",
                    stakes="Trust",
                )
            ]
        )
    )
    outline_model = CapturingStructuredFakeModel(OutlineBeats(beats=["Beat."]))
    review_model = CapturingStructuredFakeModel(OutlineCritique(critique="Looks good."))
    models = {
        SCENE_STANCES_NODE_ID: stances_model,
        SCENE_OUTLINE_NODE_ID: outline_model,
        SCENE_OUTLINE_REVIEW_NODE_ID: review_model,
        SCENE_DRAFT_NODE_ID: _canvas_draft_model(),
    }

    _author_stances_node(models)(state)
    state["stances"] = get_world().get_scene(scene.id).generated.stances
    _outline_node(models)(state)
    state["outline"] = get_world().get_scene(scene.id).generated.outline
    _review_outline_node(models)(state)

    captured_prompts: list[str] = []

    def capturing_create_agent(*args: Any, **kwargs: Any) -> Any:
        from langchain.agents import create_agent as real_create_agent

        agent = real_create_agent(*args, **kwargs)
        original_invoke = agent.invoke

        def invoke_with_capture(input_state: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            messages = input_state.get("messages", [])
            if messages:
                captured_prompts.append(messages[0].content)
            return original_invoke(input_state, *args, **kwargs)

        agent.invoke = invoke_with_capture  # type: ignore[method-assign]
        return agent

    import app.graphs.scene_workflow as scene_workflow_module

    original_create_agent = scene_workflow_module.create_agent
    scene_workflow_module.create_agent = capturing_create_agent
    try:
        state["revision_count"] = 1
        state["max_revisions"] = 1
        _draft_prose_node(models)(state)
    finally:
        scene_workflow_module.create_agent = original_create_agent

    for prompt in [
        stances_model.last_prompt,
        outline_model.last_prompt,
        review_model.last_prompt,
        *captured_prompts,
    ]:
        assert "She left the room." in prompt
        assert "Maintain continuity with the surrounding scenes" in prompt


def test_workflow_nodes_work_with_empty_continuity_context(isolated_world: World) -> None:
    character_id = _seed_character()
    scene = create_scene("Proposed Title")
    scene.blueprint = SceneBlueprint(
        premise="Brief premise.",
        purpose="Brief purpose.",
        character_ids=[character_id],
        event_ids=[_seed_event()],
    )
    input_state = _workflow_input(
        scene.id, event_ids=scene.blueprint.event_ids, continuity_context=""
    )
    input_state["character_ids"] = [character_id]
    build_scene_writer_graph(models=_workflow_models()).invoke(input_state)

    updated = get_world().get_scene(scene.id)
    assert updated.markdown == "Drafted scene prose."


def test_summary_node_persists_summary_without_touching_title(isolated_world: World) -> None:
    scene = create_scene("Agent Chosen Title")
    models = {SCENE_SUMMARY_NODE_ID: structured_fake_model(SceneSummary(summary="A quiet patrol."))}
    state = _workflow_input(scene.id)
    state["prose"] = "Some prose."
    _summary_node(models)(state)

    updated = get_world().get_scene(scene.id)
    assert updated.title == "Agent Chosen Title"
    assert updated.summary == "A quiet patrol."


def test_full_graph_drafts_end_to_end(isolated_world: World) -> None:
    character_id = _seed_character()
    scene = create_scene("Proposed Title")
    scene.blueprint = SceneBlueprint(
        premise="Brief premise.",
        purpose="Brief purpose.",
        character_ids=[character_id],
        event_ids=[_seed_event()],
    )
    prose = "The hero stepped into the alley."
    input_state = _workflow_input(scene.id, event_ids=scene.blueprint.event_ids)
    input_state["character_ids"] = [character_id]
    build_scene_writer_graph(models=_workflow_models(prose=prose)).invoke(input_state)

    updated = get_world().get_scene(scene.id)
    assert updated.markdown == prose
    assert updated.generated.outline == ["Revised beat one.", "Revised beat two."]
    assert updated.generated.stances[0].intent == "Investigate"
    # The workflow writes the summary but never touches the title.
    assert updated.title == "Proposed Title"
    assert updated.summary == "Hero investigates."


def test_run_scene_generation_clears_old_content_and_stamps_fingerprint(
    isolated_world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    character_id = _seed_character()
    event_id = _seed_event()
    scene = create_scene()
    scene.blueprint = SceneBlueprint(
        premise="Old premise",
        purpose="Purpose",
        character_ids=[character_id],
        event_ids=[event_id],
    )
    scene.markdown = "Old prose to discard."
    scene.generated.outline = ["Old beat"]
    expected_fingerprint = blueprint_fingerprint(scene.blueprint)

    monkeypatch.setattr(
        "app.graphs.scene_generation.get_workflow",
        lambda name, **kwargs: build_scene_writer_graph(models=_workflow_models()),
    )

    run_scene_generation(scene.id)

    updated = get_world().get_scene(scene.id)
    assert updated.markdown == "Drafted scene prose."
    assert updated.generated.blueprint_fingerprint == expected_fingerprint
    assert updated.generated.generated_at is not None
    assert updated.generated.outline == ["Revised beat one.", "Revised beat two."]


def test_run_scene_generation_passes_continuity_context(
    isolated_world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.world.store import world_transaction

    with world_transaction() as world:
        world.story_bible.timeline = [
            Event(id="event_a", title="Alpha"),
            Event(id="event_b", title="Beta"),
        ]
        world.story_bible.event_relations = [
            EventRelation(kind="follows", source_id="event_b", target_id="event_a"),
        ]

    character_id = _seed_character()
    previous = create_scene("Previous")
    previous.blueprint = SceneBlueprint(
        premise="Earlier premise.",
        purpose="Earlier purpose.",
        character_ids=[character_id],
        event_ids=["event_a"],
    )
    set_scene_text(previous.id, "Previous scene ending.")

    scene = create_scene("Current")
    scene.blueprint = SceneBlueprint(
        premise="Current premise.",
        purpose="Current purpose.",
        character_ids=[character_id],
        event_ids=["event_b"],
    )

    captured: dict[str, Any] = {}

    class CapturingWorkflow:
        def invoke(self, state: dict[str, Any]) -> None:
            captured["state"] = state

    monkeypatch.setattr(
        "app.graphs.scene_generation.get_workflow",
        lambda name, **kwargs: CapturingWorkflow(),
    )

    run_scene_generation(scene.id)

    continuity_context = captured["state"]["continuity_context"]
    assert "Previous scene ending." in continuity_context
    assert "Maintain continuity with the surrounding scenes" in continuity_context


def test_scene_is_stale_when_blueprint_changes_after_generation(world_with_scene: World) -> None:
    from datetime import datetime, timezone

    from app.world.models import SceneGenerated

    scene = world_with_scene.scenes[0]
    scene.blueprint.premise = "Stable"
    scene.blueprint.event_ids = ["event_1"]
    fingerprint = blueprint_fingerprint(scene.blueprint)
    scene.generated = SceneGenerated(
        blueprint_fingerprint=fingerprint,
        generated_at=datetime.now(timezone.utc),
    )
    assert scene_is_stale(scene) is False

    scene.blueprint.premise = "Changed"
    assert scene_is_stale(scene) is True


def test_generation_manager_rejects_concurrent_start(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()
    started: list[str] = []

    def slow_run(scene_id: str, *, max_revisions: int = 1) -> None:
        started.append(scene_id)
        import time

        time.sleep(0.05)

    monkeypatch.setattr("app.graphs.scene_generation.run_scene_generation", slow_run)
    manager.start_scene_generation("scene_a")
    with pytest.raises(RuntimeError, match="already running"):
        manager.start_scene_generation("scene_a")


def test_generation_manager_captures_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()

    def failing_run(scene_id: str, *, max_revisions: int = 1) -> None:
        msg = "workflow exploded"
        raise RuntimeError(msg)

    monkeypatch.setattr("app.graphs.scene_generation.run_scene_generation", failing_run)
    manager.start_scene_generation("scene_b")
    import time

    deadline = time.time() + 2
    while manager.is_generating("scene_b") and time.time() < deadline:
        time.sleep(0.01)

    assert manager.last_error("scene_b") == "workflow exploded"


def test_propose_scene_tool_creates_and_opens_scene(
    world_with_scene: World,
) -> None:
    character_id = _seed_character()
    event_id = _seed_event()
    state = {
        "current_scene_id": world_with_scene.scenes[0].id,
        "current_scene": world_with_scene.scenes[0].markdown,
    }

    command = propose_scene.func(
        "The Proposal",
        "Brief premise.",
        "Brief purpose.",
        "First person",
        [character_id],
        [event_id],
        state,
        "propose-call",
    )

    assert isinstance(command, Command)
    new_id = command.update["current_scene_id"]
    assert new_id != state["current_scene_id"]
    assert len(get_world().scenes) == 2
    assert get_world().get_scene(new_id).title == "The Proposal"
    assert isinstance(command.update["messages"][0], ToolMessage)


def test_propose_scene_tool_rejects_unknown_character_ids(world_with_scene: World) -> None:
    _seed_character()
    event_id = _seed_event()
    state = {
        "current_scene_id": world_with_scene.scenes[0].id,
        "current_scene": world_with_scene.scenes[0].markdown,
    }
    scene_count = len(world_with_scene.scenes)

    with pytest.raises(ToolException, match="Unknown character_id"):
        propose_scene.func(
            "The Proposal",
            "Brief premise.",
            "Brief purpose.",
            "Third person",
            ["char_villain"],
            [event_id],
            state,
            "propose-call",
        )

    assert len(get_world().scenes) == scene_count


def test_graph_nodes_register_scene_workflow_nodes() -> None:
    node_ids = {node.node_id for node in GRAPH_NODES}
    expected = {
        SCENE_STANCES_NODE_ID,
        SCENE_OUTLINE_NODE_ID,
        SCENE_OUTLINE_REVIEW_NODE_ID,
        SCENE_OUTLINE_REVISE_NODE_ID,
        SCENE_DRAFT_NODE_ID,
        SCENE_SUMMARY_NODE_ID,
    }
    assert expected <= node_ids


def test_get_chat_model_for_node_resolves_registered_nodes(
    isolated_data_dir: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    created: list[str] = []

    def fake_get_chat_model_for_config(
        config: Any, settings: Any = None, *, streaming: bool = True
    ) -> str:
        created.append(config.id)
        return f"model-{config.id}"

    monkeypatch.setattr(
        "app.models.client.get_chat_model_for_config", fake_get_chat_model_for_config
    )

    result = get_chat_model_for_node(SCENE_DRAFT_NODE_ID)
    assert result == "model-large"
    assert created == ["large"]
