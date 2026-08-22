"""Tests for the World/Story Bible models and the replay engine."""

from __future__ import annotations

import pytest

from app.world.models import (
    SCHEMA_VERSION,
    AddIntimacy,
    AddWorldStateEntry,
    Character,
    CharacterBaselineState,
    CharacterIdentity,
    Event,
    EventRelation,
    Intimacy,
    IntimacyEvidence,
    RemoveIntimacy,
    RemoveWorldStateEntry,
    Scene,
    SceneBlueprint,
    SceneCharacterStance,
    SetIntimacyStrength,
    Signal,
    StoryBible,
    UpdateIntimacy,
    UpdateWorldStateEntry,
    World,
    WorldFact,
    WorldStateEntry,
    slugify,
    unique_slug,
)
from app.world.replay import derive_state, derive_state_at, effect_diagnostics


def _bible_with_character() -> tuple[StoryBible, Character, Intimacy]:
    intimacy = Intimacy(text="Wary of outsiders", strength="minor")
    character = Character(
        identity=CharacterIdentity(name="Mira"),
        baseline_state=CharacterBaselineState(
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


def test_schema_version_is_nine() -> None:
    assert SCHEMA_VERSION == 9


def test_scene_blueprint_defaults() -> None:
    blueprint = SceneBlueprint()
    assert blueprint.premise == ""
    assert blueprint.purpose == ""
    assert blueprint.pov == ""
    assert blueprint.starting_state == ""
    assert blueprint.central_conflict == ""
    assert blueprint.required_resolution == ""
    assert blueprint.character_ids == []
    assert blueprint.event_ids == []
    assert blueprint.related_event_ids == []
    assert blueprint.constraints == ""
    assert blueprint.notes == ""


def test_scene_character_stance_mood_is_list() -> None:
    stance = SceneCharacterStance(character_id="char-1", mood=["Wary", "Exhausted"])
    assert stance.mood == ["Wary", "Exhausted"]
    assert stance.intent == ""


def test_scene_has_generated_default_factory() -> None:
    scene = Scene()
    assert isinstance(scene.blueprint, SceneBlueprint)
    assert scene.generated.stances == []
    assert scene.generated.outline == []
    assert scene.generated.generated_at is None


def test_character_has_no_stance_field() -> None:
    assert "stance" not in Character.model_fields


def test_slugify_normalizes_text() -> None:
    assert slugify("The Protagonist") == "the_protagonist"
    assert slugify("  New Scene!  ") == "new_scene"
    assert slugify("") == ""


def test_unique_slug_from_text_and_handles_collisions() -> None:
    existing: set[str] = set()

    assert unique_slug("char_", "The Guard", existing) == "char_the_guard"
    existing.add("char_the_guard")
    assert unique_slug("char_", "The Guard", existing) == "char_the_guard_2"


def test_unique_slug_blank_text_uses_bare_prefix() -> None:
    existing: set[str] = set()

    assert unique_slug("char_", "", existing) == "char"
    existing.add("char")
    assert unique_slug("char_", "", existing) == "char_2"


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

    assert {item.id: item.strength for item in midpoint.intimacies} == {
        intimacy.id: "defining",
        "int-2": "major",
    }
    by_id = {item.id: item for item in final.intimacies}
    assert by_id["int-2"].text == "Trusts Mira completely"
    assert by_id[intimacy.id].strength == "dormant"


def test_derive_state_follows_graph_order_over_list_order() -> None:
    bible, character, _intimacy = _bible_with_character()
    added = Intimacy(id="int-2", text="New trust", strength="minor")
    strengthen = SetIntimacyStrength(intimacy_id="int-2", strength="defining")
    strengthen_event = Event(
        id="event_strengthen",
        title="Strengthen first in list",
        signals=[Signal(character_id=character.id, effects=[strengthen])],
    )
    add_event = Event(
        id="event_add",
        title="Add later in list",
        signals=[Signal(character_id=character.id, effects=[AddIntimacy(intimacy=added)])],
    )
    bible.timeline = [strengthen_event, add_event]
    bible.event_relations.append(
        EventRelation(
            kind="follows",
            source_id="event_strengthen",
            target_id="event_add",
        )
    )

    derived = derive_state(bible)

    assert derived.characters[character.id].intimacies[-1].strength == "defining"


def test_effect_diagnostics_warns_on_dangling_intimacy_reference() -> None:
    bible, character, _intimacy = _bible_with_character()
    added = Intimacy(id="int-2", text="Later intimacy", strength="minor")
    first = Event(
        id="event_early",
        title="Early",
        signals=[
            Signal(
                character_id=character.id,
                effects=[SetIntimacyStrength(intimacy_id="int-2", strength="major")],
            )
        ],
    )
    second = Event(
        id="event_late",
        title="Late",
        signals=[Signal(character_id=character.id, effects=[AddIntimacy(intimacy=added)])],
    )
    bible.timeline = [first, second]

    diagnostics = effect_diagnostics(bible)

    assert len(diagnostics) == 1
    assert diagnostics[0].event_id == "event_early"
    assert "int-2" in diagnostics[0].message
    assert "later in chronological order" in diagnostics[0].message


def test_effect_diagnostics_warns_on_dangling_world_state_reference() -> None:
    bible = StoryBible(
        baseline_world_state=[WorldStateEntry(id="ws-1", text="Baseline", kind="thread")]
    )
    first = Event(
        id="event_early",
        title="Early",
        world_state_effects=[UpdateWorldStateEntry(entry_id="ws-2", text="missing")],
    )
    second = Event(
        id="event_late",
        title="Late",
        world_state_effects=[
            AddWorldStateEntry(entry=WorldStateEntry(id="ws-2", text="Added later", kind="thread"))
        ],
    )
    bible.timeline = [first, second]

    diagnostics = effect_diagnostics(bible)

    assert len(diagnostics) == 1
    assert diagnostics[0].event_id == "event_early"
    assert "ws-2" in diagnostics[0].message


def test_effect_diagnostics_warns_when_target_never_added() -> None:
    bible, character, _intimacy = _bible_with_character()
    bible.timeline = [
        Event(
            title="Ghost",
            signals=[
                Signal(
                    character_id=character.id,
                    effects=[RemoveIntimacy(intimacy_id="never-added")],
                )
            ],
        )
    ]

    diagnostics = effect_diagnostics(bible)

    assert len(diagnostics) == 1
    assert "never added" in diagnostics[0].message


def test_derive_state_up_to_event_id_includes_that_event() -> None:
    bible, character, _intimacy = _bible_with_character()
    added = Intimacy(id="int-2", text="Shaken by the news", strength="minor")
    first = Event(
        title="First",
        signals=[Signal(character_id=character.id, effects=[AddIntimacy(intimacy=added)])],
    )
    second = Event(
        title="Second",
        signals=[
            Signal(
                character_id=character.id,
                effects=[UpdateIntimacy(intimacy_id="int-2", text="Resolved the crisis")],
            )
        ],
    )
    bible.timeline = [first, second]

    derived = derive_state(bible, up_to_event_id=first.id)

    assert derived.events_applied == 1
    assert derived.characters[character.id].intimacies[-1].text == "Shaken by the news"


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
                    effects=[AddIntimacy(intimacy=Intimacy(text="ignored"))],
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


def test_event_lookups() -> None:
    bible, character, _intimacy = _bible_with_character()
    event = Event(title="Only event")
    bible.timeline = [event]

    assert bible.get_event(event.id) is event
    assert bible.get_event("missing") is None
    assert bible.get_character(character.id) is character
    assert bible.get_character("missing") is None


def _bible_with_named_characters(*names: str) -> StoryBible:
    existing: set[str] = set()
    characters: list[Character] = []
    for name in names:
        char_id = unique_slug("char_", name, existing)
        existing.add(char_id)
        characters.append(Character(id=char_id, identity=CharacterIdentity(name=name)))
    return StoryBible(characters=characters)


def test_resolve_character_id_exact_match() -> None:
    bible = _bible_with_named_characters("The Narrator")

    assert bible.resolve_character_id("char_the_narrator") == "char_the_narrator"


def test_resolve_character_id_tolerates_dropped_article() -> None:
    bible = _bible_with_named_characters("The Narrator", "The Protagonist", "The Princess")

    assert bible.resolve_character_id("char_narrator") == "char_the_narrator"
    assert bible.resolve_character_id("char_protagonist") == "char_the_protagonist"
    assert bible.resolve_character_id("char_princess") == "char_the_princess"


def test_resolve_character_id_returns_none_for_unknown() -> None:
    bible = _bible_with_named_characters("The Narrator")

    assert bible.resolve_character_id("char_villain") is None
    assert bible.resolve_character_id("") is None


def test_resolve_character_id_returns_none_when_ambiguous() -> None:
    bible = _bible_with_named_characters("The Guard", "The Guard")

    # Both ids reduce to the same significant token, so there is no unique match.
    assert bible.resolve_character_id("char_guard") is None


def test_resolve_character_id_respects_allowed_set() -> None:
    bible = _bible_with_named_characters("The Narrator", "The Protagonist")

    assert bible.resolve_character_id("char_narrator", allowed=["char_the_protagonist"]) is None
    assert (
        bible.resolve_character_id("char_narrator", allowed=["char_the_narrator"])
        == "char_the_narrator"
    )


def test_resolve_event_id_exact_and_drift() -> None:
    bible = StoryBible(
        timeline=[
            Event(id="evt_the_ambush", title="The Ambush"),
            Event(id="evt_the_feast", title="The Feast"),
        ]
    )

    assert bible.resolve_event_id("evt_the_ambush") == "evt_the_ambush"
    assert bible.resolve_event_id("evt_ambush") == "evt_the_ambush"
    assert bible.resolve_event_id("evt_missing") is None


def test_resolve_event_id_returns_none_when_ambiguous() -> None:
    bible = StoryBible(
        timeline=[
            Event(id="evt_the_guard_shift", title="Guard Shift"),
            Event(id="evt_the_guard_patrol", title="Guard Patrol"),
        ]
    )

    assert bible.resolve_event_id("evt_guard") is None


def test_resolve_world_fact_id_exact_and_drift() -> None:
    bible = StoryBible(
        world_facts=[
            WorldFact(id="fact_the_harbor", title="The Harbor", text="Salt."),
            WorldFact(id="fact_the_market", title="The Market", text="Crowds."),
        ]
    )

    assert bible.resolve_world_fact_id("fact_the_harbor") == "fact_the_harbor"
    assert bible.resolve_world_fact_id("fact_harbor") == "fact_the_harbor"
    assert bible.resolve_world_fact_id("fact_missing") is None


def test_resolve_scene_id_exact_and_drift() -> None:
    world = World(
        scenes=[
            Scene(id="scene_the_docks", title="The Docks"),
            Scene(id="scene_the_tower", title="The Tower"),
        ]
    )

    assert world.resolve_scene_id("scene_the_docks") == "scene_the_docks"
    assert world.resolve_scene_id("scene_docks") == "scene_the_docks"
    assert world.resolve_scene_id("scene_missing") is None


def test_resolve_scene_id_returns_none_when_ambiguous() -> None:
    world = World(
        scenes=[
            Scene(id="scene_the_guard_post", title="Guard Post"),
            Scene(id="scene_the_guard_tower", title="Guard Tower"),
        ]
    )

    assert world.resolve_scene_id("scene_guard") is None


def test_signal_evidence_round_trips() -> None:
    bible, character, intimacy = _bible_with_character()
    bible.timeline.append(
        Event(
            title="A look",
            signals=[
                Signal(
                    character_id=character.id,
                    interpretation="They meant it.",
                    evidence=[
                        IntimacyEvidence(
                            intimacy_id=intimacy.id,
                            direction="supports",
                            strength=3,
                            rationale="The warning was personal.",
                            confidence=0.8,
                        )
                    ],
                )
            ],
        )
    )

    restored = World.model_validate(World(story_bible=bible).model_dump(mode="json"))
    entry = restored.story_bible.timeline[0].signals[0].evidence[0]
    assert entry.intimacy_id == intimacy.id
    assert entry.direction == "supports"
    assert entry.strength == 3
    assert entry.confidence == 0.8
    assert entry.novelty == "novel"


def test_derive_state_applies_evidence_rank_and_keeps_dormant_intimacies() -> None:
    bible, character, intimacy = _bible_with_character()
    bible.timeline = [
        Event(
            title="Proof",
            signals=[
                Signal(
                    character_id=character.id,
                    evidence=[
                        IntimacyEvidence(
                            intimacy_id=intimacy.id,
                            direction="supports",
                            strength=5,
                            rationale="Identity-shaking betrayal.",
                        )
                    ],
                )
            ],
        ),
        Event(
            title="Erosion",
            signals=[
                Signal(
                    character_id=character.id,
                    evidence=[
                        IntimacyEvidence(
                            intimacy_id=intimacy.id,
                            direction="contradicts",
                            strength=5,
                            rationale="The fear no longer holds.",
                        )
                    ],
                )
            ],
        ),
    ]

    after_proof = derive_state_at(bible, 1).characters[character.id]
    after_erosion = derive_state(bible).characters[character.id]

    # One identity-shaking support promotes minor to major, not defining.
    # A later identity-shaking contradiction then demotes major to minor.
    assert after_proof.intimacies[0].strength == "major"
    assert after_erosion.intimacies[0].strength == "minor"
    assert after_erosion.intimacies[0].id == intimacy.id


def test_derive_state_recomputes_evidence_rank_at_inserted_event() -> None:
    bible, character, intimacy = _bible_with_character()
    late = Event(
        id="event_late",
        title="Late proof",
        signals=[
            Signal(
                character_id=character.id,
                evidence=[
                    IntimacyEvidence(
                        intimacy_id=intimacy.id,
                        direction="supports",
                        strength=5,
                        rationale="The later confirmation.",
                    )
                ],
            )
        ],
    )
    inserted = Event(
        id="event_inserted",
        title="Inserted challenge",
        signals=[
            Signal(
                character_id=character.id,
                evidence=[
                    IntimacyEvidence(
                        intimacy_id=intimacy.id,
                        direction="contradicts",
                        strength=3,
                        rationale="A mid-timeline crack.",
                    )
                ],
            )
        ],
    )
    bible.timeline = [late, inserted]
    bible.event_relations.append(
        EventRelation(kind="follows", source_id=late.id, target_id=inserted.id)
    )

    after_insert = derive_state(bible, up_to_event_id=inserted.id).characters[character.id]
    after_both = derive_state(bible).characters[character.id]
    without_insert = derive_state(
        StoryBible(
            characters=bible.characters,
            timeline=[late],
        )
    ).characters[character.id]

    # Replay recomputes over the current order: the inserted contradiction is
    # enough to keep the later identity-shaking support from promoting.
    assert after_insert.intimacies[0].strength == "minor"
    assert after_both.intimacies[0].strength == "minor"
    assert without_insert.intimacies[0].strength == "major"


def test_derive_state_same_signal_add_and_evidence() -> None:
    bible, character, _intimacy = _bible_with_character()
    created = Intimacy(id="intim_new_debt", text="Owes Kael a debt", strength="minor")
    bible.timeline = [
        Event(
            title="A favor",
            signals=[
                Signal(
                    character_id=character.id,
                    effects=[AddIntimacy(intimacy=created)],
                    evidence=[
                        IntimacyEvidence(
                            intimacy_id=created.id,
                            direction="supports",
                            strength=3,
                            rationale="The debt is real.",
                        )
                    ],
                )
            ],
        )
    ]

    derived = derive_state(bible).characters[character.id]
    by_id = {item.id: item for item in derived.intimacies}
    # Creating signal evidence explains why the intimacy exists; one ordinary
    # event does not promote it past the conservative floor.
    assert by_id[created.id].strength == "minor"
    assert by_id[created.id].text == "Owes Kael a debt"


def test_effect_diagnostics_warns_on_dangling_evidence() -> None:
    bible, character, _intimacy = _bible_with_character()
    bible.timeline = [
        Event(
            id="event_early",
            title="Early",
            signals=[
                Signal(
                    character_id=character.id,
                    evidence=[
                        IntimacyEvidence(
                            intimacy_id="intim_later",
                            direction="supports",
                            strength=3,
                            rationale="Too soon.",
                        )
                    ],
                )
            ],
        ),
        Event(
            id="event_late",
            title="Late",
            signals=[
                Signal(
                    character_id=character.id,
                    effects=[AddIntimacy(intimacy=Intimacy(id="intim_later", text="Later"))],
                )
            ],
        ),
    ]

    diagnostics = effect_diagnostics(bible)

    assert len(diagnostics) == 1
    assert diagnostics[0].event_id == "event_early"
    assert "intim_later" in diagnostics[0].message
    assert "evidence" in diagnostics[0].message


def test_resolve_intimacy_id_exact_and_drift() -> None:
    intimacy = Intimacy(id="intim_the_guild", text="I can't trust the Guild")
    character = Character(
        identity=CharacterIdentity(name="Mira"),
        baseline_state=CharacterBaselineState(intimacies=[intimacy]),
    )
    bible = StoryBible(characters=[character])

    assert bible.resolve_intimacy_id("intim_the_guild") == "intim_the_guild"
    assert bible.resolve_intimacy_id("intim_guild") == "intim_the_guild"
    assert bible.resolve_intimacy_id("intim_missing") is None
    assert bible.resolve_intimacy_id("intim_guild", character_id=character.id) == "intim_the_guild"
