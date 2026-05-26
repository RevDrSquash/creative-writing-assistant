"""Shared single-scene state for the workspace editor and agent tools."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from nicegui import app

SCENE_CONTENT_KEY = "scene_content"
DEFAULT_SCENE_MARKDOWN = "# New Scene\n\nStart writing..."


def get_current_scene_text(
    backing_store: MutableMapping[str, Any] | None = None,
) -> str:
    """Return the current scene text, seeding the default scene if needed."""

    storage = backing_store if backing_store is not None else app.storage.user
    return str(storage.setdefault(SCENE_CONTENT_KEY, DEFAULT_SCENE_MARKDOWN))


def set_current_scene_text(
    text: str,
    backing_store: MutableMapping[str, Any] | None = None,
) -> None:
    """Persist the current scene text to the active user storage."""

    storage = backing_store if backing_store is not None else app.storage.user
    storage[SCENE_CONTENT_KEY] = text
