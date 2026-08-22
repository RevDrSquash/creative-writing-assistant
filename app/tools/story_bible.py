"""Agent tools for reading and editing the structured Story Bible.

These are simple per-entity CRUD primitives; review workflows (intimacy
deduplication, signal-driven updates) are layered on top in later phases.
All write tools run inside a world transaction: the mutation and save are
serialized against other writers, and the in-memory mutation is rolled back
if the save fails, so memory and disk never diverge.
"""

from __future__ import annotations

import json

from langchain_core.tools import ToolException, tool

from app.world.character_arc import CharacterArc, derive_character_arc, format_character_arc
from app.world.evidence import RankState, format_threshold_distance
from app.world.models import (
    AddIntimacy,
    Character,
    Event,
    EventRelation,
    EventRelationKind,
    EventRelationSpec,
    Intimacy,
    Signal,
    StoryBible,
    WorldFact,
    WorldStateEffect,
    WorldStateEntry,
    WorldStateKind,
    unique_slug,
)
from app.world.relations import (
    RelationValidationError,
    chronological_order,
    diagnostics_for_relation,
    format_diagnostics,
    normalize_relation,
    relation_diagnostics,
)
from app.world.replay import (
    DerivedCharacterState,
    derive_state,
    effect_diagnostics,
    explain_intimacies,
    format_effect_diagnostics,
)
from app.world.scene import enacting_scenes, prune_event_links
from app.world.store import get_world, world_transaction


@tool
def read_story_bible() -> str:
    """Return an overview of the story bible: narrative style, world facts,
    baseline world state, characters, and the event timeline, with entity ids.

    Use the ids with the more specific read/update tools.
    """

    world = get_world()
    bible = world.story_bible
    lines = ["# Story Bible Overview", ""]

    lines.append("## Narrative Style")
    for label, value in (
        ("Premise", bible.premise),
        ("Tone", bible.tone),
        ("Themes", bible.themes),
        ("Writing style", bible.writing_style),
    ):
        text = value.strip()
        lines.append(f"### {label}")
        lines.append(text if text else "(not set)")

    lines.append("")
    lines.append("## World Facts")
    if not bible.world_facts:
        lines.append("(none)")
    for fact in bible.world_facts:
        tags = f" tags: {', '.join(fact.tags)}" if fact.tags else ""
        lines.append(f"- {fact.title or 'Untitled'} [id: {fact.id}]{tags}")

    lines.append("")
    lines.append("## Baseline World State")
    if not bible.baseline_world_state:
        lines.append("(none)")
    for entry in bible.baseline_world_state:
        lines.append(f"- ({entry.kind}) {entry.text} [id: {entry.id}]")

    lines.append("")
    lines.append("## Characters")
    if not bible.characters:
        lines.append("(none)")
    for character in bible.characters:
        lines.append(f"- {character.identity.name or 'Unnamed'} [id: {character.id}]")

    lines.append("")
    ordered = chronological_order(bible)
    lines.append(f"## Timeline ({len(ordered)} events)")
    for position, event in enumerate(ordered, start=1):
        signal_count = len(event.signals)
        relation_summary = _event_relation_summary(bible, event.id)
        summary_suffix = f" ({signal_count} signals"
        if relation_summary:
            summary_suffix += f", {relation_summary}"
        summary_suffix += ")"
        lines.append(f"{position}. {event.title or 'Untitled'} [id: {event.id}]{summary_suffix}")

    _append_timeline_warnings(lines, bible, world)

    return "\n".join(lines)


@tool
def update_narrative_style(
    premise: str | None = None,
    tone: str | None = None,
    themes: str | None = None,
    writing_style: str | None = None,
) -> str:
    """Update narrative style fields (premise, tone, themes, writing style).

    Only the provided fields change; omit a field to leave it unchanged.
    """

    with world_transaction() as world:
        bible = world.story_bible
        updates = {
            "premise": premise,
            "tone": tone,
            "themes": themes,
            "writing_style": writing_style,
        }
        for field, value in updates.items():
            if value is not None:
                setattr(bible, field, value)
    return "Updated narrative style."


@tool
def read_world_fact(fact_id: str) -> str:
    """Return the full text and tags of a world fact."""

    fact = get_world().story_bible.get_world_fact(fact_id)
    if fact is None:
        raise ToolException(f"No world fact with id {fact_id}.")
    tags = f"\nTags: {', '.join(fact.tags)}" if fact.tags else ""
    return f"# {fact.title or 'Untitled'} [id: {fact.id}]{tags}\n\n{fact.text}"


