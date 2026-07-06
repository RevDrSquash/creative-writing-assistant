"""Tests for world save retry on transient PermissionError."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.persistence.world import JsonFileWorldStore, default_world


def test_world_save_retries_replace_on_permission_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonFileWorldStore(tmp_path / "world.json")
    world = default_world()
    attempts = {"count": 0}
    real_replace = os.replace

    def flaky_replace(src: os.PathLike[str], dst: os.PathLike[str]) -> None:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("WinError 5")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    store.save(world)
    assert attempts["count"] == 3
    assert store.path.is_file()


def test_world_save_raises_after_retry_exhaustion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = JsonFileWorldStore(tmp_path / "world.json")
    world = default_world()

    def always_fail(src: os.PathLike[str], dst: os.PathLike[str]) -> None:
        raise PermissionError("WinError 5")

    monkeypatch.setattr(os, "replace", always_fail)
    with pytest.raises(PermissionError):
        store.save(world)
