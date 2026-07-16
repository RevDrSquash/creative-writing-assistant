"""Tests for workflow-scoped scene generated-artifact edit tools."""

from __future__ import annotations

import pytest
from langchain_core.tools import ToolException

from app.tools.scene_generated import (
    OutlineEdit,
    ProseEdit,
    apply_outline_operations,
    apply_prose_operations,
    edit_outline,
    edit_prose,
    update_stance,
)
from app.tools.story_bible import upsert_character
from app.world.models import SceneCharacterStance, World
from app.world.store import get_world


def test_apply_outline_replace_add_after_add_first_delete() -> None:
    outline = ["Bob enters the cabin", "Bob leaves the cabin"]
    updated, reports = apply_outline_operations(
        outline,
        [
            OutlineEdit(
                op="replace", match="enters the cabin", text="Bob and Alice enter the house"
            ),
            OutlineEdit(op="add_after", match="enter the house", text="Bob starts a fire"),
            OutlineEdit(op="add_first", text="Dawn breaks over the trees"),
            OutlineEdit(op="delete", match="leaves the cabin"),
        ],
    )

    assert updated == [
        "Dawn breaks over the trees",
        "Bob and Alice enter the house",
        "Bob starts a fire",
    ]
    assert all("[ok]" in line for line in reports)
    assert len(reports) == 4


def test_apply_outline_case_insensitive_unique_match() -> None:
    outline = ["Bob Enters The Cabin", "Alice waits outside"]
    updated, reports = apply_outline_operations(
        outline,
        [OutlineEdit(op="replace", match="ENTERS the cabin", text="Bob slips inside")],
    )

    assert updated == ["Bob slips inside", "Alice waits outside"]
    assert "[ok]" in reports[0]


def test_apply_outline_ambiguous_and_missing_matches_partial_apply() -> None:
    outline = ["Bob enters", "Bob enters again", "Alice waves"]
    updated, reports = apply_outline_operations(
        outline,
        [
            OutlineEdit(op="delete", match="Bob enters"),
            OutlineEdit(op="replace", match="waves", text="Alice nods"),
            OutlineEdit(op="delete", match="missing beat"),
        ],
    )

    assert updated == ["Bob enters", "Bob enters again", "Alice nods"]
    assert "[error]" in reports[0]
    assert "Ambiguous" in reports[0]
    assert "[ok]" in reports[1]
    assert "[error]" in reports[2]
    assert "No beat matched" in reports[2]


def test_edit_outline_tool_updates_state_via_command() -> None:
    command = edit_outline.func(
        [OutlineEdit(op="add_first", text="Opening beat")],
        {"outline": ["Existing beat"]},
        "call-1",
    )

    assert command.update["outline"] == ["Opening beat", "Existing beat"]
    assert "Applied 1/1" in command.update["messages"][0].content


def test_edit_outline_rejects_empty_operations() -> None:
    with pytest.raises(ToolException, match="at least one"):
        edit_outline.func([], {"outline": ["Beat"]}, "call-1")


def test_update_stance_updates_fields(isolated_world: World) -> None:
    upsert_character.invoke({"name": "Hero"})
    character_id = get_world().story_bible.characters[-1].id
    state = {
        "character_ids": [character_id],
        "stances": [
            SceneCharacterStance(
                character_id=character_id,
                mood=["Wary"],
                intent="Investigate",
                tactics="Ask questions",
                stakes="Trust",
            )
        ],
    }

    command = update_stance.func(
        character_id,
        state,
        "call-1",
        mood=["Determined"],
        intent="Confront",
    )

    updated = command.update["stances"]
    assert updated[0]["mood"] == ["Determined"]
    assert updated[0]["intent"] == "Confront"
    assert updated[0]["tactics"] == "Ask questions"
    assert "Updated stance" in command.update["messages"][0].content


def test_update_stance_returns_only_changed_stance(isolated_world: World) -> None:
    """The stances state key merges by character_id, so the update must carry
    only the changed stance; a full-list update would clobber parallel calls."""

    upsert_character.invoke({"name": "Hero"})
    upsert_character.invoke({"name": "Ally"})
    hero_id = get_world().story_bible.characters[-2].id
    ally_id = get_world().story_bible.characters[-1].id
    state = {
        "character_ids": [hero_id, ally_id],
        "stances": [
            SceneCharacterStance(character_id=hero_id, intent="Lead"),
            SceneCharacterStance(character_id=ally_id, intent="Follow"),
        ],
    }

    command = update_stance.func(ally_id, state, "call-1", intent="Scout ahead")

    updated = command.update["stances"]
    assert len(updated) == 1
    assert updated[0]["character_id"] == ally_id
    assert updated[0]["intent"] == "Scout ahead"


def test_update_stance_rejects_unknown_character(isolated_world: World) -> None:
    upsert_character.invoke({"name": "Hero"})
    character_id = get_world().story_bible.characters[-1].id
    state = {
        "character_ids": [character_id],
        "stances": [
            SceneCharacterStance(character_id=character_id, intent="Stay"),
        ],
    }

    with pytest.raises(ToolException, match="Unknown character_id"):
        update_stance.func("char_villain", state, "call-1", intent="Flee")


def test_update_stance_rejects_character_without_stance(isolated_world: World) -> None:
    upsert_character.invoke({"name": "Hero"})
    upsert_character.invoke({"name": "Ally"})
    hero_id = get_world().story_bible.characters[-2].id
    ally_id = get_world().story_bible.characters[-1].id
    state = {
        "character_ids": [hero_id, ally_id],
        "stances": [SceneCharacterStance(character_id=hero_id, intent="Lead")],
    }

    with pytest.raises(ToolException, match="No stance"):
        update_stance.func(ally_id, state, "call-1", intent="Follow")


def test_apply_prose_replace_delete_and_insert() -> None:
    prose = "Bob entered the cabin. Alice waited."
    updated, reports = apply_prose_operations(
        prose,
        [
            ProseEdit(match="entered the cabin", replacement="and Alice entered the house"),
            ProseEdit(match="Alice waited.", replacement=""),
            ProseEdit(
                match="entered the house",
                replacement="entered the house. Bob lit a fire.",
            ),
        ],
    )

    assert updated == "Bob and Alice entered the house. Bob lit a fire.. "
    assert all("[ok]" in line for line in reports)


def test_apply_prose_ambiguous_match_skips_op() -> None:
    prose = "The door opened. The door closed."
    updated, reports = apply_prose_operations(
        prose,
        [ProseEdit(match="The door", replacement="A gate")],
    )

    assert updated == prose
    assert "[error]" in reports[0]
    assert "Ambiguous" in reports[0]


def test_edit_prose_tool_updates_current_scene() -> None:
    command = edit_prose.func(
        [ProseEdit(match="quiet", replacement="tense")],
        {"current_scene": "The quiet room."},
        "call-1",
    )

    assert command.update["current_scene"] == "The tense room."
    assert "Applied 1/1" in command.update["messages"][0].content
