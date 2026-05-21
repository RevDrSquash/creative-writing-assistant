"""Smoke tests for the Phase 1 NiceGUI UI skeleton."""

from collections.abc import Iterable

import app.ui.app as app
from app.ui.app import NavigationItem, SidebarGroup


def labels(items: Iterable[NavigationItem]) -> set[str]:
    return {item.label for item in items}


def paths(items: Iterable[NavigationItem]) -> set[str]:
    return {item.path for item in items}


def group_labels(groups: Iterable[SidebarGroup]) -> set[str]:
    return {group.label for group in groups}


def test_ui_entrypoint_is_available() -> None:
    assert callable(app.main)


def test_header_navigation_has_phase_one_screens() -> None:
    assert labels(app.HEADER_NAV_ITEMS) == {"Workspace", "Models", "Settings"}
    assert paths(app.HEADER_NAV_ITEMS) == {"/workspace", "/models", "/settings"}


def test_workspace_sidebar_has_story_bible_and_scenes() -> None:
    sidebar_labels = labels(app.WORKSPACE_SIDEBAR_ITEMS)

    assert group_labels(app.WORKSPACE_SIDEBAR_GROUPS) == {"Story Bible", "Scenes"}
    assert "Story Bible" not in sidebar_labels
    assert "Scenes" not in sidebar_labels
    assert {"Characters", "Locations", "Lore", "Narrative Style", "New Scene"}.issubset(
        sidebar_labels
    )


def test_models_sidebar_has_selection_new_model_and_configs() -> None:
    sidebar_labels = labels(app.MODELS_SIDEBAR_ITEMS)

    assert {"Model Selection", "New Model"}.issubset(sidebar_labels)
    assert labels(app.MODEL_CONFIGURATIONS).issubset(sidebar_labels)
    assert app.MODELS_SIDEBAR_ITEMS == (
        *app.MODEL_STATIC_SIDEBAR_ITEMS,
        *app.MODEL_CONFIGURATIONS,
    )


def test_models_routes_have_distinct_placeholder_renderers() -> None:
    assert callable(app._model_selection_page)
    assert callable(app._new_model_page)
    assert callable(app._model_configuration_page)
