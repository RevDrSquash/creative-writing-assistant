"""Tests for scene editing tools."""

from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException

from app.tools.scene import (
    delete_scene,
    list_scenes,
    propose_scene,
    read_scene,
    read_scene_blueprint,
    select_scene,
    update_scene,
    update_scene_blueprint,
)
from app.world.models import Scene, SceneBlueprint, World
from app.world.scene import create_scene as create_scene_helper
from app.world.scene import set_scene_metadata


def test_read_scene_returns_state_current_scene() -> None:
    result = read_scene.func({"current_scene": "# Scene\n\nText"})

    assert result == "# Scene\n\nText"


def test_read_scene_with_id_reads_other_scene_from_world(world_with_scene: World) -> None:
    other = Scene(title="Other", markdown="Other scene text")
    world_with_scene.scenes.append(other)
    state = {"current_scene": "Open scene text", "current_scene_id": world_with_scene.scenes[0].id}

    assert read_scene.func(state, scene_id=other.id) == "Other scene text"
    assert read_scene.func(state) == "Open scene text"
    with pytest.raises(ToolException, match="No scene with id"):
        read_scene.func(state, scene_id="missing")


def test_list_scenes_marks_open_scene(world_with_scene: World) -> None:
    world_with_scene.scenes.append(Scene(title="Chapter 2", summary="The journey"))
    first = world_with_scene.scenes[0]

    listing = list_scenes.func({"current_scene_id": first.id})

    assert f"1. {first.title} [id: {first.id}] (open)" in listing
    assert "Chapter 2" in listing
    assert "The journey" in listing


def test_create_scene_helper_assigns_slug_id(world_with_scene: World) -> None:
    scene = create_scene_helper("Chapter Two", summary="The journey continues")

    assert scene.id == "scene_chapter_two"
    assert world_with_scene.scenes[-1].id == "scene_chapter_two"


def test_propose_scene_tool_creates_blueprint_and_opens(world_with_scene: World) -> None:
    from app.tools.story_bible import add_event, upsert_character

    upsert_character.invoke({"name": "Hero"})
    character_id = world_with_scene.story_bible.characters[-1].id
    add_event.invoke({"title": "Arrival"})
    event_id = world_with_scene.story_bible.timeline[-1].id
    first = world_with_scene.scenes[0]
    state = {"current_scene_id": first.id, "current_scene": first.markdown}

    command = propose_scene.func(
        "The Arrival",
        "Hero arrives.",
        "Introduce the hero.",
        "Third person",
        "Hero waits at the gate.",
        "Hero must prove they belong.",
        "Hero is admitted to the city.",
        [character_id],
        [event_id],
        state,
        "tool-call-1",
        constraints="Keep it brief.",
    )

    new_scene = world_with_scene.scenes[-1]
    assert new_scene.title == "The Arrival"
    assert new_scene.blueprint.premise == "Hero arrives."
    assert new_scene.blueprint.starting_state == "Hero waits at the gate."
    assert new_scene.blueprint.central_conflict == "Hero must prove they belong."
    assert new_scene.blueprint.required_resolution == "Hero is admitted to the city."
    assert new_scene.blueprint.event_ids == [event_id]
    assert command.update["current_scene_id"] == new_scene.id
    assert isinstance(command.update["messages"][0], ToolMessage)


def test_propose_scene_tool_rejects_blank_title(world_with_scene: World) -> None:
    from app.tools.story_bible import add_event

    add_event.invoke({"title": "Arrival"})
    event_id = world_with_scene.story_bible.timeline[-1].id
    first = world_with_scene.scenes[0]
    state = {"current_scene_id": first.id, "current_scene": first.markdown}
    scene_count = len(world_with_scene.scenes)

    with pytest.raises(ToolException, match="non-empty scene title"):
        propose_scene.func(
            "   ",
            "Hero arrives.",
            "Introduce the hero.",
            "Third person",
            "Hero waits at the gate.",
            "Hero must prove they belong.",
            "Hero is admitted to the city.",
            [],
            [event_id],
            state,
            "tool-call-1",
        )

    assert len(world_with_scene.scenes) == scene_count


@pytest.mark.parametrize(
    ("field_name", "blank_value"),
    [
        ("starting_state", "   "),
        ("central_conflict", ""),
        ("required_resolution", "\t"),
    ],
)
def test_propose_scene_tool_rejects_blank_scene_frame_fields(
    world_with_scene: World,
    field_name: str,
    blank_value: str,
) -> None:
    from app.tools.story_bible import add_event, upsert_character

    upsert_character.invoke({"name": "Hero"})
    character_id = world_with_scene.story_bible.characters[-1].id
    add_event.invoke({"title": "Arrival"})
    event_id = world_with_scene.story_bible.timeline[-1].id
    first = world_with_scene.scenes[0]
    state = {"current_scene_id": first.id, "current_scene": first.markdown}
    scene_count = len(world_with_scene.scenes)
    frame = {
        "starting_state": "Hero waits at the gate.",
        "central_conflict": "Hero must prove they belong.",
        "required_resolution": "Hero is admitted to the city.",
    }
    frame[field_name] = blank_value

    with pytest.raises(ToolException, match=f"non-empty {field_name}"):
        propose_scene.func(
            "The Arrival",
            "Hero arrives.",
            "Introduce the hero.",
            "Third person",
            frame["starting_state"],
            frame["central_conflict"],
            frame["required_resolution"],
            [character_id],
            [event_id],
            state,
            "tool-call-1",
        )

    assert len(world_with_scene.scenes) == scene_count


