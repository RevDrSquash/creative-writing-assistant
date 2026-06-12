"""In-memory World singleton shared by the UI and agent tools."""

from __future__ import annotations

from app.persistence.world import get_world_store
from app.world.models import World, utc_now

_WORLD: World | None = None


def get_world() -> World:
    """Return the in-memory world, loading it from disk on first access."""

    global _WORLD

    if _WORLD is None:
        _WORLD = get_world_store().load()
    return _WORLD


def save_world() -> None:
    """Write the in-memory world through to disk."""

    world = get_world()
    world.metadata.updated_at = utc_now()
    get_world_store().save(world)


def replace_world(world: World) -> None:
    """Swap in a new world (used by import) and persist it."""

    global _WORLD

    _WORLD = world
    get_world_store().save(world)


def reset_world_cache() -> None:
    """Drop the in-memory world so the next access reloads from disk (tests)."""

    global _WORLD

    _WORLD = None
