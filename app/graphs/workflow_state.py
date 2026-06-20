"""State schema for enforced scene-writing workflow graphs."""

from __future__ import annotations

from typing import TypedDict

from app.world.models import SceneCharacterStance


class SceneWorkflowState(TypedDict, total=False):
    """Inputs, working fields, and outputs for the scene-writing workflow."""

    premise: str
    purpose: str
    pov: str
    character_ids: list[str]
    event_ids: list[str]
    related_event_ids: list[str]
    constraints: str
    scene_id: str
    stances: list[SceneCharacterStance]
    outline: list[str]
    critique: str
    revision_count: int
    prose: str
    title: str
    summary: str
    max_revisions: int
