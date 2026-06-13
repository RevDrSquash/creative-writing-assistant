"""Tests for the story bible agent tools."""

from __future__ import annotations

import pytest
from langchain_core.tools import ToolException

from app.tools.story_bible import (
    add_event,
    delete_character,
    delete_event,
    delete_world_fact,
    delete_world_state_entry,
    read_character,
    read_event,
    read_story_bible,
    read_timeline,
    read_world_fact,
    read_world_state,
    update_character_stance,
    update_event,
    update_narrative_style,
    upsert_character,
    upsert_world_fact,
    upsert_world_state_entry,
)
from app.world.models import (
    AddIntimacy,
    AddWorldStateEntry,
    Intimacy,
    SetStatus,
    Signal,
    World,
    WorldStateEntry,
)


def test_read_story_bible_overview_lists_entities(isolated_world: World) -> None:
    upsert_world_fact.func("The Reach", "A coastal region")
    upsert_character.func(name="Mira", goal="Find the archive")
    add_event.func("Storm hits")

    overview = read_story_bible.func()

    assert "The Reach" in overview
    assert "Mira" in overview
    assert "Storm hits" in overview
    assert "Timeline (1 events)" in overview


def test_update_narrative_style_persists(isolated_world: World) -> None:
    update_narrative_style.func("Lyrical, slow-burn fantasy.")

    assert isolated_world.story_bible.narrative_style == "Lyrical, slow-burn fantasy."


def test_world_fact_crud(isolated_world: World) -> None:
    result = upsert_world_fact.func("The Reach", "A coastal region", tags=["region"])
    fact = isolated_world.story_bible.world_facts[0]
    assert "Created" in result

    upsert_world_fact.func("The Reach", "A storm-battered coastal region", fact_id=fact.id)
    assert fact.text == "A storm-battered coastal region"
    assert fact.tags == ["region"]

    detail = read_world_fact.func(fact.id)
    assert "storm-battered" in detail

    delete_world_fact.func(fact.id)
    assert isolated_world.story_bible.world_facts == []

    with pytest.raises(ToolException, match="No world fact"):
        read_world_fact.func(fact.id)


def test_baseline_world_state_crud(isolated_world: World) -> None:
    upsert_world_state_entry.func("Drought in the valley", "pressure")
    entry = isolated_world.story_bible.baseline_world_state[0]

    upsert_world_state_entry.func("Drought worsening", "pressure", entry_id=entry.id)
    assert entry.text == "Drought worsening"

    delete_world_state_entry.func(entry.id)
    assert isolated_world.story_bible.baseline_world_state == []


def test_upsert_character_creates_and_partially_updates(isolated_world: World) -> None:
    upsert_character.func(
        name="Mira",
        traits="Curious, guarded",
        goal="Find the archive",
        intimacies=[Intimacy(text="Hungry for knowledge", strength="defining")],
    )
    character = isolated_world.story_bible.characters[0]
    assert character.identity.name == "Mira"

    upsert_character.func(character_id=character.id, status="Wounded")

    assert character.baseline_state.status == "Wounded"
    assert character.identity.traits == "Curious, guarded"
    assert character.baseline_state.intimacies[0].strength == "defining"


