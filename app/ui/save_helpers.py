"""Shared UI helpers for world persistence."""

from __future__ import annotations

from nicegui import ui

from app.world.store import save_world


def save_world_ui() -> None:
    """Persist the world and notify the user if the save fails after retries."""

    try:
        save_world()
    except (PermissionError, OSError):
        ui.notify("Save failed — retry by editing again", type="negative")
