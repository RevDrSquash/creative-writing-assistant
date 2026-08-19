"""Pydantic models for the World, Story Bible, and scenes.

The Story Bible is event-sourced: Events and Signals carry structured effects,
and derived state is computed by the replay engine (``app/world/replay.py``)
rather than stored. See ``docs/story_bible_model.md`` for the authoritative
model description.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

SCHEMA_VERSION = 8

IntimacyStrength = Literal["minor", "major", "defining"]
WorldStateKind = Literal["pressure", "thread", "consequence"]
EventRelationKind = Literal["follows", "directly_follows", "depends_on", "during"]

INTIMACY_STRENGTHS: tuple[IntimacyStrength, ...] = ("minor", "major", "defining")
WORLD_STATE_KINDS: tuple[WorldStateKind, ...] = ("pressure", "thread", "consequence")
EVENT_RELATION_KINDS: tuple[EventRelationKind, ...] = (
    "follows",
    "directly_follows",
    "depends_on",
    "during",
)
DIRECTED_EVENT_RELATION_KINDS: tuple[EventRelationKind, ...] = (
    "follows",
    "directly_follows",
    "depends_on",
)

# Articles dropped when comparing entity ids, so a model that emits
# ``char_narrator`` still resolves to the real ``char_the_narrator``.
_ID_STOPWORDS = frozenset({"the", "a", "an"})
_ID_TYPE_PREFIXES = ("char_", "evt_", "fact_", "scene_", "wse_")


def _entity_id_tokens(value: str) -> frozenset[str]:
    """Return the significant tokens of an entity id for fuzzy matching."""

    cleaned = value.strip().lower()
    for prefix in _ID_TYPE_PREFIXES:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            break
    return frozenset(token for token in cleaned.split("_") if token and token not in _ID_STOPWORDS)


# Backward-compatible alias used by older imports/tests.
_character_id_tokens = _entity_id_tokens


def _resolve_entity_id(raw_id: str, candidate_ids: list[str]) -> str | None:
    """Resolve a possibly-imprecise id against candidates (exact, then unique token match)."""

    if raw_id in candidate_ids:
        return raw_id

    target = _entity_id_tokens(raw_id)
    if not target:
        return None
    matches = [candidate for candidate in candidate_ids if target <= _entity_id_tokens(candidate)]
    if len(matches) == 1:
        return matches[0]
    return None


def new_id() -> str:
    """Return a short unique id for world entities."""

    return uuid4().hex[:12]


def slugify(text: str) -> str:
    """Convert text to a lowercase underscore slug."""

    normalized = re.sub(r"[^a-z0-9]+", "_", text.lower().strip())
    return normalized.strip("_")


def unique_slug(prefix: str, text: str, existing: set[str]) -> str:
    """Return a unique slug from a type prefix and source text.

    Non-blank text becomes ``{prefix}{slugify(text)}`` (e.g. ``char_the_guard``).
    Blank text falls back to the bare prefix without its trailing underscore
    (e.g. ``char``, ``char_2``). Numeric suffixes resolve collisions.
    """

    base = slugify(text)
    slug = f"{prefix}{base}" if base else prefix.rstrip("_")
    if slug not in existing:
        return slug
    counter = 2
    while True:
        candidate = f"{slug}_{counter}"
        if candidate not in existing:
            return candidate
        counter += 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Intimacy(BaseModel):
    """A character-subjective belief, attachment, value, fear, or desire."""

    id: str = Field(default_factory=new_id)
    text: str = ""
    strength: IntimacyStrength = "minor"


class WorldFact(BaseModel):
    """A stable setting fact (locations and lore are world facts)."""

    id: str = Field(default_factory=new_id)
    title: str = ""
    text: str = ""
    tags: list[str] = Field(default_factory=list)


class WorldStateEntry(BaseModel):
    """A currently-active pressure, open thread, or recent consequence."""

    id: str = Field(default_factory=new_id)
    text: str = ""
    kind: WorldStateKind = "thread"


class AddWorldStateEntry(BaseModel):
    """Add a world-state entry."""

    op: Literal["add_entry"] = "add_entry"
    entry: WorldStateEntry = Field(default_factory=WorldStateEntry)


class UpdateWorldStateEntry(BaseModel):
    """Replace the text and/or kind of an existing world-state entry."""

    op: Literal["update_entry"] = "update_entry"
    entry_id: str = ""
    text: str | None = None
    kind: WorldStateKind | None = None


class RemoveWorldStateEntry(BaseModel):
    """Remove a world-state entry."""

    op: Literal["remove_entry"] = "remove_entry"
    entry_id: str = ""


WorldStateEffect = Annotated[
    AddWorldStateEntry | UpdateWorldStateEntry | RemoveWorldStateEntry,
    Field(discriminator="op"),
]


class AddIntimacy(BaseModel):
    """Add an intimacy to the character."""

    op: Literal["add_intimacy"] = "add_intimacy"
    intimacy: Intimacy = Field(default_factory=Intimacy)


class SetIntimacyStrength(BaseModel):
    """Strengthen or weaken an existing intimacy."""

    op: Literal["set_intimacy_strength"] = "set_intimacy_strength"
    intimacy_id: str = ""
    strength: IntimacyStrength = "minor"


class UpdateIntimacy(BaseModel):
    """Replace the text of an existing intimacy."""

    op: Literal["update_intimacy"] = "update_intimacy"
    intimacy_id: str = ""
    text: str = ""


class RemoveIntimacy(BaseModel):
    """Remove an intimacy from the character."""

    op: Literal["remove_intimacy"] = "remove_intimacy"
    intimacy_id: str = ""


CharacterStateEffect = Annotated[
    AddIntimacy | SetIntimacyStrength | UpdateIntimacy | RemoveIntimacy,
    Field(discriminator="op"),
]


class CharacterIdentity(BaseModel):
    """Stable identity: who the character is, independent of the timeline."""

    name: str = ""
    traits: str = ""
    appearance: str = ""
    background: str = ""
    voice: str = ""


class CharacterBaselineState(BaseModel):
    """The character's state at the start of the timeline."""

    intimacies: list[Intimacy] = Field(default_factory=list)