@tool
def upsert_world_fact(
    title: str,
    text: str,
    fact_id: str = "",
    tags: list[str] | None = None,
) -> str:
    """Create a world fact, or fully update one when `fact_id` is given.

    World facts are stable setting facts; locations and lore belong here.
    Ids are generated by the system: omit `fact_id` to create a new fact, and
    only pass a `fact_id` previously returned by read_story_bible or this tool.
    """

    with world_transaction() as world:
        bible = world.story_bible
        if fact_id:
            fact = bible.get_world_fact(fact_id)
            if fact is None:
                raise ToolException(
                    f"No world fact with id {fact_id}. Omit fact_id to create a new fact, "
                    "or call read_story_bible to list existing fact ids."
                )
            fact.title = title
            fact.text = text
            if tags is not None:
                fact.tags = tags
            action = "Updated"
        else:
            fact = WorldFact(title=title, text=text, tags=tags or [])
            fact.id = unique_slug(
                "fact_",
                title,
                {item.id for item in bible.world_facts},
            )
            bible.world_facts.append(fact)
            action = "Created"
    return f"{action} world fact '{fact.title}' (id: {fact.id})."


@tool
def delete_world_fact(fact_id: str) -> str:
    """Delete a world fact permanently."""

    with world_transaction() as world:
        bible = world.story_bible
        fact = bible.get_world_fact(fact_id)
        if fact is None:
            raise ToolException(f"No world fact with id {fact_id}.")
        bible.world_facts = [item for item in bible.world_facts if item.id != fact_id]
    return f"Deleted world fact '{fact.title}' (id: {fact_id})."


@tool
def upsert_world_state_entry(
    text: str,
    kind: WorldStateKind = "thread",
    entry_id: str = "",
) -> str:
    """Create or update a baseline world-state entry (pressure, thread, or
    consequence in effect before any timeline events).

    Mid-story world-state changes belong on events as world-state effects,
    not in the baseline. Ids are generated by the system: omit `entry_id` to
    create a new entry, and only pass an `entry_id` from read_story_bible.
    """

    with world_transaction() as world:
        bible = world.story_bible
        if entry_id:
            entry = next(
                (item for item in bible.baseline_world_state if item.id == entry_id),
                None,
            )
            if entry is None:
                raise ToolException(
                    f"No baseline world-state entry with id {entry_id}. Omit entry_id to "
                    "create a new entry, or call read_story_bible to list existing ids."
                )
            entry.text = text
            entry.kind = kind
            action = "Updated"
        else:
            entry = WorldStateEntry(text=text, kind=kind)
            entry.id = unique_slug(
                "wse_",
                text,
                {item.id for item in bible.baseline_world_state},
            )
            bible.baseline_world_state.append(entry)
            action = "Created"
    return f"{action} baseline world-state entry (id: {entry.id})."


@tool
def delete_world_state_entry(entry_id: str) -> str:
    """Delete a baseline world-state entry permanently."""

    with world_transaction() as world:
        bible = world.story_bible
        entry = next((item for item in bible.baseline_world_state if item.id == entry_id), None)
        if entry is None:
            raise ToolException(f"No baseline world-state entry with id {entry_id}.")
        bible.baseline_world_state = [
            item for item in bible.baseline_world_state if item.id != entry_id
        ]
    return f"Deleted baseline world-state entry (id: {entry_id})."


@tool
def read_character(
    character_id: str,
    start_event_id: str = "",
    end_event_id: str = "",
) -> str:
    """Return a character's identity, baseline state, and derived state.

    By default, derived state is after the full timeline. When start_event_id
    and/or end_event_id are given, that current-state section is replaced by a
    scoped arc: state entering the window (before the start event), transitions
    during the inclusive window, and state after the end event. Late-story
    state is not included when a window is set.
    """

    bible = get_world().story_bible
    character = _require_character(bible, character_id)

    identity = character.identity
    baseline = character.baseline_state
    lines = [
        f"# {identity.name or 'Unnamed'} [id: {character.id}]",
        "",
        "## Identity",
        f"Traits: {identity.traits or '-'}",
        f"Appearance: {identity.appearance or '-'}",
        f"Background: {identity.background or '-'}",
        f"Voice: {identity.voice or '-'}",
        "",
        "## Baseline State (start of timeline)",
        "Intimacies:",
        *_intimacy_lines(baseline.intimacies),
        "",
    ]
    if start_event_id.strip() or end_event_id.strip():
        arc = _character_arc_or_raise(bible, character.id, start_event_id, end_event_id)
        lines.append(format_character_arc(arc))
    else:
        lines.append("## Current State (after full timeline)")
        derived = derive_state(bible).characters.get(character.id)
        if derived is not None:
            lines.extend(
                _derived_character_lines(
                    derived,
                    explain_intimacies(bible, character.id),
                )
            )
    return "\n".join(lines)


