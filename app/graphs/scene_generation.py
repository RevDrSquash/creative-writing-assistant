"""Entry point for user-triggered scene generation from a scene blueprint."""

from __future__ import annotations

from app.graphs.registry import get_workflow
from app.world.models import utc_now
from app.world.scene import (
    blueprint_fingerprint,
    scene_is_generatable,
    update_scene_generated,
)
from app.world.scene_context import build_scene_continuity_context, format_continuity_context
from app.world.store import get_world, world_transaction


def run_scene_generation(scene_id: str, *, max_revisions: int = 1) -> None:
    """Run the scene-writing workflow for an existing scene blueprint.

    Validates the blueprint, snapshots its fingerprint, clears prior generated
    content and prose, invokes the workflow graph, then stamps generation metadata.
    """

    world = get_world()
    scene = world.get_scene(scene_id)
    if scene is None:
        msg = f"Scene not found: {scene_id}"
        raise ValueError(msg)
    if not scene_is_generatable(scene):
        msg = "Blueprint must have a non-empty premise and at least one enacted event."
        raise ValueError(msg)

    blueprint = scene.blueprint
    fingerprint = blueprint_fingerprint(blueprint)
    update_scene_generated(scene_id, clear=True)
    continuity_context = format_continuity_context(build_scene_continuity_context(world, scene_id))

    workflow = get_workflow("generate_scene")
    workflow.invoke(
        {
            "scene_id": scene_id,
            "premise": blueprint.premise,
            "purpose": blueprint.purpose,
            "pov": blueprint.pov,
            "character_ids": list(blueprint.character_ids),
            "event_ids": list(blueprint.event_ids),
            "related_event_ids": list(blueprint.related_event_ids),
            "constraints": blueprint.constraints,
            "arc": list(blueprint.arc),
            "notes": blueprint.notes,
            "continuity_context": continuity_context,
            "revision_count": 0,
            "max_revisions": max_revisions,
        }
    )

    with world_transaction():
        updated = get_world().get_scene(scene_id)
        if updated is None:
            return
        updated.generated.blueprint_fingerprint = fingerprint
        updated.generated.generated_at = utc_now()
