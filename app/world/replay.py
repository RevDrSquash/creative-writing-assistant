"""Replay engine: derive world and character state at any timeline position.

Replay is a pure function over the Story Bible. It folds each event's
world-state effects and each signal's character-state effects over the
editable baselines, in chronological order (graph-derived with list tie-break).
Effects that reference missing entries or intimacies are skipped silently;
``effect_diagnostics`` surfaces those dangling references as warnings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.world.models import (
    AddIntimacy,
    AddWorldStateEntry,
    CharacterStateEffect,
    Intimacy,
    RemoveIntimacy,
    RemoveWorldStateEntry,
    SetIntimacyStrength,
    Signal,
    StoryBible,
    UpdateIntimacy,
    UpdateWorldStateEntry,
    WorldStateEffect,
    WorldStateEntry,
)
from app.world.relations import chronological_order


class DerivedCharacterState(BaseModel):
    """A character's state after replaying the timeline to a position."""

    character_id: str
    name: str = ""
    intimacies: list[Intimacy] = Field(default_factory=list)


class DerivedState(BaseModel):
    """World state plus per-character state at a timeline position."""

    events_applied: int = 0
    world_state: list[WorldStateEntry] = Field(default_factory=list)
    characters: dict[str, DerivedCharacterState] = Field(default_factory=dict)


EffectDiagnosticKind = Literal["dangling_effect"]


@dataclass(frozen=True)
class EffectDiagnostic:
    """A derived warning about an effect that references missing state."""

    kind: EffectDiagnosticKind
    event_id: str
    message: str


def derive_state(bible: StoryBible, up_to_event_id: str | None = None) -> DerivedState:
    """Derive state after applying the timeline up to and including an event.

    ``up_to_event_id=None`` replays the full timeline. Raises ``ValueError``
    if the event id is not on the timeline.
    """

    ordered = chronological_order(bible)
    if up_to_event_id is None:
        return derive_state_at(bible, len(ordered))

    try:
        index = next(index for index, event in enumerate(ordered) if event.id == up_to_event_id)
    except StopIteration:
        msg = f"Event not found on timeline: {up_to_event_id}"
        raise ValueError(msg) from None
    return derive_state_at(bible, index + 1)


def derive_state_at(bible: StoryBible, event_count: int) -> DerivedState:
    """Derive state after applying the first ``event_count`` chronological events.

    ``event_count=0`` returns the baselines unchanged.
    """

    ordered = chronological_order(bible)
    event_count = max(0, min(event_count, len(ordered)))

    world_state = [entry.model_copy(deep=True) for entry in bible.baseline_world_state]
    characters = {
        character.id: DerivedCharacterState(
            character_id=character.id,
            name=character.identity.name,
            intimacies=[
                intimacy.model_copy(deep=True) for intimacy in character.baseline_state.intimacies
            ],
        )
        for character in bible.characters
    }

    for event in ordered[:event_count]:
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


def effect_diagnostics(bible: StoryBible) -> list[EffectDiagnostic]:
    """Return warnings for effects that target state not present at replay time."""

    ordered = chronological_order(bible)
    diagnostics: list[EffectDiagnostic] = []

    world_state_ids: set[str] = {entry.id for entry in bible.baseline_world_state}
    character_intimacy_ids: dict[str, set[str]] = {
        character.id: {intimacy.id for intimacy in character.baseline_state.intimacies}
        for character in bible.characters
    }

    # Track when each id is first added across the full timeline.
    first_world_add: dict[str, str] = {}
    first_intimacy_add: dict[str, tuple[str, str]] = {}  # intimacy_id -> (character_id, event_id)

    for event in ordered:
        for world_effect in event.world_state_effects:
            if isinstance(world_effect, AddWorldStateEntry):
                entry_id = world_effect.entry.id
                if entry_id not in first_world_add:
                    first_world_add[entry_id] = event.id
        for signal in event.signals:
            for effect in signal.effects:
                if isinstance(effect, AddIntimacy):
                    intimacy_id = effect.intimacy.id
                    if intimacy_id not in first_intimacy_add:
                        first_intimacy_add[intimacy_id] = (signal.character_id, event.id)

    for event in ordered:
        event_label = event.title or event.id

        for world_effect in event.world_state_effects:
            diagnostic = _world_effect_diagnostic(
                event.id,
                event_label,
                world_effect,
                world_state_ids,
                first_world_add,
            )
            if diagnostic is not None:
                diagnostics.append(diagnostic)
            _track_world_effect(world_effect, world_state_ids)

        for signal in event.signals:
            intimacy_ids = character_intimacy_ids.setdefault(signal.character_id, set())
            for effect in signal.effects:
                diagnostic = _character_effect_diagnostic(
                    event.id,
                    event_label,
                    signal.character_id,
                    effect,
                    intimacy_ids,
                    first_intimacy_add,
                )
                if diagnostic is not None:
                    diagnostics.append(diagnostic)
                _track_character_effect(effect, intimacy_ids)

    return diagnostics


