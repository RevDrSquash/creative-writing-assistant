"""World-backed scene helpers shared by the UI and agent tools."""

from __future__ import annotations

from app.persistence.world import DEFAULT_SCENE_MARKDOWN, DEFAULT_SCENE_TITLE
from app.world.models import Scene
from app.world.store import get_world, world_transaction

__all__ = [
    "DEFAULT_SCENE_MARKDOWN",
    "DEFAULT_SCENE_TITLE",
    "create_scene",
    "delete_scene",
    "get_scene_text",
    "resolve_scene",
    "set_scene_text",
]


def resolve_scene(scene_id: str | None = None) -> Scene:
    """Return the scene with ``scene_id``, or the first scene if not found.

    The world always contains at least one scene (the store seeds a default
    and ``delete_scene`` refuses to remove the last one).
    """

    world = get_world()
    if not world.scenes:
        with world_transaction() as world:
            world.scenes.append(Scene(title=DEFAULT_SCENE_TITLE, markdown=DEFAULT_SCENE_MARKDOWN))
    if scene_id:
        scene = world.get_scene(scene_id)
        if scene is not None:
            return scene
    return world.scenes[0]


def get_scene_text(scene_id: str | None = None) -> str:
    """Return the markdown text of a scene (first scene if id is unknown)."""

    return resolve_scene(scene_id).markdown


def set_scene_text(scene_id: str | None, text: str) -> None:
    """Set a scene's markdown text and write the world through to disk."""

    with world_transaction():
        resolve_scene(scene_id).markdown = text


def create_scene(title: str = DEFAULT_SCENE_TITLE, summary: str = "") -> Scene:
    """Append a new scene to the world and persist it."""

    scene = Scene(title=title or DEFAULT_SCENE_TITLE, summary=summary)
    with world_transaction() as world:
        world.scenes.append(scene)
    return scene


def delete_scene(scene_id: str) -> None:
    """Delete a scene; refuses to delete the last remaining scene."""

    with world_transaction() as world:
        scene = world.get_scene(scene_id)
        if scene is None:
            msg = f"Scene not found: {scene_id}"
            raise ValueError(msg)
        if len(world.scenes) == 1:
            msg = "Cannot delete the last remaining scene."
            raise ValueError(msg)
        world.scenes.remove(scene)