@tool
def read_character_arc(
    character_id: str,
    start_event_id: str = "",
    end_event_id: str = "",
) -> str:
    """Return a character's derived state entering and leaving a timeline window.

    Start state is the character entering the window (before the start event;
    baseline when start_event_id is omitted). End state is after the end event
    (full timeline when end_event_id is omitted). The window is inclusive of
    both endpoints. Transitions list only events in the window that carry a
    signal for this character.
    """

    bible = get_world().story_bible
    character = _require_character(bible, character_id)
    arc = _character_arc_or_raise(bible, character.id, start_event_id, end_event_id)
    name = character.identity.name or "Unnamed"
    return f"# {name} [id: {character.id}]\n\n{format_character_arc(arc)}"


@tool
def upsert_character(
    character_id: str = "",
    name: str | None = None,
    traits: str | None = None,
    appearance: str | None = None,
    background: str | None = None,
    voice: str | None = None,
    intimacies: list[Intimacy] | None = None,
) -> str:
    """Create a character, or partially update one when `character_id` is given.

    Only the provided fields change. `intimacies` sets the character's BASELINE
    state (start of timeline); mid-story changes belong on events as signals.
    `intimacies` replaces the whole baseline intimacy list, so read the
    character first and resend the full list when editing it.
    Ids are generated by the system: omit `character_id` to create a new
    character, and only pass a `character_id` from read_story_bible.
    """

    with world_transaction() as world:
        bible = world.story_bible
        if character_id:
            character = bible.get_character(character_id)
            if character is None:
                raise ToolException(
                    f"No character with id {character_id}. Omit character_id to create a "
                    "new character, or call read_story_bible to list existing ids."
                )
            action = "Updated"
        else:
            character = Character()
            character.id = unique_slug(
                "char_",
                name or "",
                {item.id for item in bible.characters},
            )
            bible.characters.append(character)
            action = "Created"

        identity_updates = {
            "name": name,
            "traits": traits,
            "appearance": appearance,
            "background": background,
            "voice": voice,
        }
        for field, value in identity_updates.items():
            if value is not None:
                setattr(character.identity, field, value)
        if intimacies is not None:
            character.baseline_state.intimacies = intimacies

    return f"{action} character '{character.identity.name or 'Unnamed'}' (id: {character.id})."


@tool
def delete_character(character_id: str) -> str:
    """Delete a character permanently.

    Events keep any signals that reference the character; replay skips them.
    """

    with world_transaction() as world:
        bible = world.story_bible
        character = bible.get_character(character_id)
        if character is None:
            raise ToolException(f"No character with id {character_id}.")
        bible.characters = [item for item in bible.characters if item.id != character_id]
    return f"Deleted character '{character.identity.name or 'Unnamed'}' (id: {character_id})."


@tool
def read_timeline() -> str:
    """Return the ordered event timeline with ids, placement, and signal counts."""

    world = get_world()
    bible = world.story_bible
    ordered = chronological_order(bible)
    if not ordered:
        return "The timeline has no events yet."
    lines = []
    for position, event in enumerate(ordered, start=1):
        description = f" - {event.description}" if event.description else ""
        relation_summary = _event_relation_summary(bible, event.id)
        relation_part = f", {relation_summary}" if relation_summary else ""
        placement = _format_event_placement(world, event.id)
        lines.append(
            f"{position}. {event.title or 'Untitled'} [id: {event.id}] "
            f"({placement}; {len(event.signals)} signals{relation_part}){description}"
        )

    _append_timeline_warnings(lines, bible, world)

    return "\n".join(lines)


