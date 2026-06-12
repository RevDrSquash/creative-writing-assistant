"""Per-user current-scene selection backed by NiceGUI user storage."""

from __future__ import annotations

from nicegui import app

from app.world.models import Scene
from app.world.scene import resolve_scene

CURRENT_SCENE_KEY = "current_scene_id"


def get_current_scene() -> Scene:
    """Return the user's currently selected scene, falling back to the first."""

    scene = resolve_scene(app.storage.user.get(CURRENT_SCENE_KEY))
    app.storage.user[CURRENT_SCENE_KEY] = scene.id
    return scene


def set_current_scene_id(scene_id: str) -> None:
    """Persist the user's currently selected scene id."""

    app.storage.user[CURRENT_SCENE_KEY] = scene_id
