"""Tests for scene editing tools and fuzzy replacement."""

from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException

from app.tools.scene import (
    create_scene,
    delete_scene,
    fuzzy_replace_once,
    list_scenes,
    read_scene,
    replace_scene_text,
    select_scene,
)
from app.world.models import Scene, World
from app.world.scene import create_scene as create_scene_helper


def test_fuzzy_replace_exact_single_match_replaces() -> None:
    document = "The door opened.\nThe room was dark."

    result = fuzzy_replace_once(document, "The door opened.", "The door groaned open.")

    assert result == "The door groaned open.\nThe room was dark."


def test_fuzzy_replace_multiple_exact_matches_raises() -> None:
    with pytest.raises(ToolException, match="target matches 2 locations"):
        fuzzy_replace_once("echo\necho", "echo", "whisper")


def test_fuzzy_replace_fuzzy_match_with_whitespace_drift_replaces() -> None:
    document = "The moon was   bright over the harbor."

    result = fuzzy_replace_once(
        document,
        "The moon was bright",
        "The moon burned silver",
    )

    assert result == "The moon burned silver over the harbor."


def test_fuzzy_replace_no_match_below_threshold_raises() -> None:
    with pytest.raises(ToolException, match="no match for target"):
        fuzzy_replace_once("The room was empty.", "A dragon filled the sky.", "A storm rose.")


def test_fuzzy_replace_ambiguous_fuzzy_matches_raises() -> None:
    document = "The lantern flickered.\nThe lantern flickered."

    with pytest.raises(ToolException, match="multiple fuzzy matches found"):
        fuzzy_replace_once(document, "The lantern flickers", "The lantern died.")


def test_fuzzy_replace_empty_target_raises() -> None:
    with pytest.raises(ToolException, match="target must not be empty"):
        fuzzy_replace_once("Text", "", "Replacement")


def test_read_scene_returns_state_current_scene() -> None:
    result = read_scene.func({"current_scene": "# Scene\n\nText"})

    assert result == "# Scene\n\nText"


def test_replace_scene_text_returns_command_with_updated_scene_and_tool_message() -> None:
    command = replace_scene_text.func(
        "old wording",
        "new wording",
        {"current_scene": "Some old wording here."},
        "tool-call-1",
    )

    assert command.update["current_scene"] == "Some new wording here."
    tool_message = command.update["messages"][0]
    assert isinstance(tool_message, ToolMessage)
    assert tool_message.tool_call_id == "tool-call-1"
    assert "scene is now" in tool_message.content


def test_replace_scene_text_raises_tool_exception_on_no_match() -> None:
    with pytest.raises(ToolException, match="no match for target"):
        replace_scene_text.func(
            "missing wording",
            "new wording",
            {"current_scene": "Some old wording here."},
            "tool-call-1",
        )


def test_read_scene_with_id_reads_other_scene_from_world(isolated_world: World) -> None:
    other = Scene(title="Other", markdown="Other scene text")
    isolated_world.scenes.append(other)
    state = {"current_scene": "Open scene text", "current_scene_id": isolated_world.scenes[0].id}

    assert read_scene.func(state, scene_id=other.id) == "Other scene text"
    assert read_scene.func(state) == "Open scene text"
    with pytest.raises(ToolException, match="No scene with id"):
        read_scene.func(state, scene_id="missing")


def test_list_scenes_marks_open_scene(isolated_world: World) -> None:
    isolated_world.scenes.append(Scene(title="Chapter 2", summary="The journey"))
    first = isolated_world.scenes[0]

    listing = list_scenes.func({"current_scene_id": first.id})

    assert f"1. {first.title} [id: {first.id}] (open)" in listing
    assert "Chapter 2" in listing
    assert "The journey" in listing


def test_create_scene_helper_assigns_slug_id(isolated_world: World) -> None:
    scene = create_scene_helper("Chapter Two", summary="The journey continues")

    assert scene.id == "scene_chapter_two"
    assert isolated_world.scenes[-1].id == "scene_chapter_two"


def test_create_scene_tool_persists_open_text_and_switches(isolated_world: World) -> None:
    first = isolated_world.scenes[0]
    state = {"current_scene": "Edited mid-run text", "current_scene_id": first.id}

    command = create_scene.func("Chapter 2", state, "tool-call-1", "A new beginning")

    new_scene = isolated_world.scenes[1]
    assert new_scene.title == "Chapter 2"
    assert new_scene.summary == "A new beginning"
    assert command.update["current_scene_id"] == new_scene.id
    assert command.update["current_scene"] == ""
    # The open scene's in-run text must be saved before switching away.
    assert first.markdown == "Edited mid-run text"


def test_select_scene_tool_switches_to_existing_scene(isolated_world: World) -> None:
    other = Scene(title="Other", markdown="Other text")
    isolated_world.scenes.append(other)
    first = isolated_world.scenes[0]
    state = {"current_scene": first.markdown, "current_scene_id": first.id}

    command = select_scene.func(other.id, state, "tool-call-1")

    assert command.update["current_scene_id"] == other.id
    assert command.update["current_scene"] == "Other text"

    with pytest.raises(ToolException, match="No scene with id"):
        select_scene.func("missing", state, "tool-call-2")


def test_delete_scene_tool_switches_when_open_scene_deleted(isolated_world: World) -> None:
    doomed = Scene(title="Doomed", markdown="Doomed text")
    isolated_world.scenes.append(doomed)
    first = isolated_world.scenes[0]

    command = delete_scene.func(doomed.id, {"current_scene_id": doomed.id}, "tool-call-1")

    assert doomed not in isolated_world.scenes
    assert command.update["current_scene_id"] == first.id
    assert command.update["current_scene"] == first.markdown


def test_delete_scene_tool_keeps_state_when_other_scene_deleted(isolated_world: World) -> None:
    doomed = Scene(title="Doomed")
    isolated_world.scenes.append(doomed)
    first = isolated_world.scenes[0]

    command = delete_scene.func(doomed.id, {"current_scene_id": first.id}, "tool-call-1")

    assert "current_scene_id" not in command.update
    assert doomed not in isolated_world.scenes


def test_delete_scene_tool_refuses_last_scene(isolated_world: World) -> None:
    only_scene = isolated_world.scenes[0]

    with pytest.raises(ToolException, match="last remaining scene"):
        delete_scene.func(only_scene.id, {"current_scene_id": only_scene.id}, "tool-call-1")
