"""Tests for character-arc derivation over a timeline window."""

from __future__ import annotations

import pytest

from app.world.character_arc import derive_character_arc, format_character_arc
from app.world.models import (
    AddIntimacy,
    AddWorldStateEntry,
    Character,
    CharacterBaselineState,
    CharacterIdentity,
    Event,
    EventRelation,
    Intimacy,
    RemoveIntimacy,
    SetIntimacyStrength,
    Signal,
    StoryBible,
    UpdateIntimacy,
    WorldStateEntry,
)


def _bible_with_arc() -> tuple[StoryBible, Character, Intimacy, list[Event]]:
    baseline = Intimacy(id="intim_wary", text="Wary of outsiders", strength="minor")
    character = Character(
        id="char_mira",
        identity=CharacterIdentity(name="Mira"),
        baseline_state=CharacterBaselineState(intimacies=[baseline]),
    )
    added = Intimacy(id="intim_debt", text="Owes Kael a debt", strength="major")
    events = [
        Event(
            id="event_meeting",
            title="Meeting at the gate",
            description="Kael arrives during the drought.",
            signals=[
                Signal(
                    id="sig_meet",
                    character_id=character.id,
                    interpretation="This stranger may be useful.",
                    effects=[AddIntimacy(intimacy=added)],
                )
            ],
        ),
        Event(
            id="event_storm",
            title="The storm",
            description="Roads flood; no one can leave.",
            world_state_effects=[
                AddWorldStateEntry(entry=WorldStateEntry(text="Roads flooded")),
            ],
        ),
        Event(
            id="event_betrayal",
            title="Betrayal",
            description="Kael opens the gate.",
            signals=[
                Signal(
                    id="sig_betray",
                    character_id=character.id,
                    interpretation="Outsiders cannot be trusted.",
                    effects=[
                        SetIntimacyStrength(intimacy_id=baseline.id, strength="defining"),
                        UpdateIntimacy(intimacy_id=added.id, text="Kael will pay for this"),
                    ],
                )
            ],
        ),
        Event(
            id="event_exile",
            title="Exile",
            description="Mira leaves the valley.",
            signals=[
                Signal(
                    id="sig_exile",
                    character_id=character.id,
                    interpretation="The valley is lost to her.",
                    effects=[RemoveIntimacy(intimacy_id=added.id)],
                )
            ],
        ),
    ]
    bible = StoryBible(characters=[character], timeline=list(events))
    return bible, character, baseline, events


def test_full_timeline_starts_at_baseline_and_ends_after_last_event() -> None:
    bible, character, baseline, events = _bible_with_arc()

    arc = derive_character_arc(bible, character.id)

    assert [item.id for item in arc.start_state.intimacies] == [baseline.id]
    assert arc.start_state.intimacies[0].strength == "minor"
    assert [item.text for item in arc.end_state.intimacies] == ["Wary of outsiders"]
    assert arc.end_state.intimacies[0].strength == "defining"
    assert [item.event_id for item in arc.transitions] == [
        events[0].id,
        events[2].id,
        events[3].id,
    ]


def test_blank_window_ids_match_unscoped_derivation() -> None:
    bible, character, _baseline, _events = _bible_with_arc()

    scoped = derive_character_arc(bible, character.id, start_event_id="", end_event_id="  ")
    unscoped = derive_character_arc(bible, character.id)

    assert scoped == unscoped


def test_mid_timeline_window_excludes_start_event_from_start_state() -> None:
    bible, character, baseline, events = _bible_with_arc()

    arc = derive_character_arc(
        bible,
        character.id,
        start_event_id=events[2].id,
        end_event_id=events[2].id,
    )

    intimacy_ids = {item.id: item for item in arc.start_state.intimacies}
    assert set(intimacy_ids) == {baseline.id, "intim_debt"}
    assert intimacy_ids[baseline.id].strength == "minor"
    assert intimacy_ids["intim_debt"].text == "Owes Kael a debt"

    end_ids = {item.id: item for item in arc.end_state.intimacies}
    assert end_ids[baseline.id].strength == "defining"
    assert end_ids["intim_debt"].text == "Kael will pay for this"
    assert [item.event_id for item in arc.transitions] == [events[2].id]


def test_window_is_inclusive_of_start_and_end_events() -> None:
    bible, character, _baseline, events = _bible_with_arc()

    arc = derive_character_arc(
        bible,
        character.id,
        start_event_id=events[0].id,
        end_event_id=events[2].id,
    )

    assert [item.event_id for item in arc.transitions] == [events[0].id, events[2].id]
    assert "intim_debt" in {item.id for item in arc.end_state.intimacies}
    assert "intim_debt" not in {item.id for item in arc.start_state.intimacies}


def test_end_state_includes_end_event_when_start_is_omitted() -> None:
    bible, character, baseline, events = _bible_with_arc()

    arc = derive_character_arc(bible, character.id, end_event_id=events[0].id)

    assert [item.id for item in arc.start_state.intimacies] == [baseline.id]
    assert [item.id for item in arc.end_state.intimacies] == [baseline.id, "intim_debt"]
    assert [item.event_id for item in arc.transitions] == [events[0].id]


def test_events_without_character_signals_are_skipped() -> None:
    bible, character, _baseline, events = _bible_with_arc()

    arc = derive_character_arc(bible, character.id)

    assert events[1].id not in {item.event_id for item in arc.transitions}


