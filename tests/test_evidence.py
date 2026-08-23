"""Tests for the deterministic intimacy-rank accumulator."""

from __future__ import annotations

from app.world.evidence import (
    DEMOTE_AT,
    PROMOTE_AT,
    EvidenceObservation,
    accumulate_rank,
    format_threshold_distance,
)
from app.world.models import (
    Character,
    CharacterBaselineState,
    CharacterIdentity,
    Event,
    EventRelation,
    Intimacy,
    IntimacyEvidence,
    Signal,
    SignalReview,
    StoryBible,
)
from app.world.relations import scenario_ids
from app.world.replay import derive_state, derive_state_at, explain_intimacies


def _obs(
    *,
    event_id: str,
    strength: int,
    direction: str = "supports",
    chronological_index: int = 0,
    scenario_id: str = "",
    novelty: str = "novel",
    intimacy_id: str = "intim_wary",
) -> EvidenceObservation:
    return EvidenceObservation(
        intimacy_id=intimacy_id,
        direction=direction,  # type: ignore[arg-type]
        strength=strength,  # type: ignore[arg-type]
        event_id=event_id,
        signal_id=f"sig_{event_id}",
        chronological_index=chronological_index,
        scenario_id=scenario_id or event_id,
        novelty=novelty,  # type: ignore[arg-type]
        rationale=f"{direction} {strength} at {event_id}",
    )


def test_single_ordinary_event_does_not_promote() -> None:
    state = accumulate_rank("minor", [_obs(event_id="e1", strength=4, chronological_index=0)])

    assert state.rank == "minor"
    assert state.crossings == ()
    assert state.distance_to_promote is not None
    assert state.distance_to_promote > 0


def test_two_distinct_meaningful_supports_promote_minor_to_major() -> None:
    state = accumulate_rank(
        "minor",
        [
            _obs(event_id="e1", strength=3, chronological_index=0, scenario_id="a"),
            _obs(event_id="e2", strength=3, chronological_index=1, scenario_id="b"),
        ],
    )

    assert state.rank == "major"
    assert state.crossings[-1].previous_rank == "minor"
    assert state.crossings[-1].new_rank == "major"
    assert "e1" in {item.event_id for item in state.contributions}
    assert "e2" in {item.event_id for item in state.contributions}


def test_same_scenario_pair_is_reinforcement_without_promotion() -> None:
    state = accumulate_rank(
        "minor",
        [
            _obs(event_id="e1", strength=3, chronological_index=0, scenario_id="scene"),
            _obs(event_id="e2", strength=3, chronological_index=1, scenario_id="scene"),
        ],
    )

    assert state.rank == "minor"
    assert state.crossings == ()
    assert any("scenario_repeat" in item.modifiers for item in state.contributions)


def test_duplicate_novelty_diminishes_weight() -> None:
    novel = accumulate_rank(
        "minor",
        [
            _obs(event_id="e1", strength=3, chronological_index=0, scenario_id="a"),
            _obs(event_id="e2", strength=3, chronological_index=1, scenario_id="b"),
        ],
    )
    duplicate = accumulate_rank(
        "minor",
        [
            _obs(event_id="e1", strength=3, chronological_index=0, scenario_id="a"),
            _obs(
                event_id="e2",
                strength=3,
                chronological_index=1,
                scenario_id="b",
                novelty="duplicate",
            ),
        ],
    )

    assert novel.rank == "major"
    assert duplicate.rank == "minor"
    assert duplicate.contributions[-1].weight < novel.contributions[-1].weight


def test_identity_shaking_promotes_minor_but_not_to_defining() -> None:
    state = accumulate_rank("minor", [_obs(event_id="e1", strength=5)])

    assert state.rank == "major"
    assert all(crossing.new_rank != "defining" for crossing in state.crossings)


def test_identity_shaking_cannot_change_defining_alone() -> None:
    state = accumulate_rank(
        "defining",
        [_obs(event_id="e1", strength=5, direction="contradicts")],
    )

    assert state.rank == "defining"
    assert state.crossings == ()


def test_two_identity_shaking_contradictions_demote_defining_one_step() -> None:
    state = accumulate_rank(
        "defining",
        [
            _obs(event_id="e1", strength=5, direction="contradicts", chronological_index=0),
            _obs(event_id="e2", strength=5, direction="contradicts", chronological_index=1),
        ],
    )

    assert state.rank == "major"
    assert [crossing.new_rank for crossing in state.crossings] == ["major"]


def test_two_ordinary_contradictions_do_not_crack_defining() -> None:
    state = accumulate_rank(
        "defining",
        [
            _obs(event_id="e1", strength=3, direction="contradicts", chronological_index=0),
            _obs(event_id="e2", strength=3, direction="contradicts", chronological_index=1),
        ],
    )

    assert state.rank == "defining"


