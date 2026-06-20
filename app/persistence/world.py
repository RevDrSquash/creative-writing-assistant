"""JSON persistence for the World object."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from app.persistence.paths import get_data_dir
from app.world.models import SCHEMA_VERSION, World

WORLD_FILENAME = "world.json"

DEFAULT_SCENE_TITLE = "New Scene"
DEFAULT_SCENE_MARKDOWN = "# New Scene\n\nStart writing..."

_WORLD_STORE: JsonFileWorldStore | None = None


def default_world() -> World:
    """Return a fresh world with no scenes."""

    return World(scenes=[])


class WorldStorePort(Protocol):
    """Minimal persistence API for the world."""

    def load(self) -> World:
        """Return the persisted world, or a default world if none exists."""

    def save(self, world: World) -> None:
        """Persist the world."""


class JsonFileWorldStore:
    """JSON-file-backed world store."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_data_dir() / WORLD_FILENAME

    def load(self) -> World:
        """Load the world from disk, seeding a default world if absent."""

        if not self.path.exists():
            return default_world()

        raw = self.path.read_text(encoding="utf-8")
        if not raw.strip():
            return default_world()

        data = json.loads(raw)
        if not isinstance(data, dict):
            msg = f"Expected world JSON object at {self.path}"
            raise ValueError(msg)
        return validate_world_payload(data, source=str(self.path))

    def save(self, world: World) -> None:
        """Write the world atomically."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(world.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, self.path)


def migrate_world_payload(data: dict) -> dict:
    """Upgrade a stored world payload to the current schema version."""

    schema_version = data.get("schema_version")
    if schema_version == SCHEMA_VERSION:
        return data
    if schema_version == 3:
        migrated = dict(data)
        migrated["schema_version"] = 4
        return migrated
    msg = (
        f"Unsupported world schema_version {schema_version!r}; "
        f"this app supports version {SCHEMA_VERSION}."
    )
    raise ValueError(msg)


def validate_world_payload(data: dict, *, source: str) -> World:
    """Validate a world JSON payload, migrating and enforcing the schema version."""

    try:
        migrated = migrate_world_payload(data)
    except ValueError as exc:
        msg = f"{exc} in {source}."
        raise ValueError(msg) from exc
    return World.model_validate(migrated)


def get_world_store() -> JsonFileWorldStore:
    """Return the process-local world store singleton."""

    global _WORLD_STORE

    if _WORLD_STORE is None:
        _WORLD_STORE = JsonFileWorldStore()
    return _WORLD_STORE
