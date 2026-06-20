"""Tests for World persistence, the in-memory singleton, and scene helpers."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from app.persistence.world import (
    DEFAULT_SCENE_MARKDOWN,
    DEFAULT_SCENE_TITLE,
    JsonFileWorldStore,
    default_world,
    get_world_store,
)
from app.world.models import SCHEMA_VERSION, Character, CharacterIdentity, Scene, World, WorldFact
from app.world.scene import (
    create_scene,
    delete_scene,
    get_scene_text,
    resolve_scene,
    set_scene_text,
)
from app.world.store import clear_world, get_world, replace_world, save_world, world_transaction


def test_store_load_returns_default_world_when_missing(tmp_path: Path) -> None:
    store = JsonFileWorldStore(tmp_path / "world.json")

    world = store.load()

    assert world.schema_version == SCHEMA_VERSION
    assert world.scenes == []


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


def test_store_load_migrates_v3_to_v4_discarding_character_stance(tmp_path: Path) -> None:
    path = tmp_path / "world.json"
    payload = default_world().model_dump(mode="json")
    payload["scenes"] = [
        Scene(title=DEFAULT_SCENE_TITLE, markdown=DEFAULT_SCENE_MARKDOWN).model_dump(mode="json")
    ]
    payload["schema_version"] = 3
    payload["story_bible"]["characters"] = [
        {
            "id": "char_mira",
            "identity": {"name": "Mira"},
            "baseline_state": {"intimacies": []},
            "stance": {
                "mood": "Calm",
                "intent": "Find the archive",
                "tactics": "Ask questions",
                "stakes": "Trust",
            },
        }
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    world = JsonFileWorldStore(path).load()

    assert world.schema_version == SCHEMA_VERSION
    character = world.story_bible.characters[0]
    assert character.identity.name == "Mira"
    assert "stance" not in character.model_dump()
    assert world.scenes[0].blueprint.premise == ""


def test_store_load_migrates_v4_to_v5_adding_event_relations(tmp_path: Path) -> None:
    path = tmp_path / "world.json"
    payload = default_world().model_dump(mode="json")
    payload["schema_version"] = 4
    path.write_text(json.dumps(payload), encoding="utf-8")

    world = JsonFileWorldStore(path).load()

    assert world.schema_version == SCHEMA_VERSION
    assert world.story_bible.event_relations == []


def test_store_load_migrates_v5_to_v6_flips_directed_relations(tmp_path: Path) -> None:
    path = tmp_path / "world.json"
    payload = default_world().model_dump(mode="json")
    payload["schema_version"] = 5
    payload["story_bible"]["timeline"] = [
        {"id": "event_a", "title": "Alpha", "world_state_effects": [], "signals": []},
        {"id": "event_b", "title": "Beta", "world_state_effects": [], "signals": []},
    ]
    payload["story_bible"]["event_relations"] = [
        {"id": "rel_p", "kind": "precedes", "source_id": "event_a", "target_id": "event_b"},
        {"id": "rel_d", "kind": "directly_follows", "source_id": "event_a", "target_id": "event_b"},
        {"id": "rel_c", "kind": "during", "source_id": "event_a", "target_id": "event_b"},
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    world = JsonFileWorldStore(path).load()

    assert world.schema_version == SCHEMA_VERSION
    relations = {relation.id: relation for relation in world.story_bible.event_relations}
    # `precedes` becomes `follows` with endpoints swapped (later event as source).
    assert relations["rel_p"].kind == "follows"
    assert relations["rel_p"].source_id == "event_b"
    assert relations["rel_p"].target_id == "event_a"
    # `directly_follows` keeps its name but flips to follower-as-source.
    assert relations["rel_d"].kind == "directly_follows"
    assert relations["rel_d"].source_id == "event_b"
    assert relations["rel_d"].target_id == "event_a"
    # `during` is symmetric and unchanged.
    assert relations["rel_c"].kind == "during"
    assert relations["rel_c"].source_id == "event_a"
    assert relations["rel_c"].target_id == "event_b"


def test_store_load_migrates_v6_to_v7_adds_blueprint_event_links(tmp_path: Path) -> None:
    path = tmp_path / "world.json"
    payload = default_world().model_dump(mode="json")
    scene_payload = Scene(title=DEFAULT_SCENE_TITLE, markdown=DEFAULT_SCENE_MARKDOWN).model_dump(
        mode="json"
    )
    scene_payload["blueprint"].pop("event_ids", None)
    scene_payload["blueprint"].pop("related_event_ids", None)
    payload["scenes"] = [scene_payload]
    payload["schema_version"] = 6
    path.write_text(json.dumps(payload), encoding="utf-8")

    world = JsonFileWorldStore(path).load()

    assert world.schema_version == SCHEMA_VERSION
    assert world.scenes[0].blueprint.event_ids == []
    assert world.scenes[0].blueprint.related_event_ids == []


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


def test_world_transaction_commits_mutation_to_disk(
    isolated_world: World,
    isolated_data_dir: Path,
) -> None:
    with world_transaction() as world:
        world.story_bible.world_facts.append(WorldFact(title="The Reach", text="Coastal"))

    raw = json.loads((isolated_data_dir / "world.json").read_text(encoding="utf-8"))
    assert raw["story_bible"]["world_facts"][0]["title"] == "The Reach"


def test_world_transaction_rolls_back_when_block_raises(isolated_world: World) -> None:
    def mutate_then_fail() -> None:
        with world_transaction() as world:
            world.story_bible.world_facts.append(WorldFact(title="Phantom", text="x"))
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        mutate_then_fail()

    assert get_world().story_bible.world_facts == []


def test_world_transaction_rolls_back_when_save_fails(
    isolated_world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_save(world: World) -> None:
        raise PermissionError("world.json is locked by another process")

    monkeypatch.setattr(get_world_store(), "save", failing_save)

    with pytest.raises(PermissionError):
        with world_transaction() as world:
            world.story_bible.world_facts.append(WorldFact(title="Phantom", text="x"))

    assert get_world().story_bible.world_facts == []


def test_concurrent_world_transactions_are_serialized(
    isolated_world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overlapping saves caused PermissionError on Windows; the lock forbids overlap."""

    store = get_world_store()
    original_save = store.save
    active = 0
    overlaps: list[int] = []

    def instrumented_save(world: World) -> None:
        nonlocal active
        active += 1
        if active > 1:
            overlaps.append(active)
        time.sleep(0.005)
        try:
            original_save(world)
        finally:
            active -= 1

    monkeypatch.setattr(store, "save", instrumented_save)

    def add_fact(index: int) -> None:
        with world_transaction() as world:
            world.story_bible.world_facts.append(WorldFact(title=f"Fact {index}", text="x"))

    threads = [threading.Thread(target=add_fact, args=(index,)) for index in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not overlaps
    assert len(get_world().story_bible.world_facts) == 5


def test_scene_helpers_create_read_write(isolated_world: World) -> None:
    scene = create_scene("Chapter 2", "The journey begins")

    assert scene in isolated_world.scenes
    assert resolve_scene(scene.id) is scene

    set_scene_text(scene.id, "# Updated")
    assert get_scene_text(scene.id) == "# Updated"


def test_resolve_scene_falls_back_to_first_scene(world_with_scene: World) -> None:
    assert resolve_scene("missing-id") is world_with_scene.scenes[0]
    assert resolve_scene(None) is world_with_scene.scenes[0]


def test_resolve_scene_returns_none_when_world_has_no_scenes(isolated_world: World) -> None:
    assert resolve_scene(None) is None
    assert resolve_scene("missing-id") is None


def test_delete_scene_removes_last_scene(world_with_scene: World) -> None:
    only_scene = world_with_scene.scenes[0]

    delete_scene(only_scene.id)

    assert only_scene not in world_with_scene.scenes
    assert world_with_scene.scenes == []


def test_delete_scene_removes_scene(world_with_scene: World) -> None:
    extra = create_scene("Extra")

    delete_scene(extra.id)

    assert extra not in world_with_scene.scenes
    with pytest.raises(ValueError, match="Scene not found"):
        delete_scene(extra.id)


def test_clear_world_story_bible_only(world_with_scene: World) -> None:
    world_with_scene.story_bible.premise = "A dark tale"
    world_with_scene.story_bible.world_facts.append(WorldFact(title="The Reach", text="Coastal"))
    world_with_scene.story_bible.characters.append(
        Character(identity=CharacterIdentity(name="Mira"))
    )
    create_scene("Extra")

    clear_world(story_bible=True, scenes=False)

    world = get_world()
    assert world.story_bible.premise == ""
    assert world.story_bible.world_facts == []
    assert world.story_bible.characters == []
    assert len(world.scenes) == 2


def test_clear_world_scenes_only(world_with_scene: World) -> None:
    world_with_scene.story_bible.premise = "Keep me"
    create_scene("Extra")

    clear_world(story_bible=False, scenes=True)

    world = get_world()
    assert world.story_bible.premise == "Keep me"
    assert world.scenes == []


def test_clear_world_both(world_with_scene: World) -> None:
    world_with_scene.story_bible.premise = "Gone"
    create_scene("Extra")

    clear_world(story_bible=True, scenes=True)

    world = get_world()
    assert world.story_bible.premise == ""
    assert world.scenes == []


def test_clear_world_preserves_metadata(isolated_world: World) -> None:
    isolated_world.metadata.title = "My Novel"
    isolated_world.metadata.description = "Epic fantasy"

    clear_world(story_bible=True, scenes=True)

    world = get_world()
    assert world.metadata.title == "My Novel"
    assert world.metadata.description == "Epic fantasy"


def test_clear_world_persists_to_disk(isolated_world: World, isolated_data_dir: Path) -> None:
    isolated_world.story_bible.premise = "Gone"

    clear_world(story_bible=True, scenes=False)

    raw = json.loads((isolated_data_dir / "world.json").read_text(encoding="utf-8"))
    assert raw["story_bible"]["premise"] == ""