class Character(BaseModel):
    """A named person or entity in the story world."""

    id: str = Field(default_factory=new_id)
    identity: CharacterIdentity = Field(default_factory=CharacterIdentity)
    baseline_state: CharacterBaselineState = Field(default_factory=CharacterBaselineState)


class Signal(BaseModel):
    """A character's subjective interpretation of the Event that contains it."""

    id: str = Field(default_factory=new_id)
    character_id: str = ""
    interpretation: str = ""
    effects: list[CharacterStateEffect] = Field(default_factory=list)


class EventRelationSpec(BaseModel):
    """Inline relation to create when adding a new event.

    For directed kinds the new event is the source (later) and ``event_id`` is
    the earlier target. For ``during``, the new event and ``event_id`` form an
    unordered concurrent pair.
    """

    kind: EventRelationKind
    event_id: str = ""


class Event(BaseModel):
    """An objective story beat on the timeline.

    Events live in ``StoryBible.timeline`` for storage and lookup; chronology is
    derived from ``event_relations``, not list position.
    """

    id: str = Field(default_factory=new_id)
    title: str = ""
    description: str = ""
    world_state_effects: list[WorldStateEffect] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)


class EventRelation(BaseModel):
    """A typed edge between two timeline events.

    For directed kinds (``follows``, ``directly_follows``, ``depends_on``),
    ``source_id`` is the later event and ``target_id`` the earlier one.
    """

    id: str = Field(default_factory=new_id)
    kind: EventRelationKind = "follows"
    source_id: str = ""
    target_id: str = ""


class EventRelationsForEvent(BaseModel):
    """Relations involving a single event, split by direction."""

    incoming: list[EventRelation] = Field(default_factory=list)
    outgoing: list[EventRelation] = Field(default_factory=list)
    concurrent: list[EventRelation] = Field(default_factory=list)


