"""Tests for scene editing tools and fuzzy replacement."""

from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import ToolException

from app.tools.scene import fuzzy_replace_once, read_scene, replace_scene_text


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
