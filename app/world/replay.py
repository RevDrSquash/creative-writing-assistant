"""Replay engine: derive world and character state at any timeline position.

Replay is a pure function over the Story Bible. It folds each event's
world-state effects and each signal's character-state effects over the
editable baselines, in timeline order. Effects that reference missing entries,
intimacies, or characters are skipped silently; conflict detection is planned
future work (see ``docs/story_bible_model.md``).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.world.models import (
    AddIntimacy,
    AddWorldStateEntry,
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
    WorldStateEffect,
    WorldStateEntry,
)


class DerivedCharacterState(BaseModel):
    """A character's state after replaying the timeline to a position."""

    character_id: str
    name: str = ""
    goal: str = ""
    status: str = ""
    intimacies: list[Intimacy] = Field(default_factory=list)


class DerivedState(BaseModel):
    """World state plus per-character state at a timeline position."""

    events_applied: int = 0
    world_state: list[WorldStateEntry] = Field(default_factory=list)
    characters: dict[str, DerivedCharacterState] = Field(default_factory=dict)


def derive_state(bible: StoryBible, up_to_event_id: str | None = None) -> DerivedState:
    """Derive state after applying the timeline up to and including an event.

    ``up_to_event_id=None`` replays the full timeline. Raises ``ValueError``
    if the event id is not on the timeline.
    """

    if up_to_event_id is None:
        return derive_state_at(bible, len(bible.timeline))

    index = bible.event_index(up_to_event_id)
    if index is None:
        msg = f"Event not found on timeline: {up_to_event_id}"
        raise ValueError(msg)
    return derive_state_at(bible, index + 1)


def derive_state_at(bible: StoryBible, event_count: int) -> DerivedState:
    """Derive state after applying the first ``event_count`` timeline events.

    ``event_count=0`` returns the baselines unchanged.
    """

    event_count = max(0, min(event_count, len(bible.timeline)))

    world_state = [entry.model_copy(deep=True) for entry in bible.baseline_world_state]
    characters = {
        character.id: DerivedCharacterState(
            character_id=character.id,
            name=character.identity.name,
            goal=character.baseline_state.goal,
            status=character.baseline_state.status,
            intimacies=[
                intimacy.model_copy(deep=True) for intimacy in character.baseline_state.intimacies
            ],
        )
        for character in bible.characters
    }

    for event in bible.timeline[:event_count]:
        for world_effect in event.world_state_effects:
            _apply_world_state_effect(world_state, world_effect)
        for signal in event.signals:
            character = characters.get(signal.character_id)
            if character is None:
                continue
            _apply_signal(character, signal)

    return DerivedState(
        events_applied=event_count,
        world_state=world_state,
        characters=characters,
    )


def _apply_world_state_effect(
    world_state: list[WorldStateEntry],
    effect: WorldStateEffect,
) -> None:
    if isinstance(effect, AddWorldStateEntry):
        world_state.append(effect.entry.model_copy(deep=True))
        return

    if isinstance(effect, UpdateWorldStateEntry):
        entry = _find_entry(world_state, effect.entry_id)
        if entry is None:
            return
        if effect.text is not None:
            entry.text = effect.text
        if effect.kind is not None:
            entry.kind = effect.kind
        return

    if isinstance(effect, RemoveWorldStateEntry):
        world_state[:] = [entry for entry in world_state if entry.id != effect.entry_id]


def _apply_signal(character: DerivedCharacterState, signal: Signal) -> None:
    for effect in signal.effects:
        if isinstance(effect, SetGoal):
            character.goal = effect.goal
        elif isinstance(effect, SetStatus):
            character.status = effect.status
        elif isinstance(effect, AddIntimacy):
            character.intimacies.append(effect.intimacy.model_copy(deep=True))
        elif isinstance(effect, SetIntimacyStrength):
            intimacy = _find_intimacy(character.intimacies, effect.intimacy_id)
            if intimacy is not None:
                intimacy.strength = effect.strength
        elif isinstance(effect, UpdateIntimacy):
            intimacy = _find_intimacy(character.intimacies, effect.intimacy_id)
            if intimacy is not None:
                intimacy.text = effect.text
        elif isinstance(effect, RemoveIntimacy):
            character.intimacies[:] = [
                intimacy for intimacy in character.intimacies if intimacy.id != effect.intimacy_id
            ]


def _find_entry(entries: list[WorldStateEntry], entry_id: str) -> WorldStateEntry | None:
    return next((entry for entry in entries if entry.id == entry_id), None)


def _find_intimacy(intimacies: list[Intimacy], intimacy_id: str) -> Intimacy | None:
    return next((intimacy for intimacy in intimacies if intimacy.id == intimacy_id), None)
