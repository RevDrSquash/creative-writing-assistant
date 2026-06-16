"""Unit tests for the scene-writing workflow and draft_scene tool."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import ToolException
from langgraph.types import Command

from app.graphs.scene_workflow import (
    EssentialDetails,
    OutlineBeats,
    OutlineCritique,
    StanceList,
    StanceOutput,
    TitleSummary,
    _author_stances_node,
    _formalize_details_node,
    _outline_node,
    _title_and_summary_node,
    build_scene_writer_graph,
    structured_fake_model,
)
from app.models.client import get_chat_model_for_node
from app.models.config import (
    GRAPH_NODES,
    SCENE_DRAFT_NODE_ID,
    SCENE_FORMALIZE_NODE_ID,
    SCENE_OUTLINE_NODE_ID,
    SCENE_OUTLINE_REVIEW_NODE_ID,
    SCENE_OUTLINE_REVISE_NODE_ID,
    SCENE_STANCES_NODE_ID,
    SCENE_TITLE_SUMMARY_NODE_ID,
)
from app.tools.scene import draft_scene
from app.tools.story_bible import upsert_character
from app.world.models import World
from app.world.scene import create_scene
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
        SCENE_FORMALIZE_NODE_ID: structured_fake_model(
            EssentialDetails(premise="Formal premise.", purpose="Formal purpose.")
        ),
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
        SCENE_TITLE_SUMMARY_NODE_ID: structured_fake_model(
            TitleSummary(title="The Investigation", summary="Hero investigates.")
        ),
    }


def _seed_character() -> str:
    upsert_character.invoke({"name": "Hero"})
    return get_world().story_bible.characters[-1].id


def _workflow_input(scene_id: str, max_revisions: int = 1) -> dict[str, Any]:
    return {
        "premise": "Brief premise.",
        "purpose": "Brief purpose.",
        "pov": "Third person",
        "character_ids": ["char_hero"],
        "constraints": "Keep it tense.",
        "scene_id": scene_id,
        "revision_count": 0,
        "max_revisions": max_revisions,
    }


def test_formalize_node_persists_blueprint(isolated_world: World) -> None:
    scene = create_scene()
    models = {
        SCENE_FORMALIZE_NODE_ID: structured_fake_model(
            EssentialDetails(premise="Stored premise.", purpose="Stored purpose.")
        )
    }
    node = _formalize_details_node(models)
    node(_workflow_input(scene.id))

    blueprint = get_world().get_scene(scene.id).blueprint
    assert blueprint.premise == "Stored premise."
    assert blueprint.purpose == "Stored purpose."


def test_stances_node_persists_blueprint(isolated_world: World) -> None:
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

    stances = get_world().get_scene(scene.id).blueprint.stances
    assert len(stances) == 1
    assert stances[0].character_id == character_id
    assert stances[0].mood == ["Uneasy"]


def test_stances_node_resolves_drifted_character_id(isolated_world: World) -> None:
    upsert_character.invoke({"name": "The Narrator"})
    character_id = get_world().story_bible.characters[-1].id
    scene = create_scene()
    models = {
        SCENE_STANCES_NODE_ID: structured_fake_model(
            StanceList(stances=[StanceOutput(character_id="char_narrator", mood=["Cold"])])
        )
    }
    state = _workflow_input(scene.id)
    state["character_ids"] = [character_id]
    _author_stances_node(models)(state)

    stances = get_world().get_scene(scene.id).blueprint.stances
    assert [stance.character_id for stance in stances] == [character_id]


def test_stances_node_drops_unknown_character(isolated_world: World) -> None:
    character_id = _seed_character()
    scene = create_scene()
    models = {
        SCENE_STANCES_NODE_ID: structured_fake_model(
            StanceList(
                stances=[
                    StanceOutput(character_id=character_id, mood=["Wary"]),
                    StanceOutput(character_id="char_ghost", mood=["Absent"]),
                ]
            )
        )
    }
    state = _workflow_input(scene.id)
    state["character_ids"] = [character_id]
    _author_stances_node(models)(state)

    stances = get_world().get_scene(scene.id).blueprint.stances
    assert [stance.character_id for stance in stances] == [character_id]


def test_outline_node_persists_beats(isolated_world: World) -> None:
    scene = create_scene()
    models = {SCENE_OUTLINE_NODE_ID: structured_fake_model(OutlineBeats(beats=["Open.", "Close."]))}
    state = _workflow_input(scene.id)
    _outline_node(models)(state)

    assert get_world().get_scene(scene.id).blueprint.outline == ["Open.", "Close."]


def test_title_summary_node_persists_metadata(isolated_world: World) -> None:
    scene = create_scene()
    models = {
        SCENE_TITLE_SUMMARY_NODE_ID: structured_fake_model(
            TitleSummary(title="Night Watch", summary="A quiet patrol.")
        )
    }
    state = _workflow_input(scene.id)
    state["prose"] = "Some prose."
    _title_and_summary_node(models)(state)

    updated = get_world().get_scene(scene.id)
    assert updated.title == "Night Watch"
    assert updated.summary == "A quiet patrol."


def test_bounded_loop_honors_max_revisions(isolated_world: World) -> None:
    review_counts: list[int] = []
    revise_counts: list[int] = []

    class CountingReview:
        def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
            class Runnable:
                def invoke(self, *args: Any, **kwargs: Any) -> OutlineCritique:
                    review_counts.append(1)
                    return OutlineCritique(critique="Needs work.")

            return Runnable()

        def bind_tools(self, tools: Any, **kwargs: Any) -> CountingReview:
            return self

    class CountingRevise:
        def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
            class Runnable:
                def invoke(self, *args: Any, **kwargs: Any) -> OutlineBeats:
                    revise_counts.append(1)
                    return OutlineBeats(beats=["Revised."])

            return Runnable()

        def bind_tools(self, tools: Any, **kwargs: Any) -> CountingRevise:
            return self

    scene = create_scene()
    models = _workflow_models()
    models[SCENE_OUTLINE_REVIEW_NODE_ID] = CountingReview()
    models[SCENE_OUTLINE_REVISE_NODE_ID] = CountingRevise()

    result = build_scene_writer_graph(models=models, max_revisions=1).invoke(
        _workflow_input(scene.id, max_revisions=1)
    )

    assert review_counts == [1]
    assert revise_counts == [1]
    assert result["revision_count"] == 1
    assert result["prose"] == "Drafted scene prose."


def test_bounded_loop_allows_multiple_revisions(isolated_world: World) -> None:
    review_counts: list[int] = []
    revise_counts: list[int] = []

    class CountingReview:
        def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
            class Runnable:
                def invoke(self, *args: Any, **kwargs: Any) -> OutlineCritique:
                    review_counts.append(1)
                    return OutlineCritique(critique="Still rough.")

            return Runnable()

        def bind_tools(self, tools: Any, **kwargs: Any) -> CountingReview:
            return self

    class CountingRevise:
        def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
            class Runnable:
                def invoke(self, *args: Any, **kwargs: Any) -> OutlineBeats:
                    revise_counts.append(1)
                    return OutlineBeats(beats=[f"Beat {len(revise_counts)}."])

            return Runnable()

        def bind_tools(self, tools: Any, **kwargs: Any) -> CountingRevise:
            return self

    scene = create_scene()
    models = _workflow_models()
    models[SCENE_OUTLINE_REVIEW_NODE_ID] = CountingReview()
    models[SCENE_OUTLINE_REVISE_NODE_ID] = CountingRevise()

    result = build_scene_writer_graph(models=models, max_revisions=2).invoke(
        _workflow_input(scene.id, max_revisions=2)
    )

    assert review_counts == [1, 1]
    assert revise_counts == [1, 1]
    assert result["revision_count"] == 2


def test_full_graph_drafts_end_to_end(isolated_world: World) -> None:
    character_id = _seed_character()
    scene = create_scene()
    prose = "The hero stepped into the alley."
    input_state = _workflow_input(scene.id)
    input_state["character_ids"] = [character_id]
    result = build_scene_writer_graph(models=_workflow_models(prose=prose)).invoke(input_state)

    updated = get_world().get_scene(scene.id)
    assert result["premise"] == "Formal premise."
    assert result["title"] == "The Investigation"
    assert updated.markdown == prose
    assert updated.blueprint.outline == ["Revised beat one.", "Revised beat two."]
    assert updated.blueprint.stances[0].intent == "Investigate"


def test_draft_scene_tool_creates_and_opens_scene(
    isolated_world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    character_id = _seed_character()
    monkeypatch.setattr(
        "app.graphs.registry.WORKFLOWS",
        {"draft_scene": lambda **kwargs: build_scene_writer_graph(models=_workflow_models())},
    )

    state = {
        "current_scene_id": get_world().scenes[0].id,
        "current_scene": get_world().scenes[0].markdown,
    }

    command = draft_scene.func(
        "Brief premise.",
        "Brief purpose.",
        "First person",
        [character_id],
        state,
        "draft-call",
    )

    assert isinstance(command, Command)
    new_id = command.update["current_scene_id"]
    assert new_id != state["current_scene_id"]
    assert command.update["current_scene"] == "Drafted scene prose."
    assert len(get_world().scenes) == 2
    assert isinstance(command.update["messages"][0], ToolMessage)


def test_draft_scene_tool_normalizes_drifted_character_ids(
    isolated_world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upsert_character.invoke({"name": "The Narrator"})
    character_id = get_world().story_bible.characters[-1].id
    captured: dict[str, Any] = {}

    def fake_build(**_kwargs: Any) -> Any:
        graph = build_scene_writer_graph(models=_workflow_models())
        original_invoke = graph.invoke

        def invoke(input_state: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
            captured["character_ids"] = input_state["character_ids"]
            return original_invoke(input_state, *args, **kwargs)

        monkeypatch.setattr(graph, "invoke", invoke)
        return graph

    monkeypatch.setattr("app.graphs.registry.WORKFLOWS", {"draft_scene": fake_build})

    state = {
        "current_scene_id": get_world().scenes[0].id,
        "current_scene": get_world().scenes[0].markdown,
    }
    draft_scene.func(
        "Brief premise.",
        "Brief purpose.",
        "Second person",
        ["char_narrator"],
        state,
        "draft-call",
    )

    assert captured["character_ids"] == [character_id]


def test_draft_scene_tool_rejects_unknown_character_ids(isolated_world: World) -> None:
    _seed_character()
    state = {
        "current_scene_id": get_world().scenes[0].id,
        "current_scene": get_world().scenes[0].markdown,
    }
    scene_count = len(get_world().scenes)

    with pytest.raises(ToolException, match="Unknown character_id"):
        draft_scene.func(
            "Brief premise.",
            "Brief purpose.",
            "Third person",
            ["char_villain"],
            state,
            "draft-call",
        )

    # The bogus call must not have created an orphan scene.
    assert len(get_world().scenes) == scene_count


def test_graph_nodes_register_scene_workflow_nodes() -> None:
    node_ids = {node.node_id for node in GRAPH_NODES}
    expected = {
        SCENE_FORMALIZE_NODE_ID,
        SCENE_STANCES_NODE_ID,
        SCENE_OUTLINE_NODE_ID,
        SCENE_OUTLINE_REVIEW_NODE_ID,
        SCENE_OUTLINE_REVISE_NODE_ID,
        SCENE_DRAFT_NODE_ID,
        SCENE_TITLE_SUMMARY_NODE_ID,
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