def test_transitions_include_event_metadata_and_effect_descriptions() -> None:
    bible, character, baseline, events = _bible_with_arc()

    arc = derive_character_arc(bible, character.id)
    meeting, betrayal, exile = arc.transitions

    assert meeting.title == "Meeting at the gate"
    assert meeting.description == events[0].description
    assert meeting.signal_text == "This stranger may be useful."
    assert meeting.changes == ("Added intimacy Owes Kael a debt (major)",)

    assert betrayal.changes == (
        f"Strengthened {baseline.text} to defining",
        "Updated intimacy Owes Kael a debt to Kael will pay for this",
    )
    assert exile.changes == ("Removed intimacy Kael will pay for this",)


def test_strengthen_and_weaken_use_relative_verbs() -> None:
    intimacy = Intimacy(id="intim_trust", text="Trusts the council", strength="major")
    character = Character(
        id="char_mira",
        identity=CharacterIdentity(name="Mira"),
        baseline_state=CharacterBaselineState(intimacies=[intimacy]),
    )
    bible = StoryBible(
        characters=[character],
        timeline=[
            Event(
                id="event_up",
                title="Oath",
                signals=[
                    Signal(
                        character_id=character.id,
                        effects=[SetIntimacyStrength(intimacy_id=intimacy.id, strength="defining")],
                    )
                ],
            ),
            Event(
                id="event_down",
                title="Doubt",
                signals=[
                    Signal(
                        character_id=character.id,
                        effects=[SetIntimacyStrength(intimacy_id=intimacy.id, strength="minor")],
                    )
                ],
            ),
        ],
    )

    arc = derive_character_arc(bible, character.id)

    assert arc.transitions[0].changes == ("Strengthened Trusts the council to defining",)
    assert arc.transitions[1].changes == ("Weakened Trusts the council to minor",)


def test_unknown_event_id_raises() -> None:
    bible, character, _baseline, _events = _bible_with_arc()

    with pytest.raises(ValueError, match="Event not found on timeline: missing"):
        derive_character_arc(bible, character.id, start_event_id="missing")

    with pytest.raises(ValueError, match="Event not found on timeline: missing"):
        derive_character_arc(bible, character.id, end_event_id="missing")


def test_reversed_window_raises() -> None:
    bible, character, _baseline, events = _bible_with_arc()

    with pytest.raises(ValueError, match="is after end event"):
        derive_character_arc(
            bible,
            character.id,
            start_event_id=events[3].id,
            end_event_id=events[0].id,
        )


def test_unknown_character_raises() -> None:
    bible, _character, _baseline, _events = _bible_with_arc()

    with pytest.raises(ValueError, match="Character not found: char_missing"):
        derive_character_arc(bible, "char_missing")


def test_derivation_follows_graph_order() -> None:
    intimacy = Intimacy(id="intim_wary", text="Wary of outsiders", strength="minor")
    character = Character(
        id="char_mira",
        identity=CharacterIdentity(name="Mira"),
        baseline_state=CharacterBaselineState(intimacies=[intimacy]),
    )
    later = Event(
        id="event_later",
        title="Listed first",
        signals=[
            Signal(
                character_id=character.id,
                effects=[SetIntimacyStrength(intimacy_id=intimacy.id, strength="defining")],
            )
        ],
    )
    earlier = Event(
        id="event_earlier",
        title="Listed second",
        signals=[
            Signal(
                character_id=character.id,
                effects=[AddIntimacy(intimacy=Intimacy(id="intim_new", text="New trust"))],
            )
        ],
    )
    bible = StoryBible(
        characters=[character],
        timeline=[later, earlier],
        event_relations=[
            EventRelation(kind="follows", source_id=later.id, target_id=earlier.id),
        ],
    )

    arc = derive_character_arc(bible, character.id)

    assert [item.event_id for item in arc.transitions] == [earlier.id, later.id]
    by_id = {item.id: item for item in arc.end_state.intimacies}
    assert by_id[intimacy.id].strength == "defining"
    assert "intim_new" in by_id


def test_format_character_arc_marks_start_transitions_and_end() -> None:
    bible, character, baseline, events = _bible_with_arc()

    rendered = format_character_arc(derive_character_arc(bible, character.id))

    assert "### State at start" in rendered
    assert "### Transitions" in rendered
    assert "### State at end" in rendered
    assert f"- {baseline.text} (minor) [id: {baseline.id}]" in rendered
    assert f"#### {events[0].title} [{events[0].id}]" in rendered
    assert "The storm" not in rendered
    assert "Added intimacy Owes Kael a debt (major)" in rendered
    assert f"- {baseline.text} (defining) [id: {baseline.id}]" in rendered
    assert "Signal: Outsiders cannot be trusted." in rendered


def test_format_character_arc_empty_window_shows_none() -> None:
    character = Character(
        id="char_mira",
        identity=CharacterIdentity(name="Mira"),
    )
    bible = StoryBible(characters=[character])

    rendered = format_character_arc(derive_character_arc(bible, character.id))
    start_block = rendered.split("### State at start")[1].split("### Transitions")[0]
    transitions_block = rendered.split("### Transitions")[1].split("### State at end")[0]

    assert "(none)" in start_block
    assert "(none)" in transitions_block
