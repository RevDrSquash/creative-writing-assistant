"""Tests for the World/Story Bible models and the replay engine."""

from __future__ import annotations

import pytest

from app.world.models import (
    AddIntimacy,
    AddWorldStateEntry,
    Character,
    CharacterBaselineState,
    CharacterIdentity,
    Event,
    Intimacy,
    RemoveIntimacy,
    RemoveWorldStateEntry,
    SetGoal,
    SetIntimacyStrength,
    SetStatus,
    Signal,
    StoryBible,
    UpdateIntimacy,
    UpdateWorldStateEntry,
    World,
    WorldStateEntry,
)
from app.world.replay import derive_state, derive_state_at


def _bible_with_character() -> tuple[StoryBible, Character, Intimacy]:
    intimacy = Intimacy(text="Wary of outsiders", strength="minor")
    character = Character(
        identity=CharacterIdentity(name="Mira"),
        baseline_state=CharacterBaselineState(
            goal="Find the archive",
            status="Healthy",
            intimacies=[intimacy],
        ),
    )
    bible = StoryBible(
        baseline_world_state=[
            WorldStateEntry(id="ws-1", text="Drought in the valley", kind="pressure")
        ],
        characters=[character],
    )
    return bible, character, intimacy


def test_world_serialization_round_trip_preserves_structure() -> None:
    bible, _character, _intimacy = _bible_with_character()
    bible.timeline.append(
        Event(
            title="Betrayal at the gate",
            world_state_effects=[AddWorldStateEntry(entry=WorldStateEntry(text="Gate sealed"))],
            signals=[
                Signal(
                    character_id=bible.characters[0].id,
                    interpretation="Outsiders cannot be trusted",
                    effects=[SetIntimacyStrength(intimacy_id="x", strength="major")],
                )
            ],
        )
    )
    world = World(story_bible=bible)

    restored = World.model_validate(world.model_dump(mode="json"))

    assert restored == world
    effect = restored.story_bible.timeline[0].world_state_effects[0]
    assert isinstance(effect, AddWorldStateEntry)
    signal_effect = restored.story_bible.timeline[0].signals[0].effects[0]
    assert isinstance(signal_effect, SetIntimacyStrength)


def test_derive_state_baseline_only() -> None:
    bible, character, intimacy = _bible_with_character()

    derived = derive_state_at(bible, 0)

    assert derived.events_applied == 0
    assert [entry.text for entry in derived.world_state] == ["Drought in the valley"]
    derived_character = derived.characters[character.id]
    assert derived_character.goal == "Find the archive"
    assert derived_character.intimacies[0].text == intimacy.text


def test_derive_state_applies_world_state_effects_in_order() -> None:
    bible, _character, _intimacy = _bible_with_character()
    bible.timeline = [
        Event(
            title="Storm",
            world_state_effects=[
                AddWorldStateEntry(entry=WorldStateEntry(id="ws-2", text="Roads flooded")),
                UpdateWorldStateEntry(entry_id="ws-1", text="Drought broken", kind="consequence"),
            ],
        ),
        Event(
            title="Recovery",
            world_state_effects=[RemoveWorldStateEntry(entry_id="ws-2")],
        ),
    ]

    after_first = derive_state_at(bible, 1)
    after_all = derive_state(bible)

    assert {entry.id: entry.text for entry in after_first.world_state} == {
        "ws-1": "Drought broken",
        "ws-2": "Roads flooded",
    }
    assert after_first.world_state[0].kind == "consequence"
    assert [entry.id for entry in after_all.world_state] == ["ws-1"]


