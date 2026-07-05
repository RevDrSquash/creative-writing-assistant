"""World-backed scene helpers shared by the UI and agent tools."""

from __future__ import annotations

from app.world.models import (
    Scene,
    SceneCharacterStance,
    SceneGenerated,
    blueprint_fingerprint,
    unique_slug,
    utc_now,
)
from app.world.store import get_world, world_transaction

DEFAULT_SCENE_TITLE = "New Scene"
DEFAULT_SCENE_MARKDOWN = "# New Scene\n\nStart writing..."

__all__ = [
    "DEFAULT_SCENE_MARKDOWN",
    "DEFAULT_SCENE_TITLE",
    "blueprint_fingerprint",
    "create_scene",
    "delete_scene",
    "get_scene_text",
    "resolve_scene",
    "scene_generation_status",
    "scene_is_generatable",
    "scene_is_stale",
    "set_scene_metadata",
    "set_scene_text",
    "update_scene_blueprint",
    "update_scene_generated",
]


def scene_is_stale(scene: Scene) -> bool:
    """Return True when generated content exists but the blueprint has changed since."""

    if scene.generated.generated_at is None:
        return False
    return scene.generated.blueprint_fingerprint != blueprint_fingerprint(scene.blueprint)


def scene_is_generatable(scene: Scene) -> bool:
    """Return True when the blueprint has enough input to run generation."""

    return bool(scene.blueprint.premise.strip()) and bool(scene.blueprint.event_ids)


def scene_generation_status(scene: Scene) -> str:
    """Return a human-readable generation status for tools and UI."""

    if scene.generated.generated_at is None:
        return "never generated"
    if scene_is_stale(scene):
        return "stale"
    return "up to date"


def resolve_scene(scene_id: str | None = None) -> Scene | None:
    """Return the scene with ``scene_id``, or the first scene if not found.

    Returns ``None`` when the world has no scenes and no matching id.
    """

    world = get_world()
    if scene_id:
        scene = world.get_scene(scene_id)
        if scene is not None:
            return scene
    return world.scenes[0] if world.scenes else None


def get_scene_text(scene_id: str | None = None) -> str:
    """Return the markdown text of a scene (first scene if id is unknown)."""

    scene = resolve_scene(scene_id)
    return scene.markdown if scene is not None else ""


def set_scene_text(scene_id: str | None, text: str) -> None:
    """Set a scene's markdown text and write the world through to disk."""

    with world_transaction():
        scene = resolve_scene(scene_id)
        if scene is None:
            return
        scene.markdown = text


def update_scene_blueprint(
    scene_id: str,
    *,
    premise: str | None = None,
    purpose: str | None = None,
    pov: str | None = None,
    arc: list[str] | None = None,
    character_ids: list[str] | None = None,
    event_ids: list[str] | None = None,
    related_event_ids: list[str] | None = None,
    constraints: str | None = None,
    notes: str | None = None,
) -> None:
    """Partially update blueprint inputs and write the world through to disk."""

    with world_transaction():
        scene = resolve_scene(scene_id)
        if scene is None:
            msg = f"Scene not found: {scene_id}"
            raise ValueError(msg)
        blueprint = scene.blueprint
        if premise is not None:
            blueprint.premise = premise
        if purpose is not None:
            blueprint.purpose = purpose
        if pov is not None:
            blueprint.pov = pov
        if arc is not None:
            blueprint.arc = arc
        if character_ids is not None:
            blueprint.character_ids = character_ids
        if event_ids is not None:
            blueprint.event_ids = event_ids
        if related_event_ids is not None:
            blueprint.related_event_ids = related_event_ids
        if constraints is not None:
            blueprint.constraints = constraints
        if notes is not None:
            blueprint.notes = notes


def update_scene_generated(
    scene_id: str,
    *,
    stances: list[SceneCharacterStance] | None = None,
    outline: list[str] | None = None,
    blueprint_fingerprint_value: str | None = None,
    generated_at: bool | None = None,
    clear: bool = False,
) -> None:
    """Partially update generated artifacts or reset them before a new run."""

    with world_transaction():
        scene = resolve_scene(scene_id)
        if scene is None:
            msg = f"Scene not found: {scene_id}"
            raise ValueError(msg)
        if clear:
            scene.generated = SceneGenerated()
            scene.markdown = ""
            return
        generated = scene.generated
        if stances is not None:
            generated.stances = stances
        if outline is not None:
            generated.outline = outline
        if blueprint_fingerprint_value is not None:
            generated.blueprint_fingerprint = blueprint_fingerprint_value
        if generated_at:
            generated.generated_at = utc_now()


def set_scene_metadata(
    scene_id: str | None,
    *,
    title: str | None = None,
    summary: str | None = None,
) -> None:
    """Set a scene's title and/or summary and write the world through to disk."""

    with world_transaction():
        scene = resolve_scene(scene_id)
        if scene is None:
            msg = "No scene found to update."
            raise ValueError(msg)
        if title is not None:
            scene.title = title
        if summary is not None:
            scene.summary = summary


def create_scene(title: str = DEFAULT_SCENE_TITLE, summary: str = "") -> Scene:
    """Append a new scene to the world and persist it."""

    scene = Scene(title=title or DEFAULT_SCENE_TITLE, summary=summary)
    with world_transaction() as world:
        scene.id = unique_slug(
            "scene_",
            scene.title,
            {item.id for item in world.scenes},
        )
        world.scenes.append(scene)
    return scene


def delete_scene(scene_id: str) -> None:
    """Delete a scene from the world."""

    with world_transaction() as world:
        scene = world.get_scene(scene_id)
        if scene is None:
            msg = f"Scene not found: {scene_id}"
            raise ValueError(msg)
        world.scenes.remove(scene)
