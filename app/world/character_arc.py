"""Derive a character's state changes across a timeline window.

Pure function over the Story Bible: start state is taken *before* the start
event, end state *after* the end event, and transitions list only those events
in the inclusive window that carry a signal for the character. See
``docs/story_bible_model.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.world.evidence import IntimacyEvidenceTrack, RankState, format_threshold_distance
from app.world.models import (
    AddIntimacy,
    CharacterStateEffect,
    Event,
    Intimacy,
    IntimacyEvidence,
    SetIntimacyStrength,
    Signal,
    StoryBible,
    UpdateIntimacy,
)
from app.world.relations import chronological_order, scenario_ids
from app.world.replay import (
    DerivedCharacterState,
    SignalFoldContext,
    apply_signal_to_intimacies,
    derive_state_at,
    explain_intimacies_at,
    intimacy_tracks_from_baselines,
)

_STRENGTH_ORDER = {"dormant": -1, "minor": 0, "moderate": 1, "major": 2, "defining": 3}


@dataclass(frozen=True)
class CharacterArcTransition:
    """One window event that carries a signal for the character."""

    event_id: str
    title: str
    description: str
    signal_text: str
    changes: tuple[str, ...]


@dataclass(frozen=True)
class CharacterArc:
    """A character's derived state entering and leaving a timeline window."""

    character_id: str
    start_state: DerivedCharacterState
    transitions: tuple[CharacterArcTransition, ...]
    end_state: DerivedCharacterState
    start_ranks: dict[str, RankState] = field(default_factory=dict)
    end_ranks: dict[str, RankState] = field(default_factory=dict)


def derive_character_arc(
    bible: StoryBible,
    character_id: str,
    start_event_id: str | None = None,
    end_event_id: str | None = None,
) -> CharacterArc:
    """Derive start state, in-window transitions, and end state for a character.

    ``start_event_id`` / ``end_event_id`` of ``None`` or blank mean the start of
    the timeline (baseline) and the end of the timeline (full replay). The
    window is inclusive of both endpoints. Raises ``ValueError`` if the
    character is missing, an event id is not on the timeline, or start is
    chronologically after end.
    """

    if bible.get_character(character_id) is None:
        msg = f"Character not found: {character_id}"
        raise ValueError(msg)

    ordered = chronological_order(bible)
    start_id = _optional_event_id(start_event_id)
    end_id = _optional_event_id(end_event_id)

    if not ordered:
        baseline = _character_state(bible, character_id, 0)
        empty_ranks = explain_intimacies_at(bible, character_id, 0)
        return CharacterArc(
            character_id=character_id,
            start_state=baseline,
            transitions=(),
            end_state=baseline,
            start_ranks=empty_ranks,
            end_ranks=empty_ranks,
        )

    start_index = _event_index(ordered, start_id) if start_id is not None else 0
    end_index = _event_index(ordered, end_id) if end_id is not None else len(ordered) - 1

    if start_index > end_index:
        msg = f"Start event '{start_id}' is after end event '{end_id}' on the timeline."
        raise ValueError(msg)

    start_state = _character_state(bible, character_id, start_index)
    end_state = _character_state(bible, character_id, end_index + 1)
    intimacies = [
        intimacy.model_copy(deep=True)
        for intimacy in _character_state(bible, character_id, 0).intimacies
    ]
    tracks = intimacy_tracks_from_baselines(bible)
    scenarios = scenario_ids(bible)
    transitions: list[CharacterArcTransition] = []
    for index, event in enumerate(ordered[: end_index + 1]):
        in_window = start_index <= index <= end_index
        transition = _transition_for_event(
            event,
            character_id,
            intimacies,
            chronological_index=index,
            scenario_id=scenarios.get(event.id, event.id),
            tracks=tracks,
            record=in_window,
        )
        if transition is not None:
            transitions.append(transition)
    return CharacterArc(
        character_id=character_id,
        start_state=start_state,
        transitions=tuple(transitions),
        end_state=end_state,
        start_ranks=explain_intimacies_at(bible, character_id, start_index),
        end_ranks=explain_intimacies_at(bible, character_id, end_index + 1),
    )


def format_character_arc(arc: CharacterArc) -> str:
    """Render an arc as markdown with start, transitions, and end sections."""

    lines = [
        "### State at start",
        "",
        *_state_lines(arc.start_state, arc.start_ranks),
        "",
        "### Transitions",
        "",
    ]
    if not arc.transitions:
        lines.append("(none)")
    else:
        for index, transition in enumerate(arc.transitions):
            if index:
                lines.append("")
            lines.extend(_transition_lines(transition))
    lines.extend(["", "### State at end", "", *_state_lines(arc.end_state, arc.end_ranks)])
    return "\n".join(lines)


def _optional_event_id(event_id: str | None) -> str | None:
    if event_id is None:
        return None
    stripped = event_id.strip()
    return stripped or None


def _event_index(ordered: list[Event], event_id: str) -> int:
    try:
        return next(index for index, event in enumerate(ordered) if event.id == event_id)
    except StopIteration:
        msg = f"Event not found on timeline: {event_id}"
        raise ValueError(msg) from None