def format_effect_diagnostics(diagnostics: list[EffectDiagnostic]) -> str:
    if not diagnostics:
        return ""
    return "Warnings: " + "; ".join(item.message for item in diagnostics)


def _world_effect_diagnostic(
    event_id: str,
    event_label: str,
    effect: WorldStateEffect,
    present_ids: set[str],
    first_add: dict[str, str],
) -> EffectDiagnostic | None:
    if isinstance(effect, AddWorldStateEntry):
        return None

    entry_id = effect.entry_id
    if entry_id in present_ids:
        return None

    first_event_id = first_add.get(entry_id)
    if first_event_id is not None:
        detail = f"first added at event '{first_event_id}' (later in chronological order)"
    else:
        detail = "never added on the timeline"

    op = "update_entry" if isinstance(effect, UpdateWorldStateEntry) else "remove_entry"
    return EffectDiagnostic(
        kind="dangling_effect",
        event_id=event_id,
        message=(
            f"Event '{event_label}' [{event_id}]: world-state {op} targets "
            f"entry '{entry_id}' which is not present ({detail})."
        ),
    )


def _character_effect_diagnostic(
    event_id: str,
    event_label: str,
    character_id: str,
    effect: CharacterStateEffect,
    present_ids: set[str],
    first_add: dict[str, tuple[str, str]],
) -> EffectDiagnostic | None:
    if isinstance(effect, AddIntimacy):
        return None

    intimacy_id = effect.intimacy_id
    if intimacy_id in present_ids:
        return None

    first = first_add.get(intimacy_id)
    if first is not None:
        first_character_id, first_event_id = first
        if first_character_id == character_id:
            detail = f"first added at event '{first_event_id}' (later in chronological order)"
        else:
            detail = (
                f"first added for character '{first_character_id}' at event "
                f"'{first_event_id}' (different character)"
            )
    else:
        detail = "never added on the timeline"

    if isinstance(effect, SetIntimacyStrength):
        op = "set_intimacy_strength"
    elif isinstance(effect, UpdateIntimacy):
        op = "update_intimacy"
    else:
        op = "remove_intimacy"

    return EffectDiagnostic(
        kind="dangling_effect",
        event_id=event_id,
        message=(
            f"Event '{event_label}' [{event_id}]: {op} on character '{character_id}' "
            f"targets intimacy '{intimacy_id}' which is not present ({detail})."
        ),
    )


def _track_world_effect(effect: WorldStateEffect, present_ids: set[str]) -> None:
    if isinstance(effect, AddWorldStateEntry):
        present_ids.add(effect.entry.id)
    elif isinstance(effect, RemoveWorldStateEntry):
        present_ids.discard(effect.entry_id)


def _track_character_effect(effect: CharacterStateEffect, present_ids: set[str]) -> None:
    if isinstance(effect, AddIntimacy):
        present_ids.add(effect.intimacy.id)
    elif isinstance(effect, RemoveIntimacy):
        present_ids.discard(effect.intimacy_id)


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
        if isinstance(effect, AddIntimacy):
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