@tool
def read_event(event_id: str) -> str:
    """Return an event's description, placement, world-state effects, and signals."""

    world = get_world()
    bible = world.story_bible
    event = bible.get_event(event_id)
    if event is None:
        raise ToolException(f"No event with id {event_id}.")

    chron_index = _chronological_event_index(bible, event.id)
    lines = [
        f"# Event {chron_index + 1}: {event.title or 'Untitled'} [id: {event.id}]",
        "",
        event.description or "(no description)",
        "",
        "## Scene Placement",
        _format_event_placement(world, event.id),
    ]
    related_scenes = _scenes_related_to_event(world, event.id)
    if related_scenes:
        lines.append("")
        lines.append("Related by scene blueprints (context only):")
        for scene in related_scenes:
            lines.append(f"- '{scene.title}' [scene id: {scene.id}]")

    lines.extend(["", "## World State Effects"])
    if not event.world_state_effects:
        lines.append("(none)")
    for effect in event.world_state_effects:
        lines.append(f"- {json.dumps(effect.model_dump(mode='json'))}")

    lines.append("")
    lines.append("## Signals")
    if not event.signals:
        lines.append("(none)")
    for signal in event.signals:
        character = bible.get_character(signal.character_id)
        name = character.identity.name if character else f"unknown ({signal.character_id})"
        lines.append(f"- {name} [signal id: {signal.id}]: {signal.interpretation or '-'}")
        for entry in signal.evidence:
            lines.append(f"  - evidence {json.dumps(entry.model_dump(mode='json'))}")
        for effect in signal.effects:
            lines.append(f"  - {json.dumps(effect.model_dump(mode='json'))}")

    relations = bible.relations_for_event(event.id)
    lines.append("")
    lines.append("## Relationships")
    if not relations.incoming and not relations.outgoing and not relations.concurrent:
        lines.append("(none)")
    for relation in relations.outgoing:
        other = bible.get_event(relation.target_id)
        title = other.title if other else relation.target_id
        lines.append(
            f"- {relation.kind} '{title}' [id: {relation.target_id}] [relation id: {relation.id}]"
        )
        warning = format_diagnostics(diagnostics_for_relation(bible, relation.id))
        if warning:
            lines.append(f"  {warning}")
    for relation in relations.incoming:
        other = bible.get_event(relation.source_id)
        title = other.title if other else relation.source_id
        lines.append(
            f"- '{title}' {relation.kind} this event [id: {relation.source_id}] "
            f"[relation id: {relation.id}]"
        )
        warning = format_diagnostics(diagnostics_for_relation(bible, relation.id))
        if warning:
            lines.append(f"  {warning}")
    for relation in relations.concurrent:
        other_id = relation.target_id if relation.source_id == event.id else relation.source_id
        other = bible.get_event(other_id)
        title = other.title if other else other_id
        lines.append(f"- during with '{title}' [id: {other_id}] [relation id: {relation.id}]")
        warning = format_diagnostics(diagnostics_for_relation(bible, relation.id))
        if warning:
            lines.append(f"  {warning}")

    effect_warnings = [
        item.message for item in effect_diagnostics(bible) if item.event_id == event.id
    ]
    if effect_warnings:
        lines.append("")
        lines.append("## Effect Warnings")
        for warning in effect_warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines)


