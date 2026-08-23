"""State schemas for enforced LangGraph workflow graphs."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from app.graphs.state import merge_character_critiques
from app.world.models import SceneCharacterStance


class SceneWorkflowState(TypedDict, total=False):
    """Inputs, working fields, and outputs for the scene-writing workflow."""

    premise: str
    purpose: str
    pov: str
    character_ids: list[str]
    event_ids: list[str]
    related_event_ids: list[str]
    scene_start_event_id: str
    scene_end_event_id: str
    constraints: str
    scene_id: str
    starting_state: str
    central_conflict: str
    required_resolution: str
    notes: str
    continuity_context: str
    context_dossier: str
    stances: list[SceneCharacterStance]
    outline: list[str]
    critique: str
    revision_count: int
    prose: str
    prose_critique: str
    character_critiques: Annotated[list[dict[str, Any]], merge_character_critiques]
    review_character_id: str
    prose_revision_count: int
    summary: str
    max_revisions: int


class IntimacyWorkflowState(TypedDict, total=False):
    """Inputs, working fields, and outputs for one character-event interpretation."""

    event_id: str
    character_id: str
    context: str
    analysis: dict[str, Any]
    validated: dict[str, Any]
    review: dict[str, Any]
    result: dict[str, Any]
