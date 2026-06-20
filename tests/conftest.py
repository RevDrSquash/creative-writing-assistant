"""Shared pytest fixtures.

UI tests use the ``user`` fixture, which simulates a NiceGUI browser session
in-process (no real browser, no network). It boots the real app entry point
(`app/ui/app.py`) inside an isolated NiceGUI context with persistence
redirected to a temp directory and a fake OpenRouter key, so page tests are
deterministic and never touch the developer's `data/` folder or the network.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from nicegui.testing import User
from nicegui.testing.user_simulation import user_simulation

# Bound at collection time so the isolation fixtures reset the same module
# instances that test modules imported, even after UI tests purge sys.modules.
import app.persistence.model_configs as _model_configs
import app.persistence.world as _world_persistence
import app.world.store as _world_store

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_FILE = REPO_ROOT / "app" / "ui" / "app.py"

# Valid-looking but fake key so ModelSettings validation passes without a real
# .env. Page rendering never calls OpenRouter; only sending a chat message would.
FAKE_OPENROUTER_API_KEY = "sk-or-v1-0000000000000000000000000000000000000000"


def _purge_app_modules() -> None:
    """Drop all ``app.*`` modules so the next import re-registers @ui.page routes.

    NiceGUI page registration happens at import time. The simulated user boots
    the app via ``runpy``, which is a no-op for modules already imported (for
    example during test collection), so we force a fresh import.
    """

    for name in [name for name in sys.modules if name == "app" or name.startswith("app.")]:
        sys.modules.pop(name, None)


@pytest.fixture
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Redirect JSON persistence (world, chat history, model configs, LLM logs) to a temp dir.

    The model config repository is a process-wide singleton bound to a data
    dir; reset it around the test so it rebinds to the temp dir instead of the
    developer's real ``data/`` (otherwise tests read real model selections).
    """

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("WRITING_AGENT_DATA_DIR", str(data_dir))
    _model_configs.reset_model_config_repository()
    yield data_dir
    _model_configs.reset_model_config_repository()


@pytest.fixture
def isolated_world(isolated_data_dir: Path):
    """Fresh in-memory World singleton backed by an isolated world.json."""

    _world_persistence._WORLD_STORE = None
    _world_store._WORLD = None
    yield _world_store.get_world()
    _world_persistence._WORLD_STORE = None
    _world_store._WORLD = None


@pytest.fixture
def world_with_scene(isolated_world):
    """World with one starter scene for tests that need scene content."""

    from app.persistence.world import DEFAULT_SCENE_MARKDOWN, DEFAULT_SCENE_TITLE
    from app.world.models import Scene, unique_slug

    if not isolated_world.scenes:
        scene = Scene(title=DEFAULT_SCENE_TITLE, markdown=DEFAULT_SCENE_MARKDOWN)
        scene.id = unique_slug("scene_", scene.title, set())
        isolated_world.scenes.append(scene)
    return isolated_world


@pytest.fixture
async def user(
    isolated_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> AsyncGenerator[User, None]:
    """Simulated NiceGUI user running the full app in an isolated environment."""

    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_OPENROUTER_API_KEY)
    _purge_app_modules()
    async with user_simulation(main_file=MAIN_FILE) as simulated_user:
        yield simulated_user

        errors = [record for record in caplog.get_records("call") if record.levelname == "ERROR"]
        if errors:
            messages = "\n".join(record.getMessage() for record in errors)
            pytest.fail(f"Unexpected ERROR logs during UI test:\n{messages}", pytrace=False)


@pytest.fixture
def stub_model_catalog(user: User, monkeypatch: pytest.MonkeyPatch) -> list:
    """Pre-fill the OpenRouter catalog cache so model pages never hit the network."""

    import app.models.catalog as catalog

    models = [
        catalog.OpenRouterModel(id="test/model-small", name="Test Model Small"),
        catalog.OpenRouterModel(id="test/model-large", name="Test Model Large"),
    ]
    monkeypatch.setattr(catalog, "_OPENROUTER_MODELS_CACHE", models)
    return models
