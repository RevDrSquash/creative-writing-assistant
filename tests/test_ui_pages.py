"""In-process page tests using the simulated NiceGUI user.

These boot the real app (all @ui.page routes) with persistence redirected to a
temp directory, so they verify that every page actually renders and that basic
interactions work -- without a browser or network access.
"""

from __future__ import annotations

import json
from pathlib import Path

from nicegui.testing import User


async def test_index_redirects_to_workspace(user: User) -> None:
    await user.open("/")
    await user.should_see("Editor Panel")


async def test_workspace_renders_editor_and_chat(user: User) -> None:
    await user.open("/workspace")
    await user.should_see("Editor Panel")
    await user.should_see("Send")
    # Chat must be enabled because the test environment provides a valid-looking key.
    await user.should_not_see("Chat is disabled because model settings are invalid.")


async def test_workspace_sidebar_navigates_to_placeholder(user: User) -> None:
    await user.open("/workspace")
    user.find("Characters").click()
    await user.should_see("Character list placeholder")


async def test_settings_page_renders(user: User) -> None:
    await user.open("/settings")
    await user.should_see("Settings")


async def test_models_redirects_to_selection(user: User) -> None:
    await user.open("/models")
    await user.should_see("Assign model configurations to LangGraph nodes.")


async def test_model_selection_save_writes_isolated_store(
    user: User,
    isolated_data_dir: Path,
) -> None:
    await user.open("/models/selection")
    await user.should_see("Chat Agent")

    user.find("Save").click()
    await user.should_see("Model selection saved.")

    config_path = isolated_data_dir / "model_configs.json"
    assert config_path.is_file()
    stored = json.loads(config_path.read_text(encoding="utf-8"))
    assert stored["selections"]["chat"] == "standard"


async def test_new_model_page_renders_with_catalog(
    user: User,
    stub_model_catalog: list,
) -> None:
    await user.open("/models/new")
    await user.should_see("Create a custom reusable model configuration.")
    await user.should_see("Config ID")


async def test_standard_model_config_page_renders(
    user: User,
    stub_model_catalog: list,
) -> None:
    await user.open("/models/configs/standard")
    await user.should_see("Standard model configuration")
    await user.should_see("System prompt prefix")


async def test_debug_page_renders_empty_state(user: User) -> None:
    await user.open("/debug")
    await user.should_see("LLM calls will appear here after the chat agent invokes a model.")
    await user.should_see("No LLM calls yet.")