def _character_state(
    bible: StoryBible,
    character_id: str,
    event_count: int,
) -> DerivedCharacterState:
    derived = derive_state_at(bible, event_count).characters[character_id]
    return derived.model_copy(deep=True)


def _transition_for_event(
    event: Event,
    character_id: str,
    intimacies: list[Intimacy],
    *,
    chronological_index: int,
    scenario_id: str,
    tracks: dict[tuple[str, str], IntimacyEvidenceTrack],
    record: bool,
) -> CharacterArcTransition | None:
    signals = [signal for signal in event.signals if signal.character_id == character_id]
    if not signals:
        return None

    changes: list[str] = []
    interpretations: list[str] = []
    for signal in signals:
        if signal.interpretation:
            interpretations.append(signal.interpretation)
        context = SignalFoldContext(
            character_id=character_id,
            event_id=event.id,
            chronological_index=chronological_index,
            scenario_id=scenario_id,
            tracks=tracks,
        )
        described = _describe_and_apply_signal(signal, intimacies, context)
        if record:
            changes.extend(described)

    if not record:
        return None
    return CharacterArcTransition(
        event_id=event.id,
        title=event.title,
        description=event.description,
        signal_text="\n".join(interpretations),
        changes=tuple(changes),
    )


def _describe_and_apply_signal(
    signal: Signal,
    intimacies: list[Intimacy],
    context: SignalFoldContext,
) -> list[str]:
    descriptions = [_describe_effect(effect, intimacies) for effect in signal.effects]
    rank_states = apply_signal_to_intimacies(intimacies, signal, context)
    descriptions.extend(_describe_evidence(entry, intimacies) for entry in signal.evidence)
    seen = {entry.intimacy_id for entry in signal.evidence}
    for state in rank_states:
        if state.intimacy_id not in seen:
            continue
        if not state.crossings:
            continue
        crossing = state.crossings[-1]
        if crossing.event_id != context.event_id:
            continue
        current = _find_intimacy(intimacies, state.intimacy_id)
        label = current.text if current is not None and current.text else state.intimacy_id
        descriptions.append(
            f"Derived rank {label}: {crossing.previous_rank} to {crossing.new_rank}"
        )
    return descriptions


def _describe_effect(effect: CharacterStateEffect, intimacies: list[Intimacy]) -> str:
    if isinstance(effect, AddIntimacy):
        intimacy = effect.intimacy
        return f"Added intimacy {intimacy.text} ({intimacy.strength})"

    current = _find_intimacy(intimacies, effect.intimacy_id)
    label = current.text if current is not None and current.text else effect.intimacy_id

    if isinstance(effect, SetIntimacyStrength):
        verb = _strength_verb(current.strength if current is not None else None, effect.strength)
        if verb == "Set":
            return f"Set intimacy {label} strength to {effect.strength}"
        return f"{verb} {label} to {effect.strength}"

    if isinstance(effect, UpdateIntimacy):
        return f"Updated intimacy {label} to {effect.text}"

    return f"Eroded intimacy {label} to dormant"


def _describe_evidence(entry: IntimacyEvidence, intimacies: list[Intimacy]) -> str:
    current = _find_intimacy(intimacies, entry.intimacy_id)
    label = current.text if current is not None and current.text else entry.intimacy_id
    return f"Evidence {entry.direction} {label} (strength {entry.strength})"


def _strength_verb(previous: str | None, new: str) -> str:
    if previous is None:
        return "Set"
    previous_rank = _STRENGTH_ORDER.get(previous, 0)
    new_rank = _STRENGTH_ORDER.get(new, 0)
    if new_rank > previous_rank:
        return "Strengthened"
    if new_rank < previous_rank:
        return "Weakened"
    return "Set"


def _find_intimacy(intimacies: list[Intimacy], intimacy_id: str) -> Intimacy | None:
    return next((intimacy for intimacy in intimacies if intimacy.id == intimacy_id), None)


def _state_lines(
    state: DerivedCharacterState,
    ranks: dict[str, RankState] | None = None,
) -> list[str]:
    lines = ["Intimacies:"]
    if not state.intimacies:
        lines.append("(none)")
        return lines
    for intimacy in state.intimacies:
        line = f"- {intimacy.text} ({intimacy.strength}) [id: {intimacy.id}]"
        explanation = (ranks or {}).get(intimacy.id)
        if explanation is not None:
            line = f"{line} -- {format_threshold_distance(explanation)}"
        lines.append(line)
    return lines


def _transition_lines(transition: CharacterArcTransition) -> list[str]:
    heading = transition.title or "Untitled"
    lines = [f"#### {heading} [{transition.event_id}]"]
    if transition.description:
        lines.extend(["", transition.description])
    lines.extend(["", f"Signal: {transition.signal_text or '-'}"])
    if transition.changes:
        lines.append("")
        lines.extend(f"- {change}" for change in transition.changes)
    return lines