def test_derive_state_applies_signal_effects_to_character() -> None:
    bible, character, intimacy = _bible_with_character()
    added = Intimacy(id="int-2", text="Owes Mira a debt", strength="major")
    bible.timeline = [
        Event(
            title="Betrayal",
            signals=[
                Signal(
                    character_id=character.id,
                    effects=[
                        SetGoal(goal="Escape the city"),
                        SetStatus(status="Wounded"),
                        AddIntimacy(intimacy=added),
                        SetIntimacyStrength(intimacy_id=intimacy.id, strength="defining"),
                    ],
                )
            ],
        ),
        Event(
            title="Reconciliation",
            signals=[
                Signal(
                    character_id=character.id,
                    effects=[
                        UpdateIntimacy(intimacy_id="int-2", text="Trusts Mira completely"),
                        RemoveIntimacy(intimacy_id=intimacy.id),
                    ],
                )
            ],
        ),
    ]

    midpoint = derive_state_at(bible, 1).characters[character.id]
    final = derive_state(bible).characters[character.id]

    assert midpoint.goal == "Escape the city"
    assert midpoint.status == "Wounded"
    assert {item.id: item.strength for item in midpoint.intimacies} == {
        intimacy.id: "defining",
        "int-2": "major",
    }
    assert [item.text for item in final.intimacies] == ["Trusts Mira completely"]


def test_derive_state_up_to_event_id_includes_that_event() -> None:
    bible, character, _intimacy = _bible_with_character()
    first = Event(
        title="First",
        signals=[Signal(character_id=character.id, effects=[SetStatus(status="Shaken")])],
    )
    second = Event(
        title="Second",
        signals=[Signal(character_id=character.id, effects=[SetStatus(status="Resolved")])],
    )
    bible.timeline = [first, second]

    derived = derive_state(bible, up_to_event_id=first.id)

    assert derived.events_applied == 1
    assert derived.characters[character.id].status == "Shaken"


def test_derive_state_unknown_event_id_raises() -> None:
    bible, _character, _intimacy = _bible_with_character()

    with pytest.raises(ValueError, match="Event not found"):
        derive_state(bible, up_to_event_id="missing")


def test_derive_state_skips_dangling_references() -> None:
    bible, character, _intimacy = _bible_with_character()
    bible.timeline = [
        Event(
            title="Ghost effects",
            world_state_effects=[
                UpdateWorldStateEntry(entry_id="missing", text="ignored"),
                RemoveWorldStateEntry(entry_id="missing"),
            ],
            signals=[
                Signal(
                    character_id="missing-character",
                    effects=[SetGoal(goal="ignored")],
                ),
                Signal(
                    character_id=character.id,
                    effects=[
                        SetIntimacyStrength(intimacy_id="missing", strength="defining"),
                        UpdateIntimacy(intimacy_id="missing", text="ignored"),
                        RemoveIntimacy(intimacy_id="missing"),
                    ],
                ),
            ],
        )
    ]

    derived = derive_state(bible)

    assert [entry.text for entry in derived.world_state] == ["Drought in the valley"]
    derived_character = derived.characters[character.id]
    assert derived_character.goal == "Find the archive"
    assert [item.strength for item in derived_character.intimacies] == ["minor"]


def test_derive_state_does_not_mutate_baselines() -> None:
    bible, character, intimacy = _bible_with_character()
    bible.timeline = [
        Event(
            title="Hardening",
            world_state_effects=[UpdateWorldStateEntry(entry_id="ws-1", text="Changed")],
            signals=[
                Signal(
                    character_id=character.id,
                    effects=[SetIntimacyStrength(intimacy_id=intimacy.id, strength="defining")],
                )
            ],
        )
    ]

    derive_state(bible)

    assert bible.baseline_world_state[0].text == "Drought in the valley"
    assert character.baseline_state.intimacies[0].strength == "minor"


def test_event_index_and_lookups() -> None:
    bible, character, _intimacy = _bible_with_character()
    event = Event(title="Only event")
    bible.timeline = [event]

    assert bible.event_index(event.id) == 0
    assert bible.event_index("missing") is None
    assert bible.get_event(event.id) is event
    assert bible.get_character(character.id) is character
    assert bible.get_character("missing") is None
