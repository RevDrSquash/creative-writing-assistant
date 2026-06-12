"""Shared pytest fixtures.

UI tests use the ``user`` fixture, which simulates a NiceGUI browser session
in-process (no real browser, no network). It boots the real app entry point
(`app/ui/app.py`) inside an isolated NiceGUI context with persistence
redirected to a temp directory and a fake OpenRouter key, so page tests are
deterministic and never touch the developer's `data/` folder or the network.
"""

from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from nicegui.testing import User
from nicegui.testing.user_simulation import user_simulation

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
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect JSON persistence (chat history, model configs, LLM logs) to a temp dir."""

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("WRITING_AGENT_DATA_DIR", str(data_dir))
    return data_dir


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