def test_update_scene_blueprint_marks_stale_after_generation(world_with_scene: World) -> None:
    from datetime import datetime, timezone

    from app.world.models import SceneGenerated, blueprint_fingerprint

    scene = world_with_scene.scenes[0]
    scene.blueprint.premise = "Original premise"
    scene.blueprint.event_ids = ["event_1"]
    scene.generated = SceneGenerated(
        blueprint_fingerprint=blueprint_fingerprint(scene.blueprint),
        generated_at=datetime.now(timezone.utc),
    )
    state = {"current_scene_id": scene.id}

    message = update_scene_blueprint.func(state, premise="Changed premise")

    assert "stale" in message
    assert scene.blueprint.premise == "Changed premise"


def test_select_scene_tool_switches_to_existing_scene(world_with_scene: World) -> None:
    other = Scene(title="Other", markdown="Other text")
    world_with_scene.scenes.append(other)
    first = world_with_scene.scenes[0]
    state = {"current_scene": first.markdown, "current_scene_id": first.id}

    command = select_scene.func(other.id, state, "tool-call-1")

    assert command.update["current_scene_id"] == other.id
    assert command.update["current_scene"] == "Other text"

    with pytest.raises(ToolException, match="No scene with id"):
        select_scene.func("missing", state, "tool-call-2")


def test_delete_scene_tool_switches_when_open_scene_deleted(world_with_scene: World) -> None:
    doomed = Scene(title="Doomed", markdown="Doomed text")
    world_with_scene.scenes.append(doomed)
    first = world_with_scene.scenes[0]

    command = delete_scene.func(doomed.id, {"current_scene_id": doomed.id}, "tool-call-1")

    assert doomed not in world_with_scene.scenes
    assert command.update["current_scene_id"] == first.id
    assert command.update["current_scene"] == first.markdown


def test_delete_scene_tool_keeps_state_when_other_scene_deleted(world_with_scene: World) -> None:
    doomed = Scene(title="Doomed")
    world_with_scene.scenes.append(doomed)
    first = world_with_scene.scenes[0]

    command = delete_scene.func(doomed.id, {"current_scene_id": first.id}, "tool-call-1")

    assert "current_scene_id" not in command.update
    assert doomed not in world_with_scene.scenes


def test_delete_scene_tool_clears_state_when_last_scene_deleted(world_with_scene: World) -> None:
    only_scene = world_with_scene.scenes[0]

    command = delete_scene.func(only_scene.id, {"current_scene_id": only_scene.id}, "tool-call-1")

    assert only_scene not in world_with_scene.scenes
    assert command.update["current_scene_id"] == ""
    assert command.update["current_scene"] == ""


def test_set_scene_metadata_updates_only_provided_fields(world_with_scene: World) -> None:
    scene = world_with_scene.scenes[0]
    scene.title = "Original"
    scene.summary = "Original summary"

    set_scene_metadata(scene.id, title="Renamed")

    assert scene.title == "Renamed"
    assert scene.summary == "Original summary"


def test_update_scene_tool_renames_open_scene_by_default(world_with_scene: World) -> None:
    scene = world_with_scene.scenes[0]
    state = {"current_scene_id": scene.id}

    message = update_scene.func(state, title="New Title")

    assert scene.title == "New Title"
    assert "New Title" in message


def test_update_scene_tool_targets_explicit_scene_id(world_with_scene: World) -> None:
    other = Scene(title="Other", summary="Other summary")
    world_with_scene.scenes.append(other)
    first = world_with_scene.scenes[0]
    state = {"current_scene_id": first.id}

    message = update_scene.func(state, scene_id=other.id, summary="Updated summary")

    assert other.summary == "Updated summary"
    assert other.title == "Other"
    assert "Updated summary" in message


def test_update_scene_tool_raises_on_unknown_id(world_with_scene: World) -> None:
    with pytest.raises(ToolException, match="No scene with id"):
        update_scene.func({"current_scene_id": world_with_scene.scenes[0].id}, scene_id="missing")


def test_update_scene_blueprint_updates_scene_frame(world_with_scene: World) -> None:
    scene = world_with_scene.scenes[0]
    scene.blueprint.event_ids = ["event_1"]
    state = {"current_scene_id": scene.id}

    message = update_scene_blueprint.func(
        state,
        starting_state="Opens in the rain.",
        central_conflict="They argue over the map.",
        required_resolution="They agree to split up.",
    )

    assert scene.blueprint.starting_state == "Opens in the rain."
    assert scene.blueprint.central_conflict == "They argue over the map."
    assert scene.blueprint.required_resolution == "They agree to split up."
    assert "Updated blueprint" in message


def test_read_scene_blueprint_renders_scene_frame(world_with_scene: World) -> None:
    scene = world_with_scene.scenes[0]
    scene.blueprint = SceneBlueprint(
        premise="Test",
        event_ids=["event_1"],
        starting_state="Hero waits.",
        central_conflict="Guard blocks the gate.",
        required_resolution="Hero is turned away.",
    )
    state = {"current_scene_id": scene.id}

    detail = read_scene_blueprint.func(state)

    assert "### Starting state" in detail
    assert "Hero waits." in detail
    assert "### Central conflict" in detail
    assert "Guard blocks the gate." in detail
    assert "### Required resolution" in detail
    assert "Hero is turned away." in detail


def test_read_scene_blueprint_reports_generation_status(world_with_scene: World) -> None:
    scene = world_with_scene.scenes[0]
    scene.blueprint = SceneBlueprint(premise="Test", event_ids=["event_1"])
    state = {"current_scene_id": scene.id}

    detail = read_scene_blueprint.func(state)

    assert "never generated" in detail
    assert "Test" in detail