@tool
def add_event(
    title: str,
    description: str = "",
    relations: list[EventRelationSpec] | None = None,
    world_state_effects: list[WorldStateEffect] | None = None,
    signals: list[Signal] | None = None,
) -> str:
    """Add an event to the timeline (appended in creation order).

    Events are atomic story facts at any scale — only plot-necessary facts belong on the
    timeline. If nothing in the story depends on a detail happening at a specific time, leave
    it to the prose. Do not create one event per scene or events for incidental detail.

    When other events already exist, ``relations`` is required: each entry links
    the new event to an existing one. For directed kinds (``follows``,
    ``directly_follows``, ``depends_on``) the new event is the later source and
    ``event_id`` is the earlier target. ``directly_follows`` marks tight
    moment-to-moment continuity; ``depends_on`` marks causal dependency;
    ``follows`` is loose chronology only. ``during`` marks concurrency with
    ``event_id``. Chronology is derived from relations; creation order breaks
    ties among unrelated events.

    ``world_state_effects`` are structured deltas to the active world state.
    ``signals`` describe how specific characters interpret the event and carry
    evidence entries (scored intimacy relationships) plus structural
    creation/rewording records.
    """

    with world_transaction() as world:
        bible = world.story_bible
        existing_events = len(bible.timeline)
        relation_specs = relations or []

        if existing_events > 0 and not relation_specs:
            kinds = ", ".join(("follows", "directly_follows", "depends_on", "during"))
            raise ToolException(
                "New events must link to existing ones when the timeline is not empty. "
                f"Pass `relations` with at least one entry (kinds: {kinds}). "
                f"{_event_listing(bible)}"
            )

        event = Event(
            title=title,
            description=description,
            world_state_effects=world_state_effects or [],
            signals=signals or [],
        )
        _validate_signal_character_ids(bible, event.signals)
        _validate_signal_evidence_ids(bible, event.signals)
        event.id = unique_slug(
            "event_",
            title,
            {item.id for item in bible.timeline},
        )
        bible.timeline.append(event)

        added_relations: list[EventRelation] = []
        for spec in relation_specs:
            try:
                normalized_source, normalized_target = normalize_relation(
                    bible,
                    spec.kind,
                    event.id,
                    spec.event_id,
                )
            except RelationValidationError as exc:
                raise ToolException(str(exc)) from exc
            relation = EventRelation(
                kind=spec.kind,
                source_id=normalized_source,
                target_id=normalized_target,
            )
            bible.event_relations.append(relation)
            added_relations.append(relation)

    relation_note = ""
    if added_relations:
        relation_note = f" Added {len(added_relations)} relation(s)."
    return f"Added event '{event.title}' (id: {event.id}).{relation_note}"


@tool
def update_event(
    event_id: str,
    title: str | None = None,
    description: str | None = None,
    world_state_effects: list[WorldStateEffect] | None = None,
    signals: list[Signal] | None = None,
) -> str:
    """Partially update an event; only provided fields change.

    `world_state_effects` and `signals` replace the whole respective list, so
    read the event first and resend the full list when editing them. To change
    chronology, use add_event_relation / remove_event_relation rather than
    moving the event in the timeline list.
    """

    with world_transaction() as world:
        bible = world.story_bible
        event = bible.get_event(event_id)
        if event is None:
            raise ToolException(f"No event with id {event_id}.")

        if title is not None:
            event.title = title
        if description is not None:
            event.description = description
        if world_state_effects is not None:
            event.world_state_effects = world_state_effects
        if signals is not None:
            _validate_signal_character_ids(bible, signals)
            _validate_signal_evidence_ids(bible, signals)
            event.signals = signals

    return f"Updated event '{event.title}' (id: {event.id})."


@tool
def add_event_relation(
    kind: EventRelationKind,
    source_id: str,
    target_id: str,
) -> str:
    """Add a typed relationship between two timeline events.

    Directed kinds use ``source_id`` as the later event and ``target_id`` as the
    earlier one. ``directly_follows`` is tight moment-to-moment continuity;
    ``depends_on`` is causal dependency; ``follows`` is loose chronology only.
    ``during`` marks concurrent events (unordered pair). Chronology is derived
    from directed edges (creation order breaks ties); cycles are rejected.
    """

    with world_transaction() as world:
        bible = world.story_bible
        try:
            normalized_source, normalized_target = normalize_relation(
                bible, kind, source_id, target_id
            )
        except RelationValidationError as exc:
            raise ToolException(str(exc)) from exc

        relation = EventRelation(
            kind=kind,
            source_id=normalized_source,
            target_id=normalized_target,
        )
        bible.event_relations.append(relation)

    warnings = format_diagnostics(diagnostics_for_relation(bible, relation.id))
    result = (
        f"Added {kind} relation from '{normalized_source}' to '{normalized_target}' "
        f"(relation id: {relation.id})."
    )
    if warnings:
        result = f"{result} {warnings}"
    return result


@tool
def remove_event_relation(relation_id: str) -> str:
    """Remove an event relationship by its relation id."""

    with world_transaction() as world:
        bible = world.story_bible
        relation = bible.get_event_relation(relation_id)
        if relation is None:
            raise ToolException(
                f"No event relation with id {relation_id}. "
                "Call read_event to list relation ids for an event."
            )
        bible.event_relations = [item for item in bible.event_relations if item.id != relation_id]
    return (
        f"Removed {relation.kind} relation "
        f"from '{relation.source_id}' to '{relation.target_id}' (id: {relation_id})."
    )


