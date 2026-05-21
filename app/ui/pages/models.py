"""Model selection and model configuration placeholder pages."""

from __future__ import annotations

from nicegui import ui

from app.ui.layout import find_item, render_page_shell
from app.ui.navigation import NavigationItem

MODEL_CONFIGURATIONS: tuple[NavigationItem, ...] = (
    NavigationItem("Small Drafting Model", "/models/configs/small", "Small model config placeholder"),
    NavigationItem("Standard Writing Model", "/models/configs/standard", "Standard model config placeholder"),
    NavigationItem("Large Review Model", "/models/configs/large", "Large model config placeholder"),
)

MODEL_STATIC_SIDEBAR_ITEMS: tuple[NavigationItem, ...] = (
    NavigationItem("Model Selection", "/models/selection", "Assign model configs to graph nodes"),
    NavigationItem("New Model", "/models/new", "Create a model configuration"),
)

MODELS_SIDEBAR_ITEMS: tuple[NavigationItem, ...] = (
    *MODEL_STATIC_SIDEBAR_ITEMS,
    *MODEL_CONFIGURATIONS,
)


def _render_models_shell(active_path: str) -> NavigationItem:
    active_item = find_item(
        MODELS_SIDEBAR_ITEMS,
        active_path,
        NavigationItem("Models", "/models", "Model configuration workspace placeholder"),
    )
    render_page_shell(
        active_path=active_path,
        sidebar_items=MODELS_SIDEBAR_ITEMS,
        separator_before=MODEL_CONFIGURATIONS[0].path,
    )
    return active_item


def _model_selection_page() -> None:
    active_item = _render_models_shell("/models/selection")
    with ui.column().classes("w-full gap-4 p-4"):
        ui.label(active_item.label).classes("text-2xl font-semibold")
        ui.label(active_item.placeholder).classes("text-grey-7")


def _new_model_page() -> None:
    active_item = _render_models_shell("/models/new")
    with ui.column().classes("w-full gap-4 p-4"):
        ui.label(active_item.label).classes("text-2xl font-semibold")
        ui.label(active_item.placeholder).classes("text-grey-7")


def _model_configuration_page(active_path: str) -> None:
    active_item = _render_models_shell(active_path)
    with ui.column().classes("w-full gap-4 p-4"):
        ui.label(active_item.label).classes("text-2xl font-semibold")
        ui.label(active_item.placeholder).classes("text-grey-7")


@ui.page("/models")
def models() -> None:
    ui.navigate.to("/models/selection")


@ui.page("/models/selection")
def model_selection() -> None:
    _model_selection_page()


@ui.page("/models/new")
def new_model() -> None:
    _new_model_page()


@ui.page("/models/configs/small")
def small_model_config() -> None:
    _model_configuration_page("/models/configs/small")


@ui.page("/models/configs/standard")
def standard_model_config() -> None:
    _model_configuration_page("/models/configs/standard")


@ui.page("/models/configs/large")
def large_model_config() -> None:
    _model_configuration_page("/models/configs/large")
