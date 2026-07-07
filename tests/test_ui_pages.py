"""In-process page tests using the simulated NiceGUI user.

These boot the real app (all @ui.page routes) with persistence redirected to a
temp directory, so they verify that every page actually renders and that basic
interactions work -- without a browser or network access.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from nicegui.testing import User

from app.ui.components.story_bible_forms import _build_timeline_mermaid, _during_groups
from app.world.models import Event, EventRelation, StoryBible


async def test_index_redirects_to_workspace(user: User) -> None:
    await user.open("/")
    await user.should_see("Story Bible")


async def test_workspace_renders_narrative_style_and_chat(user: User) -> None:
    await user.open("/workspace")
    await user.should_see("Premise")
    await user.should_see("Writing style")
    await user.should_see("Send")
    await user.should_not_see("Notes")


async def test_ungenerated_scene_opens_in_edit_mode_with_blueprint(user: User) -> None:
    # A scene without generated prose opens in edit mode with the blueprint
    # expanded so the writer can review the card and generate.
    await user.open("/workspace/narrative-style")
    user.find(marker="new-scene-button").click()
    await user.should_see("Notes")
    await user.should_see("Preview Markdown")
    await user.should_see("Blueprint")
    await user.should_see("Generated")
    await user.should_see("Enacted events")
    title = next(iter(user.find(marker="scene-title-input").elements))
    assert title.visible is True
    title.set_value("Renamed Scene")
    assert title.value == "Renamed Scene"
    # Chat must be enabled because the test environment provides a valid-looking key.
    await user.should_not_see("Chat is disabled because model settings are invalid.")


async def test_scene_blueprint_hidden_in_preview_mode(user: User) -> None:
    await user.open("/workspace/narrative-style")
    user.find(marker="new-scene-button").click()
    await user.should_see("Notes")
    user.find(marker="scene-editor-toggle-button").click()
    await user.should_see("Edit Markdown")
    await user.should_not_see("Blueprint")
    await user.should_not_see("Generated")


async def test_generated_scene_opens_in_preview_mode(
    user: User,
    isolated_data_dir: Path,
) -> None:
    from datetime import datetime, timezone

    from app.persistence.world import JsonFileWorldStore, default_world
    from app.world.models import (
        Event,
        Scene,
        SceneBlueprint,
        SceneGenerated,
        blueprint_fingerprint,
    )

    world = default_world()
    world.story_bible.timeline.append(Event(id="event_arrival", title="The Arrival"))
    blueprint = SceneBlueprint(premise="Something happens.", event_ids=["event_arrival"])
    world.scenes.append(
        Scene(
            id="scene_done",
            title="Done Scene",
            markdown="# Prose",
            blueprint=blueprint,
            generated=SceneGenerated(
                blueprint_fingerprint=blueprint_fingerprint(blueprint),
                generated_at=datetime.now(timezone.utc),
            ),
        )
    )
    JsonFileWorldStore(isolated_data_dir / "world.json").save(world)

    await user.open("/workspace/scenes/scene_done")
    await user.should_see("Notes")
    # The disabled Regenerate tooltip mentions "Blueprint", so assert on
    # blueprint-form-only content instead of the expansion label.
    await user.should_not_see("Enacted events")
    await user.should_not_see("Character Stances")


async def test_scene_blueprint_shows_linked_events(
    user: User,
    isolated_data_dir: Path,
) -> None:
    from app.persistence.world import JsonFileWorldStore, default_world
    from app.world.models import Event, Scene, SceneBlueprint

    world = default_world()
    world.story_bible.timeline.append(Event(id="event_arrival", title="The Arrival"))
    world.scenes.append(
        Scene(
            id="scene_chapter_1",
            title="Chapter 1",
            markdown="# One",
            blueprint=SceneBlueprint(event_ids=["event_arrival"]),
        )
    )
    JsonFileWorldStore(isolated_data_dir / "world.json").save(world)

    # Never generated, so the editor opens in edit mode with the blueprint expanded.
    await user.open("/workspace/scenes/scene_chapter_1")
    await user.should_see("Notes")
    await user.should_see("Blueprint")
    await user.should_see("Enacted events")
    await user.should_see("The Arrival")


async def test_scene_generate_button_disabled_without_blueprint(user: User) -> None:
    await user.open("/workspace/narrative-style")
    user.find(marker="new-scene-button").click()
    await user.should_see("Generate")
    button = user.find(marker="scene-generate-button")
    assert button is not None


async def test_scene_generate_button_enabled_with_generatable_blueprint(
    user: User,
    isolated_data_dir: Path,
) -> None:
    from app.persistence.world import JsonFileWorldStore, default_world
    from app.world.models import Event, Scene, SceneBlueprint

    world = default_world()
    world.story_bible.timeline.append(Event(id="event_arrival", title="The Arrival"))
    world.scenes.append(
        Scene(
            id="scene_ready",
            title="Ready",
            markdown="# Ready",
            blueprint=SceneBlueprint(
                premise="Something happens.",
                event_ids=["event_arrival"],
            ),
        )
    )
    JsonFileWorldStore(isolated_data_dir / "world.json").save(world)

    await user.open("/workspace/scenes/scene_ready")
    await user.should_see("Generate")


async def test_scene_stale_badge_when_blueprint_changed_after_generation(
    user: User,
    isolated_data_dir: Path,
) -> None:
    from datetime import datetime, timezone

    from app.persistence.world import JsonFileWorldStore, default_world
    from app.world.models import Event, Scene, SceneBlueprint, SceneGenerated, blueprint_fingerprint

    world = default_world()
    world.story_bible.timeline.append(Event(id="event_arrival", title="The Arrival"))
    blueprint = SceneBlueprint(
        premise="Original premise.",
        event_ids=["event_arrival"],
    )
    world.scenes.append(
        Scene(
            id="scene_stale",
            title="Stale Scene",
            markdown="# Prose",
            blueprint=blueprint,
            generated=SceneGenerated(
                blueprint_fingerprint=blueprint_fingerprint(blueprint),
                generated_at=datetime.now(timezone.utc),
                outline=["Beat"],
            ),
        )
    )
    scene = world.scenes[0]
    scene.blueprint.premise = "Changed premise."
    JsonFileWorldStore(isolated_data_dir / "world.json").save(world)

    await user.open("/workspace/scenes/scene_stale")
    await user.should_see("Stale")
    await user.should_see("Regenerate")


async def test_workspace_sidebar_navigates_to_characters(user: User) -> None:
    await user.open("/workspace/narrative-style")
    user.find("Characters").click()
    await user.should_see("No characters yet.")


async def test_narrative_style_page_renders_form(user: User) -> None:
    await user.open("/workspace/narrative-style")
    await user.should_see("The intended premise, tone, themes, and writing style for this project.")
    await user.should_see("Premise")
    await user.should_see("Writing style")


async def test_world_page_renders_facts_state_and_derived_sections(user: User) -> None:
    await user.open("/workspace/world")
    await user.should_see("World Facts")
    await user.should_see("Baseline World State")
    await user.should_see("Derived World State")
    await user.should_see("No world facts yet.")


async def test_add_character_creates_and_opens_detail_form(
    user: User,
    isolated_data_dir: Path,
) -> None:
    await user.open("/workspace/characters")
    user.find("Add character").click()
    await user.should_see("Identity")
    await user.should_see("Baseline State")
    await user.should_see("Derived State")
    await user.should_not_see("Stance")

    world_path = isolated_data_dir / "world.json"
    assert world_path.is_file()
    stored = json.loads(world_path.read_text(encoding="utf-8"))
    assert len(stored["story_bible"]["characters"]) == 1


async def test_timeline_add_event_opens_event_form(
    user: User,
    isolated_data_dir: Path,
) -> None:
    await user.open("/workspace/timeline")
    await user.should_see("No events yet.")
    user.find("Add event").click()
    await user.should_see("World State Effects")
    await user.should_see("Signals")
    await user.should_see("Relationships")

    stored = json.loads((isolated_data_dir / "world.json").read_text(encoding="utf-8"))
    assert len(stored["story_bible"]["timeline"]) == 1


async def test_timeline_graph_and_event_relationships(
    user: User,
    isolated_data_dir: Path,
) -> None:
    await user.open("/workspace/timeline")
    user.find("Add event").click()
    await user.should_see("Relationships")

    await user.open("/workspace/timeline")
    user.find("Add event").click()
    await user.should_see("Add relationship")

    user.find("Add relationship").click()

    stored = json.loads((isolated_data_dir / "world.json").read_text(encoding="utf-8"))
    assert len(stored["story_bible"]["event_relations"]) == 1

    await user.open("/workspace/timeline")
    await user.should_see("Event graph")


async def test_relationship_direction_control_reverses_stored_edge(
    user: User,
    isolated_data_dir: Path,
) -> None:
    await user.open("/workspace/timeline")
    user.find("Add event").click()
    await user.should_see("Relationships")

    await user.open("/workspace/timeline")
    user.find("Add event").click()
    await user.should_see("Add relationship")

    # On the second (later-in-list) event, declare that the OTHER (earlier-in-list)
    # event is the follower. This must reverse the stored edge instead of inferring
    # direction from list position.
    direction = next(iter(user.find(marker="relation-direction-select").elements))
    direction.set_value("other_follows")
    user.find("Add relationship").click()

    stored = json.loads((isolated_data_dir / "world.json").read_text(encoding="utf-8"))
    timeline = stored["story_bible"]["timeline"]
    relations = stored["story_bible"]["event_relations"]
    assert len(relations) == 1
    # other (timeline[0]) follows this (timeline[1]): source is the other, target is this.
    assert relations[0]["source_id"] == timeline[0]["id"]
    assert relations[0]["target_id"] == timeline[1]["id"]


async def test_new_scene_button_creates_first_scene(
    user: User,
    isolated_data_dir: Path,
) -> None:
    await user.open("/workspace/narrative-style")
    user.find(marker="new-scene-button").click()
    await user.should_see("Notes")

    stored = json.loads((isolated_data_dir / "world.json").read_text(encoding="utf-8"))
    assert len(stored["scenes"]) == 1


async def test_zero_scene_workspace_renders_without_crash(user: User) -> None:
    await user.open("/workspace/narrative-style")
    await user.should_see("Premise")
    await user.should_see("New Scene")
    user.find(marker="new-scene-button")


async def test_settings_page_renders(user: User) -> None:
    await user.open("/settings")
    await user.should_see("Settings")


async def test_models_redirects_to_selection(user: User) -> None:
    await user.open("/models")
    await user.should_see("Assign model configurations to LangGraph nodes.")


async def test_model_selection_save_writes_isolated_store(
    user: User,
    isolated_data_dir: Path,
) -> None:
    await user.open("/models/selection")
    await user.should_see("Chat Agent")

    user.find("Save").click()
    await user.should_see("Model selection saved.")

    config_path = isolated_data_dir / "model_configs.json"
    assert config_path.is_file()
    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored["selections"]["chat"] == "standard"


async def test_new_model_page_renders_with_catalog(
    user: User,
    stub_model_catalog: list,
) -> None:
    await user.open("/models/new")
    await user.should_see("Create a custom reusable model configuration.")
    await user.should_see("Config ID")
    await user.should_see("Provider")
    await user.should_see("Model")


async def test_standard_model_config_page_renders(
    user: User,
    stub_model_catalog: list,
) -> None:
    await user.open("/models/configs/standard")
    await user.should_see("Standard model configuration")
    await user.should_see("System prompt prefix")
    await user.should_see("Provider")
    await user.should_see("Model")


def test_catalog_by_provider_groups_and_sorts() -> None:
    from app.models.catalog import OpenRouterModel
    from app.ui.pages.models import _catalog_by_provider, _provider_display_name

    assert (
        _provider_display_name(
            OpenRouterModel(id="anthropic/claude-3.5-sonnet", name="Anthropic: Claude 3.5 Sonnet")
        )
        == "Anthropic"
    )
    assert _provider_display_name(OpenRouterModel(id="openai/gpt-4o", name="GPT-4o")) == "Openai"
    assert (
        _provider_display_name(OpenRouterModel(id="standalone", name="Standalone Model")) == "Other"
    )

    catalog = [
        OpenRouterModel(id="test/model-large", name="Test Model Large"),
        OpenRouterModel(id="test/model-small", name="Test Model Small"),
        OpenRouterModel(id="anthropic/claude-3.5-sonnet", name="Anthropic: Claude 3.5 Sonnet"),
    ]
    grouped = _catalog_by_provider(catalog)

    assert list(grouped) == ["Anthropic", "Test"]
    assert list(grouped["Test"]) == ["test/model-large", "test/model-small"]
    assert grouped["Test"]["test/model-small"] == "Test Model Small"


async def test_header_menu_includes_clear_state(user: User) -> None:
    await user.open("/workspace/narrative-style")
    user.find(marker="header-overflow-menu").click()
    await user.should_see("Clear State...")


async def test_clear_state_dialog_clears_everything(
    user: User,
    isolated_data_dir: Path,
) -> None:
    from app.persistence.world import JsonFileWorldStore, default_world
    from app.world.models import Character, CharacterIdentity, Scene, WorldFact

    world = default_world()
    world.story_bible.premise = "Epic tale"
    world.story_bible.world_facts.append(WorldFact(title="The Reach", text="Coastal"))
    world.story_bible.characters.append(Character(identity=CharacterIdentity(name="Mira")))
    world.scenes.append(Scene(title="Chapter 2", markdown="# Two"))
    JsonFileWorldStore(isolated_data_dir / "world.json").save(world)

    await user.open("/workspace/narrative-style")
    user.find(marker="header-overflow-menu").click()
    user.find(marker="clear-state-menu-item").click()
    await user.should_see("Clear State")
    user.find("Everything").click()
    user.find(marker="clear-state-confirm-button").click()

    stored = json.loads((isolated_data_dir / "world.json").read_text(encoding="utf-8"))
    assert stored["story_bible"]["premise"] == ""
    assert stored["story_bible"]["world_facts"] == []
    assert stored["story_bible"]["characters"] == []
    assert len(stored["scenes"]) == 0


async def test_debug_page_renders_empty_state(user: User) -> None:
    await user.open("/debug")
    await user.should_see("LLM calls will appear here after the chat agent invokes a model.")
    await user.should_see("No LLM calls yet.")


async def test_debug_call_page_renders_response_tool_calls(
    user: User,
    isolated_data_dir: Path,
) -> None:
    record = {
        "run_id": "run-1",
        "status": "success",
        "started_at": "2026-06-12T00:00:00+00:00",
        "model": "example/model",
        "prompt": "user: Record the cabin.",
        "response_text": "Creating the fact now.",
        "response_tool_calls": [
            {
                "name": "upsert_world_fact",
                "args": {"title": "The Cabin", "text": "A squat cabin.", "fact_id": "cabin"},
                "id": "call-1",
            }
        ],
    }
    (isolated_data_dir / "llm_call_logs.json").write_text(json.dumps([record]), encoding="utf-8")

    await user.open("/debug/calls/run-1")
    await user.should_see("Creating the fact now.")
    await user.should_see("Tool Call: upsert_world_fact")


def _three_event_bible() -> StoryBible:
    return StoryBible(
        timeline=[
            Event(id="evt_a", title="Alpha"),
            Event(id="evt_b", title="Beta"),
            Event(id="evt_c", title="Gamma"),
        ]
    )


def test_during_groups_clusters_transitively_concurrent_events() -> None:
    bible = _three_event_bible()
    bible.event_relations.append(EventRelation(kind="during", source_id="evt_a", target_id="evt_b"))
    bible.event_relations.append(EventRelation(kind="during", source_id="evt_b", target_id="evt_c"))

    groups = _during_groups(bible)

    assert groups == [["evt_a", "evt_b", "evt_c"]]


def test_during_groups_ignores_solo_events() -> None:
    bible = _three_event_bible()
    bible.event_relations.append(
        EventRelation(kind="follows", source_id="evt_b", target_id="evt_a")
    )

    assert _during_groups(bible) == []


def test_build_timeline_mermaid_flows_chronologically_left_to_right() -> None:
    bible = _three_event_bible()
    bible.event_relations.append(
        EventRelation(kind="follows", source_id="evt_b", target_id="evt_a")
    )

    source = _build_timeline_mermaid(bible)

    assert source.startswith("flowchart LR")
    assert "evt_a --> evt_b" in source
    assert "|follows|" not in source


def test_build_timeline_mermaid_renders_depends_on_as_dotted_edge() -> None:
    bible = _three_event_bible()
    bible.event_relations.append(
        EventRelation(kind="depends_on", source_id="evt_b", target_id="evt_a")
    )

    source = _build_timeline_mermaid(bible)

    assert "evt_a -.-> evt_b" in source


def test_build_timeline_mermaid_groups_during_events_without_an_edge() -> None:
    bible = _three_event_bible()
    bible.event_relations.append(EventRelation(kind="during", source_id="evt_a", target_id="evt_b"))

    source = _build_timeline_mermaid(bible)

    assert 'subgraph during_group_0["during"]' in source
    assert "style during_group_0 fill:none,stroke:#9c6ade,stroke-dasharray:4 4" in source
    # The during relation must not emit an edge -- that is what kept the members
    # off the same rank. Membership in the box conveys concurrency instead.
    assert "evt_a -.- evt_b" not in source
    assert "evt_b -.- evt_a" not in source


def test_build_timeline_mermaid_marks_cycle_edges_red() -> None:
    bible = StoryBible(
        timeline=[
            Event(id="evt_a", title="Alpha"),
            Event(id="evt_b", title="Beta"),
        ]
    )
    bible.event_relations.append(
        EventRelation(id="rel_ab", kind="follows", source_id="evt_a", target_id="evt_b")
    )
    bible.event_relations.append(
        EventRelation(id="rel_ba", kind="follows", source_id="evt_b", target_id="evt_a")
    )

    source = _build_timeline_mermaid(bible)

    assert "linkStyle 0 stroke:#e53935" in source


async def test_scene_page_renders_while_generation_in_progress(
    user: User,
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import time

    from app.graphs.jobs import get_job_manager, reset_job_manager
    from app.persistence.world import JsonFileWorldStore, default_world
    from app.world.models import Event, Scene, SceneBlueprint
    from app.world.store import get_world, reset_world_cache

    world = default_world()
    world.story_bible.timeline.append(Event(id="event_arrival", title="The Arrival"))
    world.scenes.append(
        Scene(
            id="scene_gen",
            title="Mid Generation",
            markdown="# Ready",
            blueprint=SceneBlueprint(
                premise="Something happens.",
                event_ids=["event_arrival"],
            ),
        )
    )
    JsonFileWorldStore(isolated_data_dir / "world.json").save(world)

    def slow_run(scene_id: str, *, max_revisions: int = 1) -> None:
        time.sleep(0.3)

    monkeypatch.setattr("app.graphs.scene_generation.run_scene_generation", slow_run)

    reset_world_cache()
    reset_job_manager()
    get_world()
    manager = get_job_manager()
    manager.start_scene_generation("scene_gen")

    await user.open("/workspace/scenes/scene_gen")
    await user.should_see("Mid Generation")
    await user.should_see("Generating...")
    toggle = next(iter(user.find(marker="scene-editor-toggle-button").elements))
    assert toggle.enabled is False

    for _ in range(20):
        if not manager.is_generating("scene_gen"):
            break
        await asyncio.sleep(0.05)


async def test_scene_editor_disables_edit_toggle_while_generating(
    user: User,
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import time

    from app.persistence.world import JsonFileWorldStore, default_world
    from app.world.models import Event, Scene, SceneBlueprint

    world = default_world()
    world.story_bible.timeline.append(Event(id="event_arrival", title="The Arrival"))
    world.scenes.append(
        Scene(
            id="scene_gen",
            title="Generating",
            markdown="# Ready",
            blueprint=SceneBlueprint(
                premise="Something happens.",
                event_ids=["event_arrival"],
            ),
        )
    )
    JsonFileWorldStore(isolated_data_dir / "world.json").save(world)

    def slow_run(scene_id: str, *, max_revisions: int = 1) -> None:
        time.sleep(0.3)

    monkeypatch.setattr("app.graphs.scene_generation.run_scene_generation", slow_run)

    await user.open("/workspace/scenes/scene_gen")
    user.find(marker="scene-generate-button").click()
    await user.should_see("Generating...")
    await asyncio.sleep(0.05)
    toggle = next(iter(user.find(marker="scene-editor-toggle-button").elements))
    assert toggle.enabled is False


async def test_chat_send_disabled_while_job_running(
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from langchain_core.messages import AIMessageChunk

    async def fake_astream(*args, **kwargs):
        yield "messages", (AIMessageChunk(content="Streaming"), {})
        await asyncio.sleep(0.3)

    class FakeAgent:
        astream = staticmethod(fake_astream)

    monkeypatch.setattr("app.graphs.get_chat_agent", lambda: FakeAgent())

    await user.open("/workspace/narrative-style")
    textarea = next(iter(user.find("Message the writing agent...").elements))
    textarea.set_value("Hello agent")
    user.find(marker="chat-send-button").click()
    await asyncio.sleep(0.2)
    send = next(iter(user.find(marker="chat-send-button").elements))
    assert send.enabled is False


async def test_chat_persists_assistant_message_after_navigation(
    user: User,
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import json

    from langchain_core.messages import AIMessageChunk

    async def fake_astream(*args, **kwargs):
        yield "messages", (AIMessageChunk(content="Persisted reply"), {})
        await asyncio.sleep(0.15)

    class FakeAgent:
        astream = staticmethod(fake_astream)

    monkeypatch.setattr("app.graphs.get_chat_agent", lambda: FakeAgent())

    await user.open("/workspace/narrative-style")
    textarea = next(iter(user.find("Message the writing agent...").elements))
    textarea.set_value("Question")
    user.find(marker="chat-send-button").click()
    await asyncio.sleep(0.1)
    await user.open("/workspace/world")
    await user.should_see("World Facts")
    await asyncio.sleep(0.3)

    chat_path = isolated_data_dir / "chat_history.json"
    stored = json.loads(chat_path.read_text(encoding="utf-8"))
    assert any(
        msg.get("role") == "assistant" and msg.get("content") == "Persisted reply" for msg in stored
    )


def _count_top_level_content_matches(user: User, text: str) -> int:
    from nicegui import ElementFilter

    with user.client:
        elements = list(ElementFilter(content=text, only_visible=True))
        return sum(
            1
            for element in elements
            if not any(
                element in other.descendants(include_self=False)
                for other in elements
                if other is not element
            )
        )


def _message_column_child_index(message_column, element) -> int:
    for index, child in enumerate(message_column.default_slot.children):
        if element in child.descendants(include_self=True):
            return index
    msg = "element is not a descendant of the message column"
    raise ValueError(msg)


async def test_chat_finished_job_not_duplicated_on_page_remount(
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from langchain_core.messages import AIMessageChunk

    reply_text = "Unique assistant reply for remount test"

    async def fake_astream(*args, **kwargs):
        yield "messages", (AIMessageChunk(content=reply_text), {})
        await asyncio.sleep(0.05)

    class FakeAgent:
        astream = staticmethod(fake_astream)

    monkeypatch.setattr("app.graphs.get_chat_agent", lambda: FakeAgent())

    await user.open("/workspace/narrative-style")
    textarea = next(iter(user.find("Message the writing agent...").elements))
    textarea.set_value("Question")
    user.find(marker="chat-send-button").click()
    await asyncio.sleep(0.3)

    await user.open("/workspace/world")
    await asyncio.sleep(0.6)

    assert _count_top_level_content_matches(user, reply_text) == 1


async def test_chat_finished_job_does_not_replay_navigation_on_remount(
    user: User,
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from langchain_core.messages import AIMessageChunk

    from app.persistence.world import JsonFileWorldStore, default_world
    from app.world.models import Scene

    world = default_world()
    world.scenes.append(Scene(id="scene_source", title="Source Scene", markdown="# Source"))
    world.scenes.append(Scene(id="scene_target", title="Target Scene", markdown="# Target"))
    JsonFileWorldStore(isolated_data_dir / "world.json").save(world)

    async def fake_astream(*args, **kwargs):
        yield "messages", (AIMessageChunk(content="Switching scenes"), {})
        yield "updates", {"agent": {"current_scene_id": "scene_target"}}
        await asyncio.sleep(0.05)

    class FakeAgent:
        astream = staticmethod(fake_astream)

    monkeypatch.setattr("app.graphs.get_chat_agent", lambda: FakeAgent())

    await user.open("/workspace/scenes/scene_source")
    textarea = next(iter(user.find("Message the writing agent...").elements))
    textarea.set_value("Go to target scene")
    user.find(marker="chat-send-button").click()
    await asyncio.sleep(0.3)

    await user.open("/workspace/world")
    await asyncio.sleep(0.6)
    await user.should_see("World Facts")
    await user.should_not_see("Notes")


async def test_chat_live_message_renders_after_user_message(
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio

    from langchain_core.messages import AIMessageChunk

    user_text = "Slow stream ordering question"

    async def fake_astream(*args, **kwargs):
        yield "messages", (AIMessageChunk(content="Partial"), {})
        await asyncio.sleep(0.3)

    class FakeAgent:
        astream = staticmethod(fake_astream)

    monkeypatch.setattr("app.graphs.get_chat_agent", lambda: FakeAgent())

    await user.open("/workspace/narrative-style")
    textarea = next(iter(user.find("Message the writing agent...").elements))
    textarea.set_value(user_text)
    user.find(marker="chat-send-button").click()
    await user.should_see(marker="chat-live-assistant", retries=10)

    with user.client:
        message_column = next(iter(user.find(marker="chat-message-column").elements))
        user_message = next(iter(user.find(content=user_text).elements))
        live_marker = next(iter(user.find(marker="chat-live-assistant").elements))
        assert _message_column_child_index(
            message_column, live_marker
        ) > _message_column_child_index(message_column, user_message)