def test_erosion_below_minor_yields_dormant() -> None:
    state = accumulate_rank(
        "minor",
        [
            _obs(event_id="e1", strength=3, direction="contradicts", chronological_index=0),
            _obs(event_id="e2", strength=3, direction="contradicts", chronological_index=1),
        ],
    )

    assert state.rank == "dormant"
    assert state.distance_to_demote is None
    assert state.distance_to_promote is not None


def test_contradictory_evidence_is_preserved_in_explanation() -> None:
    state = accumulate_rank(
        "minor",
        [
            _obs(event_id="e1", strength=3, chronological_index=0),
            _obs(event_id="e2", strength=3, direction="contradicts", chronological_index=1),
        ],
    )

    assert state.standing_support > 0
    assert state.standing_contradict > 0
    assert state.rank == "minor"


def test_distance_to_threshold_matches_constants() -> None:
    empty = accumulate_rank("minor", [], intimacy_id="intim_wary")

    assert empty.distance_to_promote == PROMOTE_AT["minor"] - empty.effective_net
    assert empty.distance_to_demote == empty.effective_net - DEMOTE_AT["minor"]
    assert "from major" in format_threshold_distance(empty)
    assert "above dormant" in format_threshold_distance(empty)


def test_what_if_oracle_needs_no_world() -> None:
    state = accumulate_rank(
        "major",
        [
            _obs(event_id="hyp_a", strength=4, chronological_index=0, scenario_id="x"),
            _obs(event_id="hyp_b", strength=4, chronological_index=1, scenario_id="y"),
        ],
    )

    assert state.rank == "defining"
    assert state.distance_to_promote is None


def test_scenario_ids_group_directly_follows_chains() -> None:
    bible = StoryBible(
        timeline=[
            Event(id="event_a", title="A"),
            Event(id="event_b", title="B"),
            Event(id="event_c", title="C"),
        ],
        event_relations=[
            EventRelation(kind="directly_follows", source_id="event_b", target_id="event_a"),
            EventRelation(kind="follows", source_id="event_c", target_id="event_b"),
        ],
    )

    grouped = scenario_ids(bible)
    assert grouped["event_a"] == grouped["event_b"]
    assert grouped["event_c"] != grouped["event_a"]


def test_replay_skips_rejected_signal_evidence() -> None:
    intimacy = Intimacy(id="intim_wary", text="Wary", strength="minor")
    character = Character(
        id="char_mira",
        identity=CharacterIdentity(name="Mira"),
        baseline_state=CharacterBaselineState(intimacies=[intimacy]),
    )
    bible = StoryBible(
        characters=[character],
        timeline=[
            Event(
                id="event_a",
                title="A",
                signals=[
                    Signal(
                        character_id=character.id,
                        review=SignalReview(decision="rejected"),
                        evidence=[
                            IntimacyEvidence(
                                intimacy_id=intimacy.id,
                                direction="supports",
                                strength=5,
                            )
                        ],
                    )
                ],
            )
        ],
    )

    derived = derive_state(bible).characters[character.id]
    assert derived.intimacies[0].strength == "minor"


def test_replay_promotes_across_distinct_events() -> None:
    intimacy = Intimacy(id="intim_wary", text="Wary", strength="minor")
    character = Character(
        id="char_mira",
        identity=CharacterIdentity(name="Mira"),
        baseline_state=CharacterBaselineState(intimacies=[intimacy]),
    )
    bible = StoryBible(
        characters=[character],
        timeline=[
            Event(
                id="event_a",
                title="A",
                signals=[
                    Signal(
                        character_id=character.id,
                        evidence=[
                            IntimacyEvidence(
                                intimacy_id=intimacy.id,
                                direction="supports",
                                strength=3,
                            )
                        ],
                    )
                ],
            ),
            Event(
                id="event_b",
                title="B",
                signals=[
                    Signal(
                        character_id=character.id,
                        evidence=[
                            IntimacyEvidence(
                                intimacy_id=intimacy.id,
                                direction="supports",
                                strength=3,
                            )
                        ],
                    )
                ],
            ),
        ],
    )

    after_first = derive_state_at(bible, 1).characters[character.id]
    after_both = derive_state(bible).characters[character.id]
    assert after_first.intimacies[0].strength == "minor"
    assert after_both.intimacies[0].strength == "major"

    explained = explain_intimacies(bible, character.id)
    assert explained[intimacy.id].rank == "major"
    assert explained[intimacy.id].distance_to_promote is not None