class StoryBible(BaseModel):
    """Structured reference material for the story world."""

    premise: str = ""
    tone: str = ""
    themes: str = ""
    writing_style: str = ""
    world_facts: list[WorldFact] = Field(default_factory=list)
    baseline_world_state: list[WorldStateEntry] = Field(default_factory=list)
    characters: list[Character] = Field(default_factory=list)
    timeline: list[Event] = Field(
        default_factory=list,
        description="Append-only event storage; creation order is a tie-breaker only.",
    )
    event_relations: list[EventRelation] = Field(default_factory=list)

    def get_character(self, character_id: str) -> Character | None:
        return next(
            (character for character in self.characters if character.id == character_id),
            None,
        )

    def resolve_character_id(
        self,
        character_id: str,
        allowed: Iterable[str] | None = None,
    ) -> str | None:
        """Resolve a possibly-imprecise character id to a real character id.

        Models occasionally emit a slightly different id than the canonical
        one (for example ``char_narrator`` instead of ``char_the_narrator``).
        This matches exactly first, then tolerates minor drift by comparing the
        significant id tokens (ignoring dropped articles). When ``allowed`` is
        given, only those ids are considered. Returns ``None`` if there is no
        unique match.
        """

        candidate_ids = [character.id for character in self.characters]
        if allowed is not None:
            allowed_set = set(allowed)
            candidate_ids = [cid for cid in candidate_ids if cid in allowed_set]

        return _resolve_entity_id(character_id, candidate_ids)

    def resolve_event_id(self, event_id: str) -> str | None:
        """Resolve a possibly-imprecise event id (exact, then unique token match)."""

        return _resolve_entity_id(event_id, [event.id for event in self.timeline])

    def resolve_world_fact_id(self, fact_id: str) -> str | None:
        """Resolve a possibly-imprecise world-fact id (exact, then unique token match)."""

        return _resolve_entity_id(fact_id, [fact.id for fact in self.world_facts])

    def get_world_fact(self, fact_id: str) -> WorldFact | None:
        return next((fact for fact in self.world_facts if fact.id == fact_id), None)

    def get_event(self, event_id: str) -> Event | None:
        return next((event for event in self.timeline if event.id == event_id), None)

    def get_event_relation(self, relation_id: str) -> EventRelation | None:
        return next(
            (relation for relation in self.event_relations if relation.id == relation_id),
            None,
        )

    def relations_for_event(self, event_id: str) -> EventRelationsForEvent:
        incoming: list[EventRelation] = []
        outgoing: list[EventRelation] = []
        concurrent: list[EventRelation] = []
        for relation in self.event_relations:
            if relation.kind == "during":
                if relation.source_id == event_id or relation.target_id == event_id:
                    concurrent.append(relation)
            elif relation.target_id == event_id:
                incoming.append(relation)
            elif relation.source_id == event_id:
                outgoing.append(relation)
        return EventRelationsForEvent(
            incoming=incoming,
            outgoing=outgoing,
            concurrent=concurrent,
        )


class SceneCharacterStance(BaseModel):
    """Ephemeral per-character posture for a scene; excluded from Story Bible replay."""

    character_id: str = ""
    mood: list[str] = Field(default_factory=list)
    intent: str = ""
    tactics: str = ""
    stakes: str = ""


class SceneBlueprint(BaseModel):
    """Editable scene card inputs: premise, purpose, POV, scene frame, links, and constraints.

    ``starting_state``, ``central_conflict``, and ``required_resolution`` form the scene frame:
    how the scene opens, the conflict it dramatizes, and the outcome later scenes depend on.
    Beat-level planning is left to the generation workflow.

    ``event_ids`` are the timeline events this scene enacts on-page (one or more; each event may
    be enacted by at most one scene); ``related_event_ids`` are context-only events relevant to
    the scene without being enacted. Both are scene-local scratch (not event-sourced, excluded
    from replay). Deleting an event prunes its id from every blueprint.
    """

    premise: str = ""
    purpose: str = ""
    pov: str = ""
    starting_state: str = ""
    central_conflict: str = ""
    required_resolution: str = ""
    character_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    related_event_ids: list[str] = Field(default_factory=list)
    constraints: str = ""
    notes: str = ""


def blueprint_fingerprint(blueprint: SceneBlueprint) -> str:
    """Return a stable hash of blueprint inputs for staleness detection."""

    payload = blueprint.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


class SceneGenerated(BaseModel):
    """Workflow output for a scene: stances, outline, and generation metadata."""

    stances: list[SceneCharacterStance] = Field(default_factory=list)
    outline: list[str] = Field(default_factory=list)
    blueprint_fingerprint: str = ""
    generated_at: datetime | None = None


class Scene(BaseModel):
    """A prose scene; ``markdown`` holds the full scene text."""

    id: str = Field(default_factory=new_id)
    title: str = "New Scene"
    summary: str = ""
    markdown: str = ""
    notes: str = ""
    blueprint: SceneBlueprint = Field(default_factory=SceneBlueprint)
    generated: SceneGenerated = Field(default_factory=SceneGenerated)


class WorldMetadata(BaseModel):
    """Project-level information about the world."""

    title: str = "Untitled World"
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class World(BaseModel):
    """Root object for a story project."""

    schema_version: int = SCHEMA_VERSION
    metadata: WorldMetadata = Field(default_factory=WorldMetadata)
    story_bible: StoryBible = Field(default_factory=StoryBible)
    scenes: list[Scene] = Field(default_factory=list)

    def get_scene(self, scene_id: str) -> Scene | None:
        return next((scene for scene in self.scenes if scene.id == scene_id), None)

    def resolve_scene_id(self, scene_id: str) -> str | None:
        """Resolve a possibly-imprecise scene id (exact, then unique token match)."""

        return _resolve_entity_id(scene_id, [scene.id for scene in self.scenes])
