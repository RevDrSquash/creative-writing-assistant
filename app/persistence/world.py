"""JSON persistence for the World object."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from app.persistence.paths import get_data_dir
from app.world.models import SCHEMA_VERSION, SceneBlueprint, World, blueprint_fingerprint, utc_now

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
        return migrate_world_payload(migrated)
    if schema_version == 4:
        migrated = dict(data)
        migrated["schema_version"] = 5
        return migrate_world_payload(migrated)
    if schema_version == 5:
        return migrate_world_payload(_migrate_v5_to_v6(data))
    if schema_version == 6:
        migrated = dict(data)
        migrated["schema_version"] = 7
        return migrate_world_payload(migrated)
    if schema_version == 7:
        return migrate_world_payload(_migrate_v7_to_v8(data))
    msg = (
        f"Unsupported world schema_version {schema_version!r}; "
        f"this app supports version {SCHEMA_VERSION}."
    )
    raise ValueError(msg)


def _migrate_v5_to_v6(data: dict) -> dict:
    """Flip directed event relations to the follower-as-source convention.

    v5 stored directed edges with ``source`` as the earlier event
    (``precedes`` meant "source precedes target"). v6 renames ``precedes`` to
    ``follows`` and stores ``source`` as the later event (the follower), so both
    directed kinds reference an earlier ``target``. Swapping endpoints preserves
    each edge's chronological meaning.
    """

    migrated = dict(data)
    bible = dict(migrated.get("story_bible") or {})
    relations = []
    for raw in bible.get("event_relations", []):
        relation = dict(raw)
        kind = relation.get("kind")
        if kind in ("precedes", "directly_follows"):
            relation["source_id"], relation["target_id"] = (
                relation.get("target_id", ""),
                relation.get("source_id", ""),
            )
            relation["kind"] = "follows" if kind == "precedes" else "directly_follows"
        relations.append(relation)
    bible["event_relations"] = relations
    migrated["story_bible"] = bible
    migrated["schema_version"] = 6
    return migrated


def _migrate_v7_to_v8(data: dict) -> dict:
    """Split blueprint stances/outline into ``Scene.generated`` and add blueprint fields."""

    migrated = dict(data)
    raw_scenes = migrated.get("scenes")
    if not isinstance(raw_scenes, list):
        migrated["schema_version"] = 8
        return migrated
    scenes: list[dict] = []
    for raw_scene in raw_scenes:
        scene = dict(raw_scene)
        blueprint = dict(scene.get("blueprint") or {})
        generated = dict(scene.get("generated") or {})

        stances = blueprint.pop("stances", None)
        outline = blueprint.pop("outline", None)
        if stances is not None:
            generated["stances"] = stances
        if outline is not None:
            generated["outline"] = outline

        blueprint.setdefault("pov", "")
        blueprint.setdefault("arc", [])
        blueprint.setdefault("character_ids", [])
        blueprint.setdefault("constraints", "")
        blueprint.setdefault("notes", "")

        scene["blueprint"] = blueprint
        scene["generated"] = generated

        markdown = scene.get("markdown", "")
        has_prose = bool(markdown.strip()) and markdown != DEFAULT_SCENE_MARKDOWN
        has_generated = bool(generated.get("stances")) or bool(generated.get("outline"))
        if has_prose or has_generated:
            fingerprint = blueprint_fingerprint(SceneBlueprint.model_validate(blueprint))
            generated["blueprint_fingerprint"] = fingerprint
            if has_prose:
                generated["generated_at"] = utc_now().isoformat()
        scene["generated"] = generated
        scenes.append(scene)

    migrated["scenes"] = scenes
    migrated["schema_version"] = 8
    return migrated


def validate_world_payload(data: dict, *, source: str) -> World:
    """Validate a world JSON payload, migrating and enforcing the schema version."""

    try:
        migrated = migrate_world_payload(data)
    except ValueError as exc:
        msg = f"{exc} in {source}."
        raise ValueError(msg) from exc
    try:
        return World.model_validate(migrated)
    except Exception as exc:
        msg = f"World payload failed validation in {source}."
        raise ValueError(msg) from exc


def get_world_store() -> JsonFileWorldStore:
    """Return the process-local world store singleton."""

    global _WORLD_STORE

    if _WORLD_STORE is None:
        _WORLD_STORE = JsonFileWorldStore()
    return _WORLD_STORE
