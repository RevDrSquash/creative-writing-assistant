"""Smoke tests for the Phase 1 NiceGUI UI skeleton."""

import importlib
from collections.abc import Iterable

import app.ui.app as ui_app
from app.models.config import ModelConfig
from app.persistence import JsonFileModelConfigStore, ModelConfigRepository
from app.ui import navigation
from app.ui.navigation import NavigationItem, SidebarGroup
from app.ui.pages import models, workspace


def labels(items: Iterable[NavigationItem]) -> set[str]:
    return {item.label for item in items}


def paths(items: Iterable[NavigationItem]) -> set[str]:
    return {item.path for item in items}


def group_labels(groups: Iterable[SidebarGroup]) -> set[str]:
    return {group.label for group in groups}


def test_ui_entrypoint_is_available() -> None:
    assert callable(ui_app.main)


def test_header_navigation_has_phase_one_screens() -> None:
    assert labels(navigation.HEADER_NAV_ITEMS) == {"Workspace", "Models", "Settings"}
    assert paths(navigation.HEADER_NAV_ITEMS) == {"/workspace", "/models", "/settings"}


def test_workspace_sidebar_has_story_bible_and_scenes() -> None:
    sidebar_labels = labels(workspace.WORKSPACE_SIDEBAR_ITEMS)

    assert group_labels(workspace.WORKSPACE_SIDEBAR_GROUPS) == {"Story Bible", "Scenes"}
    assert "Story Bible" not in sidebar_labels
    assert "Scenes" not in sidebar_labels
    assert {"Characters", "Locations", "Lore", "Narrative Style", "New Scene"}.issubset(
        sidebar_labels
    )


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


def test_ui_page_modules_import_cleanly() -> None:
    assert importlib.import_module("app.ui.app")
    assert importlib.import_module("app.ui.pages.workspace")
    assert importlib.import_module("app.ui.pages.models")
    assert importlib.import_module("app.ui.pages.settings")
