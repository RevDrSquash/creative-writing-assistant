"""Tests for World persistence, the in-memory singleton, and scene helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.persistence.world import (
    DEFAULT_SCENE_MARKDOWN,
    JsonFileWorldStore,
    default_world,
)
from app.world.models import SCHEMA_VERSION, Scene, World, WorldFact
from app.world.scene import (
    create_scene,
    delete_scene,
    get_scene_text,
    resolve_scene,
    set_scene_text,
)
from app.world.store import get_world, replace_world, save_world


def test_store_load_returns_default_world_when_missing(tmp_path: Path) -> None:
    store = JsonFileWorldStore(tmp_path / "world.json")

    world = store.load()

    assert world.schema_version == SCHEMA_VERSION
    assert len(world.scenes) == 1
    assert world.scenes[0].markdown == DEFAULT_SCENE_MARKDOWN


def test_store_save_and_load_round_trip(tmp_path: Path) -> None:
    store = JsonFileWorldStore(tmp_path / "world.json")
    world = default_world()
    world.metadata.title = "Test World"
    world.story_bible.world_facts.append(WorldFact(title="The Reach", text="A coastal region"))
    world.scenes.append(Scene(title="Chapter 2", markdown="# Two"))

    store.save(world)
    restored = store.load()

    assert restored == world
    raw = json.loads((tmp_path / "world.json").read_text(encoding="utf-8"))
    assert raw["schema_version"] == SCHEMA_VERSION


def test_store_load_rejects_unsupported_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "world.json"
    payload = default_world().model_dump(mode="json")
    payload["schema_version"] = 999
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version"):
        JsonFileWorldStore(path).load()


def test_get_world_singleton_loads_once_and_save_world_persists(
    isolated_world: World,
    isolated_data_dir: Path,
) -> None:
    assert get_world() is isolated_world

    isolated_world.metadata.title = "Persisted Title"
    save_world()

    raw = json.loads((isolated_data_dir / "world.json").read_text(encoding="utf-8"))
    assert raw["metadata"]["title"] == "Persisted Title"


def test_replace_world_swaps_singleton_and_persists(
    isolated_world: World,
    isolated_data_dir: Path,
) -> None:
    new_world = default_world()
    new_world.metadata.title = "Imported"

    replace_world(new_world)

    assert get_world() is new_world
    raw = json.loads((isolated_data_dir / "world.json").read_text(encoding="utf-8"))
    assert raw["metadata"]["title"] == "Imported"


def test_scene_helpers_create_read_write(isolated_world: World) -> None:
    scene = create_scene("Chapter 2", "The journey begins")

    assert scene in isolated_world.scenes
    assert resolve_scene(scene.id) is scene

    set_scene_text(scene.id, "# Updated")
    assert get_scene_text(scene.id) == "# Updated"


def test_resolve_scene_falls_back_to_first_scene(isolated_world: World) -> None:
    assert resolve_scene("missing-id") is isolated_world.scenes[0]
    assert resolve_scene(None) is isolated_world.scenes[0]


def test_delete_scene_refuses_last_scene(isolated_world: World) -> None:
    only_scene = isolated_world.scenes[0]

    with pytest.raises(ValueError, match="last remaining scene"):
        delete_scene(only_scene.id)


def test_delete_scene_removes_scene(isolated_world: World) -> None:
    extra = create_scene("Extra")

    delete_scene(extra.id)

    assert extra not in isolated_world.scenes
    with pytest.raises(ValueError, match="Scene not found"):
        delete_scene(extra.id)
