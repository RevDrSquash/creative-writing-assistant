"""Tests for portable world ZIP export/import."""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.persistence.world import default_world
from app.persistence.world_zip import export_world_zip, import_world_zip, scene_archive_name
from app.world.models import Character, CharacterIdentity, Scene


def _sample_world():
    world = default_world()
    world.metadata.title = "Zip World"
    world.scenes.append(Scene(title="Chapter 2", markdown="# Two\n\nProse here."))
    world.story_bible.characters.append(Character(identity=CharacterIdentity(name="Mira")))
    return world


def test_export_world_zip_layout_and_emptied_markdown() -> None:
    world = _sample_world()

    data = export_world_zip(world)

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        assert "world.json" in names
        assert "assets/" in names
        for scene in world.scenes:
            assert scene_archive_name(scene.id) in names
            assert archive.read(scene_archive_name(scene.id)).decode("utf-8") == scene.markdown

        payload = json.loads(archive.read("world.json").decode("utf-8"))
        assert all(scene["markdown"] == "" for scene in payload["scenes"])

    # Exporting must not mutate the live world.
    assert world.scenes[1].markdown == "# Two\n\nProse here."


def test_zip_round_trip_restores_world() -> None:
    world = _sample_world()

    restored = import_world_zip(export_world_zip(world))

    assert restored == world


def test_import_rejects_invalid_zip_bytes() -> None:
    with pytest.raises(ValueError, match="Not a valid ZIP file"):
        import_world_zip(b"definitely not a zip")


def test_import_rejects_zip_without_world_json() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hello")

    with pytest.raises(ValueError, match=r"does not contain world\.json"):
        import_world_zip(buffer.getvalue())


def test_import_rejects_unsupported_schema_version() -> None:
    world = _sample_world()
    payload = world.model_dump(mode="json")
    payload["schema_version"] = 999
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("world.json", json.dumps(payload))

    with pytest.raises(ValueError, match="schema_version"):
        import_world_zip(buffer.getvalue())


def test_import_rejects_invalid_world_payload() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "world.json",
            json.dumps({"schema_version": 1, "scenes": "not-a-list"}),
        )

    with pytest.raises(ValueError, match="failed validation"):
        import_world_zip(buffer.getvalue())
