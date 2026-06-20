"""In-memory World singleton shared by the UI and agent tools."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from app.persistence.world import get_world_store
from app.world.models import StoryBible, World, utc_now

_WORLD: World | None = None

# Serializes world writes. Agent tool calls can run concurrently in worker
# threads, and on Windows two overlapping atomic saves of world.json collide
# on the file lock (PermissionError WinError 32).
_WORLD_LOCK = threading.RLock()


def get_world() -> World:
    """Return the in-memory world, loading it from disk on first access."""

    global _WORLD

    if _WORLD is None:
        _WORLD = get_world_store().load()
    return _WORLD


def save_world() -> None:
    """Write the in-memory world through to disk."""

    with _WORLD_LOCK:
        world = get_world()
        world.metadata.updated_at = utc_now()
        get_world_store().save(world)


@contextmanager
def world_transaction() -> Iterator[World]:
    """Mutate the world and persist it as a single serialized transaction.

    Holds the world lock across the whole mutate+save so concurrent writers
    cannot interleave. If the block or the save raises, the in-memory world is
    rolled back to its pre-transaction state, keeping memory and disk
    consistent (a failed tool call must not leave phantom mutations behind).

    Rollback restores field values on the existing ``World`` instance, so
    references to the world itself stay valid, but references to nested
    objects (scenes, characters, ...) captured before the transaction may go
    stale on the failure path.
    """

    with _WORLD_LOCK:
        world = get_world()
        snapshot = world.model_copy(deep=True)
        try:
            yield world
            save_world()
        except BaseException:
            for name in World.model_fields:
                setattr(world, name, getattr(snapshot, name))
            raise


def clear_world(*, story_bible: bool, scenes: bool) -> None:
    """Reset selected parts of the world to their empty/default forms."""

    with world_transaction() as world:
        if story_bible:
            world.story_bible = StoryBible()
        if scenes:
            world.scenes = []


def replace_world(world: World) -> None:
    """Swap in a new world (used by import) and persist it."""

    global _WORLD

    with _WORLD_LOCK:
        _WORLD = world
        get_world_store().save(world)


def reset_world_cache() -> None:
    """Drop the in-memory world so the next access reloads from disk (tests)."""

    global _WORLD

    with _WORLD_LOCK:
        _WORLD = None
