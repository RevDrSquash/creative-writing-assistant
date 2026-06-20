"""World-backed scene helpers shared by the UI and agent tools."""

from __future__ import annotations

from app.persistence.world import DEFAULT_SCENE_MARKDOWN, DEFAULT_SCENE_TITLE
from app.world.models import Scene, SceneCharacterStance, unique_slug
from app.world.store import get_world, world_transaction

__all__ = [
    "DEFAULT_SCENE_MARKDOWN",
    "DEFAULT_SCENE_TITLE",
    "create_scene",
    "delete_scene",
    "get_scene_text",
    "resolve_scene",
    "set_scene_metadata",
    "set_scene_text",
    "update_scene_blueprint",
]


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
    stances: list[SceneCharacterStance] | None = None,
    outline: list[str] | None = None,
) -> None:
    """Partially update a scene blueprint and write the world through to disk."""

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
        if stances is not None:
            blueprint.stances = stances
        if outline is not None:
            blueprint.outline = outline


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