@tool
def delete_event(event_id: str) -> str:
    """Delete an event and its signals permanently.

    Also removes the event id from every scene blueprint that referenced it.
    """

    with world_transaction() as world:
        bible = world.story_bible
        event = bible.get_event(event_id)
        if event is None:
            raise ToolException(f"No event with id {event_id}.")
        affected_scene_ids = prune_event_links(world, event_id)
        bible.timeline = [item for item in bible.timeline if item.id != event_id]
        bible.event_relations = [
            item
            for item in bible.event_relations
            if item.source_id != event_id and item.target_id != event_id
        ]
    note = ""
    if affected_scene_ids:
        note = (
            f" Removed the event from {len(affected_scene_ids)} scene blueprint(s): "
            f"{', '.join(affected_scene_ids)}."
        )
    return f"Deleted event '{event.title or 'Untitled'}' (id: {event_id}).{note}"


@tool
def read_world_state(at_event_id: str = "") -> str:
    """Return the derived world state and character states at a timeline position.

    With `at_event_id`, derives state after that event has been applied;
    without it, derives state after the full timeline.
    """

    bible = get_world().story_bible
    try:
        derived = derive_state(bible, at_event_id or None)
    except ValueError as exc:
        raise ToolException(str(exc)) from exc

    lines = [
        f"# Derived State (after {derived.events_applied} of {len(bible.timeline)} events)",
        "",
        "## World State",
    ]
    if not derived.world_state:
        lines.append("(no active entries)")
    for entry in derived.world_state:
        lines.append(f"- ({entry.kind}) {entry.text} [id: {entry.id}]")

    for character in derived.characters.values():
        lines.append("")
        lines.append(f"## {character.name or 'Unnamed'} [id: {character.character_id}]")
        lines.extend(
            _derived_character_lines(
                character,
                explain_intimacies(bible, character.character_id, at_event_id or None),
            )
        )

    effect_warnings = format_effect_diagnostics(effect_diagnostics(bible))
    if effect_warnings:
        lines.append("")
        lines.append(effect_warnings)

    return "\n".join(lines)


def _require_character(bible: StoryBible, character_id: str) -> Character:
    character = bible.get_character(character_id)
    if character is None:
        raise ToolException(f"No character with id {character_id}. {_character_listing(bible)}")
    return character


def _character_arc_or_raise(
    bible: StoryBible,
    character_id: str,
    start_event_id: str,
    end_event_id: str,
) -> CharacterArc:
    try:
        return derive_character_arc(
            bible,
            character_id,
            start_event_id or None,
            end_event_id or None,
        )
    except ValueError as exc:
        raise ToolException(f"{exc} {_event_listing(bible)}") from exc


def _character_listing(bible: StoryBible) -> str:
    if not bible.characters:
        return "No characters exist yet; create one first."
    listing = ", ".join(
        f"{character.identity.name or 'Unnamed'} [{character.id}]" for character in bible.characters
    )
    return f"Valid characters: {listing}"


def _event_listing(bible: StoryBible) -> str:
    if not bible.timeline:
        return "No events exist yet."
    listing = ", ".join(f"{event.title or 'Untitled'} [{event.id}]" for event in bible.timeline)
    return f"Valid events: {listing}"


def _validate_signal_character_ids(bible: StoryBible, signals: list[Signal]) -> None:
    valid_characters = {
        character.id: character.identity.name or "Unnamed" for character in bible.characters
    }
    for signal in signals:
        if signal.character_id and signal.character_id not in valid_characters:
            if valid_characters:
                listing = ", ".join(
                    f"{name} [{character_id}]" for character_id, name in valid_characters.items()
                )
                detail = f"Valid characters: {listing}"
            else:
                detail = "No characters exist yet; create one first."
            raise ToolException(f"Unknown character_id '{signal.character_id}' in signal. {detail}")


def _validate_signal_evidence_ids(bible: StoryBible, signals: list[Signal]) -> None:
    """Resolve or reject evidence intimacy ids; never persist a dangling reference."""

    for signal in signals:
        extra_ids = [
            effect.intimacy.id
            for effect in signal.effects
            if isinstance(effect, AddIntimacy) and effect.intimacy.id
        ]
        catalog = dict(bible.intimacy_catalog(signal.character_id or None))
        for extra_id in extra_ids:
            if extra_id not in catalog:
                catalog[extra_id] = extra_id
        for entry in signal.evidence:
            if not entry.intimacy_id:
                raise ToolException(
                    f"Signal evidence is missing intimacy_id. {_intimacy_listing(catalog)}"
                )
            match = bible.resolve_intimacy_id(
                entry.intimacy_id,
                character_id=signal.character_id or None,
                extra_ids=extra_ids,
            )
            if match is None:
                raise ToolException(
                    f"Unknown intimacy_id '{entry.intimacy_id}' in signal evidence. "
                    f"{_intimacy_listing(catalog)}"
                )
            entry.intimacy_id = match


