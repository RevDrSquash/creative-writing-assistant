"""Pydantic models for the World, Story Bible, and scenes.

The Story Bible is event-sourced: Events and Signals carry structured effects,
and derived state is computed by the replay engine (``app/world/replay.py``)
rather than stored. See ``docs/story_bible_model.md`` for the authoritative
model description.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

IntimacyStrength = Literal["minor", "major", "defining"]
WorldStateKind = Literal["pressure", "thread", "consequence"]
EventKind = Literal["scene", "time_passage"]

INTIMACY_STRENGTHS: tuple[IntimacyStrength, ...] = ("minor", "major", "defining")
WORLD_STATE_KINDS: tuple[WorldStateKind, ...] = ("pressure", "thread", "consequence")
EVENT_KINDS: tuple[EventKind, ...] = ("scene", "time_passage")


def new_id() -> str:
    """Return a short unique id for world entities."""

    return uuid4().hex[:12]


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


class SetGoal(BaseModel):
    """Set the character's current goal."""

    op: Literal["set_goal"] = "set_goal"
    goal: str = ""


class SetStatus(BaseModel):
    """Set the character's current status."""

    op: Literal["set_status"] = "set_status"
    status: str = ""


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
    SetGoal | SetStatus | AddIntimacy | SetIntimacyStrength | UpdateIntimacy | RemoveIntimacy,
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

    goal: str = ""
    status: str = ""
    intimacies: list[Intimacy] = Field(default_factory=list)


class CharacterStance(BaseModel):
    """Ephemeral scene-level posture; freely editable and excluded from replay."""

    mood: str = ""
    intent: str = ""
    tactics: str = ""
    stakes: str = ""


class Character(BaseModel):
    """A named person or entity in the story world."""

    id: str = Field(default_factory=new_id)
    identity: CharacterIdentity = Field(default_factory=CharacterIdentity)
    baseline_state: CharacterBaselineState = Field(default_factory=CharacterBaselineState)
    stance: CharacterStance = Field(default_factory=CharacterStance)


class Signal(BaseModel):
    """A character's subjective interpretation of the Event that contains it."""

    id: str = Field(default_factory=new_id)
    character_id: str = ""
    interpretation: str = ""
    effects: list[CharacterStateEffect] = Field(default_factory=list)


class Event(BaseModel):
    """An objective story beat on the timeline."""

    id: str = Field(default_factory=new_id)
    title: str = ""
    description: str = ""
    kind: EventKind = "scene"
    world_state_effects: list[WorldStateEffect] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)


class StoryBible(BaseModel):
    """Structured reference material for the story world."""

    narrative_style: str = ""
    world_facts: list[WorldFact] = Field(default_factory=list)
    baseline_world_state: list[WorldStateEntry] = Field(default_factory=list)
    characters: list[Character] = Field(default_factory=list)
    timeline: list[Event] = Field(default_factory=list)

    def get_character(self, character_id: str) -> Character | None:
        return next(
            (character for character in self.characters if character.id == character_id),
            None,
        )

    def get_world_fact(self, fact_id: str) -> WorldFact | None:
        return next((fact for fact in self.world_facts if fact.id == fact_id), None)

    def get_event(self, event_id: str) -> Event | None:
        return next((event for event in self.timeline if event.id == event_id), None)

    def event_index(self, event_id: str) -> int | None:
        for index, event in enumerate(self.timeline):
            if event.id == event_id:
                return index
        return None


class Scene(BaseModel):
    """A prose scene; ``markdown`` holds the full scene text."""

    id: str = Field(default_factory=new_id)
    title: str = "New Scene"
    summary: str = ""
    markdown: str = ""
    notes: str = ""


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
