"""Smoke tests for the Phase 1 NiceGUI UI skeleton."""

import importlib
from collections.abc import Iterable

import app.ui.app as ui_app
from app.models.config import ModelConfig
from app.persistence import JsonFileModelConfigStore, ModelConfigRepository
from app.ui import navigation
from app.ui.navigation import NavigationItem
from app.ui.pages import debug, models, workspace


def labels(items: Iterable[NavigationItem]) -> set[str]:
    return {item.label for item in items}


def paths(items: Iterable[NavigationItem]) -> set[str]:
    return {item.path for item in items}


def test_ui_entrypoint_is_available() -> None:
    assert callable(ui_app.main)


def test_header_navigation_has_phase_one_screens() -> None:
    assert labels(navigation.HEADER_NAV_ITEMS) == {"Workspace", "Models", "Settings", "Debug"}
    assert paths(navigation.HEADER_NAV_ITEMS) == {"/workspace", "/models", "/settings", "/debug"}


def test_workspace_sidebar_has_story_bible_sections() -> None:
    sidebar_labels = labels(workspace.WORKSPACE_STORY_BIBLE_ITEMS)

    assert sidebar_labels == {"Narrative Style", "World", "Characters", "Timeline"}
    assert paths(workspace.WORKSPACE_STORY_BIBLE_ITEMS) == {
        "/workspace/narrative-style",
        "/workspace/world",
        "/workspace/characters",
        "/workspace/timeline",
    }


def test_models_sidebar_has_selection_new_model_and_configs() -> None:
    sidebar_labels = labels(models.MODELS_SIDEBAR_ITEMS)

    assert {"Model Selection", "New Model"}.issubset(sidebar_labels)
    assert labels(models.MODEL_CONFIGURATIONS).issubset(sidebar_labels)
    assert models.MODELS_SIDEBAR_ITEMS == (
        *models.MODEL_STATIC_SIDEBAR_ITEMS,
        *models.MODEL_CONFIGURATIONS,
    )


def test_models_sidebar_includes_custom_configs_from_repository(tmp_path) -> None:
    repo = ModelConfigRepository(JsonFileModelConfigStore(tmp_path / "model_configs.json"))
    repo.save_config(ModelConfig(id="custom", name="Custom", model="example/custom"))

    sidebar_labels = labels(models._models_sidebar_items(repo))

    assert {"Model Selection", "New Model", "Custom"}.issubset(sidebar_labels)


def test_models_routes_have_distinct_placeholder_renderers() -> None:
    assert callable(models._model_selection_page)
    assert callable(models._new_model_page)
    assert callable(models._model_configuration_page)


def test_debug_routes_have_distinct_renderers() -> None:
    assert callable(debug._debug_index_page)
    assert callable(debug._debug_call_page)


def test_debug_token_counts_prefer_usage_metadata() -> None:
    counts = debug._token_counts(
        {
            "usage_metadata": {
                "input_tokens": 12,
                "output_tokens": 8,
                "total_tokens": 20,
                "output_token_details": {"reasoning": 3},
            }
        }
    )

    assert counts == {"Input": 12, "Output": 8, "Reasoning": 3, "Total": 20}


def test_debug_token_counts_fall_back_to_token_usage() -> None:
    counts = debug._token_counts(
        {
            "token_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "total_tokens": 140,
                "completion_tokens_details": {"reasoning_tokens": 10},
            }
        }
    )

    assert counts == {"Input": 100, "Output": 40, "Reasoning": 10, "Total": 140}


def test_debug_prompt_blocks_split_into_components() -> None:
    blocks = debug._prompt_blocks(
        [
            {"role": "system", "content": "System instructions"},
            {"role": "user", "content": "Revise the line."},
            {
                "role": "assistant",
                "content": "Working on it.",
                "tool_calls": [{"name": "update_scene_blueprint", "args": {"premise": "new"}}],
            },
            {"role": "tool", "content": "Updated.", "name": "update_scene_blueprint"},
        ]
    )

    assert [(title, kind) for title, kind, _ in blocks] == [
        ("System Prompt", "markdown"),
        ("User Message", "markdown"),
        ("Assistant Message", "markdown"),
        ("Tool Call: update_scene_blueprint", "json"),
        ("Tool Response: update_scene_blueprint", "markdown"),
    ]
    tool_call_content = next(content for _, kind, content in blocks if kind == "json")
    assert '"name": "update_scene_blueprint"' in tool_call_content
    assert '"premise": "new"' in tool_call_content


def test_debug_escape_html_escapes_canvas_tags() -> None:
    escaped = debug._escape_html("Use <canvas>prose</canvas> & more")

    assert escaped == "Use &lt;canvas&gt;prose&lt;/canvas&gt; &amp; more"


def test_ui_page_modules_import_cleanly() -> None:
    assert importlib.import_module("app.ui.app")
    assert importlib.import_module("app.ui.pages.workspace")
    assert importlib.import_module("app.ui.pages.models")
    assert importlib.import_module("app.ui.pages.settings")
    assert importlib.import_module("app.ui.pages.debug")