def _intimacy_listing(catalog: dict[str, str]) -> str:
    if not catalog:
        return "No intimacies exist yet for this character; add one first."
    listing = ", ".join(
        f"{text or intimacy_id} [{intimacy_id}]" for intimacy_id, text in catalog.items()
    )
    return f"Valid intimacies: {listing}"


def _chronological_event_index(bible: StoryBible, event_id: str) -> int:
    for index, event in enumerate(chronological_order(bible)):
        if event.id == event_id:
            return index
    return 0


def _append_timeline_warnings(lines: list[str], bible: StoryBible, world) -> None:
    relation_warnings = format_diagnostics(relation_diagnostics(bible))
    if relation_warnings:
        lines.append("")
        lines.append(relation_warnings)
    effect_warnings = format_effect_diagnostics(effect_diagnostics(bible))
    if effect_warnings:
        lines.append("")
        lines.append(effect_warnings)
    duplicate_warnings = _duplicate_enactment_warnings(world)
    if duplicate_warnings:
        lines.append("")
        lines.append(duplicate_warnings)


def _format_event_placement(world, event_id: str) -> str:
    scenes = enacting_scenes(world, event_id)
    if not scenes:
        return "unplaced"
    if len(scenes) == 1:
        scene = scenes[0]
        return f"enacted by '{scene.title}' [scene id: {scene.id}]"
    titles = ", ".join(f"'{scene.title}' [scene id: {scene.id}]" for scene in scenes)
    return f"WARNING: enacted by multiple scenes ({titles})"


def _scenes_related_to_event(world, event_id: str) -> list:
    return [scene for scene in world.scenes if event_id in scene.blueprint.related_event_ids]


def _duplicate_enactment_warnings(world) -> str:
    warnings: list[str] = []
    for event in world.story_bible.timeline:
        scenes = enacting_scenes(world, event.id)
        if len(scenes) > 1:
            titles = ", ".join(f"'{scene.title}' [scene id: {scene.id}]" for scene in scenes)
            warnings.append(
                f"- Event '{event.title or 'Untitled'}' [id: {event.id}] is enacted by "
                f"multiple scenes ({titles})"
            )
    if not warnings:
        return ""
    return "Duplicate enactment warnings:\n" + "\n".join(warnings)


def _event_relation_summary(bible: StoryBible, event_id: str) -> str:
    relations = bible.relations_for_event(event_id)
    parts: list[str] = []
    if relations.incoming:
        parts.append(f"{len(relations.incoming)} incoming")
    if relations.outgoing:
        parts.append(f"{len(relations.outgoing)} outgoing")
    if relations.concurrent:
        parts.append(f"{len(relations.concurrent)} concurrent")
    return ", ".join(parts)


def _intimacy_lines(
    intimacies: list[Intimacy],
    ranks: dict[str, RankState] | None = None,
) -> list[str]:
    if not intimacies:
        return ["(none)"]
    lines: list[str] = []
    for intimacy in intimacies:
        line = f"- {intimacy.text} ({intimacy.strength}) [id: {intimacy.id}]"
        explanation = (ranks or {}).get(intimacy.id)
        if explanation is not None:
            line = f"{line} -- {format_threshold_distance(explanation)}"
        lines.append(line)
    return lines


def _derived_character_lines(
    derived: DerivedCharacterState,
    ranks: dict[str, RankState] | None = None,
) -> list[str]:
    return [
        "Intimacies:",
        *_intimacy_lines(derived.intimacies, ranks),
    ]


STORY_BIBLE_TOOLS = [
    read_story_bible,
    update_narrative_style,
    read_world_fact,
    upsert_world_fact,
    delete_world_fact,
    upsert_world_state_entry,
    delete_world_state_entry,
    read_character,
    read_character_arc,
    upsert_character,
    delete_character,
    read_timeline,
    read_event,
    add_event,
    update_event,
    delete_event,
    add_event_relation,
    remove_event_relation,
    read_world_state,
]