def test_upsert_character_rolls_back_when_save_fails(
    isolated_world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed save must not leave a phantom character behind.

    Regression test for the duplicate-character incident: a save failure after
    the in-memory append meant the character survived invisibly, so the
    model's retry created it a second time.
    """

    from app.persistence.world import get_world_store

    store = get_world_store()
    original_save = store.save
    fail_once = {"armed": True}

    def flaky_save(world: World) -> None:
        if fail_once["armed"]:
            fail_once["armed"] = False
            raise PermissionError("world.json is locked by another process")
        original_save(world)

    monkeypatch.setattr(store, "save", flaky_save)

    with pytest.raises(PermissionError):
        upsert_character.func(name="The Narrator")
    assert isolated_world.story_bible.characters == []

    upsert_character.func(name="The Narrator")

    names = [c.identity.name for c in isolated_world.story_bible.characters]
    assert names == ["The Narrator"]


def test_read_character_includes_identity_baseline_and_derived_state(
    isolated_world: World,
) -> None:
    upsert_character.func(name="Mira", goal="Find the archive")
    character = isolated_world.story_bible.characters[0]
    add_event.func(
        "Betrayal",
        signals=[Signal(character_id=character.id, effects=[SetStatus(status="Shaken")])],
    )

    detail = read_character.func(character.id)

    assert "Mira" in detail
    assert "Goal: Find the archive" in detail
    assert "Current State (after full timeline)" in detail
    assert "Status: Shaken" in detail


def test_update_character_stance_changes_only_provided_fields(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]
    character.stance.mood = "Calm"

    update_character_stance.func(character.id, intent="Win the argument")

    assert character.stance.mood == "Calm"
    assert character.stance.intent == "Win the argument"


def test_delete_character_keeps_events(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]
    add_event.func(
        "Betrayal",
        signals=[Signal(character_id=character.id, effects=[SetStatus(status="Shaken")])],
    )

    delete_character.func(character.id)

    assert isolated_world.story_bible.characters == []
    assert len(isolated_world.story_bible.timeline) == 1
    # Replay must skip the dangling signal rather than fail.
    assert "World State" in read_world_state.func()


def test_add_event_inserts_at_position(isolated_world: World) -> None:
    add_event.func("First")
    add_event.func("Third")
    add_event.func("Second", position=2)

    titles = [event.title for event in isolated_world.story_bible.timeline]
    assert titles == ["First", "Second", "Third"]
    assert "1. First" in read_timeline.func()


def test_update_event_moves_and_replaces_effects(isolated_world: World) -> None:
    add_event.func("First")
    add_event.func("Second")
    event = isolated_world.story_bible.timeline[1]

    update_event.func(
        event.id,
        title="Second (moved)",
        position=1,
        world_state_effects=[
            AddWorldStateEntry(entry=WorldStateEntry(text="Gate sealed", kind="consequence"))
        ],
    )

    timeline = isolated_world.story_bible.timeline
    assert [item.title for item in timeline] == ["Second (moved)", "First"]
    assert len(timeline[0].world_state_effects) == 1


def test_read_event_shows_effects_and_signals(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]
    add_event.func(
        "Betrayal",
        description="An ally turns on the party.",
        world_state_effects=[AddWorldStateEntry(entry=WorldStateEntry(text="Gate sealed"))],
        signals=[
            Signal(
                character_id=character.id,
                interpretation="Outsiders cannot be trusted",
                effects=[AddIntimacy(intimacy=Intimacy(text="Wary of outsiders"))],
            )
        ],
    )
    event = isolated_world.story_bible.timeline[0]

    detail = read_event.func(event.id)

    assert "Betrayal" in detail
    assert "An ally turns on the party." in detail
    assert "add_entry" in detail
    assert "Mira" in detail
    assert "Wary of outsiders" in detail


def test_delete_event_removes_it(isolated_world: World) -> None:
    add_event.func("Doomed event")
    event = isolated_world.story_bible.timeline[0]

    delete_event.func(event.id)

    assert isolated_world.story_bible.timeline == []
    with pytest.raises(ToolException, match="No event"):
        delete_event.func(event.id)


def test_read_world_state_at_event_position(isolated_world: World) -> None:
    upsert_world_state_entry.func("Drought in the valley", "pressure")
    add_event.func(
        "Storm",
        world_state_effects=[AddWorldStateEntry(entry=WorldStateEntry(text="Roads flooded"))],
    )
    add_event.func("Recovery")
    first_event = isolated_world.story_bible.timeline[0]

    at_first = read_world_state.func(first_event.id)
    full = read_world_state.func()

    assert "after 1 of 2 events" in at_first
    assert "Roads flooded" in at_first
    assert "after 2 of 2 events" in full

    with pytest.raises(ToolException, match="Event not found"):
        read_world_state.func("missing")


def test_add_event_invoked_with_json_payload_coerces_effects(isolated_world: World) -> None:
    """The real tool-call path passes JSON dicts; the args schema must coerce them."""

    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]

    add_event.invoke(
        {
            "title": "Betrayal",
            "world_state_effects": [
                {"op": "add_entry", "entry": {"text": "Gate sealed", "kind": "consequence"}}
            ],
            "signals": [
                {
                    "character_id": character.id,
                    "interpretation": "Outsiders cannot be trusted",
                    "effects": [
                        {
                            "op": "add_intimacy",
                            "intimacy": {"text": "Wary of outsiders", "strength": "minor"},
                        }
                    ],
                }
            ],
        }
    )

    event = isolated_world.story_bible.timeline[0]
    assert isinstance(event.world_state_effects[0], AddWorldStateEntry)
    assert isinstance(event.signals[0].effects[0], AddIntimacy)


def test_write_tools_persist_to_disk(isolated_world: World, isolated_data_dir) -> None:
    import json

    upsert_character.func(name="Mira")

    raw = json.loads((isolated_data_dir / "world.json").read_text(encoding="utf-8"))
    assert raw["story_bible"]["characters"][0]["identity"]["name"] == "Mira"
