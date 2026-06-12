"""Portable world ZIP export/import (see docs/zip_import_export.md)."""

from __future__ import annotations

import io
import json
import zipfile

from pydantic import ValidationError

from app.persistence.world import validate_world_payload
from app.world.models import World

WORLD_JSON_NAME = "world.json"


def scene_archive_name(scene_id: str) -> str:
    return f"scenes/scene_{scene_id}.md"


def export_world_zip(world: World) -> bytes:
    """Serialize a world to ZIP bytes.

    Scene prose is stored as per-scene markdown files; the ``markdown`` field
    inside ``world.json`` is emptied. The ``assets/`` folder is reserved.
    """

    export_world = world.model_copy(deep=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for scene in export_world.scenes:
            archive.writestr(scene_archive_name(scene.id), scene.markdown)
            scene.markdown = ""
        archive.writestr(
            WORLD_JSON_NAME,
            json.dumps(export_world.model_dump(mode="json"), indent=2) + "\n",
        )
        archive.writestr(zipfile.ZipInfo("assets/"), "")
    return buffer.getvalue()


def import_world_zip(data: bytes) -> World:
    """Parse ZIP bytes into a World; raises ``ValueError`` on invalid input."""

    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        msg = "Not a valid ZIP file."
        raise ValueError(msg) from exc

    with archive:
        names = set(archive.namelist())
        if WORLD_JSON_NAME not in names:
            msg = "ZIP does not contain world.json."
            raise ValueError(msg)

        try:
            payload = json.loads(archive.read(WORLD_JSON_NAME).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            msg = f"world.json is not valid JSON: {exc}"
            raise ValueError(msg) from exc
        if not isinstance(payload, dict):
            msg = "world.json must contain a JSON object."
            raise ValueError(msg)

        try:
            world = validate_world_payload(payload, source=WORLD_JSON_NAME)
        except ValidationError as exc:
            msg = f"world.json failed validation: {exc}"
            raise ValueError(msg) from exc
        for scene in world.scenes:
            name = scene_archive_name(scene.id)
            if name in names:
                scene.markdown = archive.read(name).decode("utf-8")
        return world
