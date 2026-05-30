"""Model selection and model configuration pages."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from nicegui import ui
from pydantic import ValidationError

from app.models.catalog import OpenRouterModel, fetch_openrouter_models
from app.models.config import (
    DEFAULT_MODEL_CONFIGS,
    GRAPH_NODES,
    ModelConfig,
    ReasoningEffort,
)
from app.models.settings import ModelSettings
from app.persistence import ModelConfigRepository, get_model_config_repository
from app.ui.layout import find_item, render_page_shell
from app.ui.navigation import NavigationItem

MODEL_CONFIGURATIONS: tuple[NavigationItem, ...] = (
    *(
        NavigationItem(config.name, f"/models/configs/{config.id}", f"{config.name} model configuration")
        for config in DEFAULT_MODEL_CONFIGS
    ),
)

MODEL_STATIC_SIDEBAR_ITEMS: tuple[NavigationItem, ...] = (
    NavigationItem("Model Selection", "/models/selection", "Assign model configs to graph nodes"),
    NavigationItem("New Model", "/models/new", "Create a model configuration"),
)

MODELS_SIDEBAR_ITEMS: tuple[NavigationItem, ...] = (
    *MODEL_STATIC_SIDEBAR_ITEMS,
    *MODEL_CONFIGURATIONS,
)


def _model_configurations(repo: ModelConfigRepository | None = None) -> tuple[NavigationItem, ...]:
    repository = repo or get_model_config_repository()
    return tuple(
        NavigationItem(
            config.name,
            f"/models/configs/{config.id}",
            f"{config.name} model configuration",
        )
        for config in repository.list_configs()
    )


def _models_sidebar_items(repo: ModelConfigRepository | None = None) -> tuple[NavigationItem, ...]:
    return (*MODEL_STATIC_SIDEBAR_ITEMS, *_model_configurations(repo))


def _render_models_shell(
    active_path: str,
    repo: ModelConfigRepository | None = None,
) -> NavigationItem:
    sidebar_items = _models_sidebar_items(repo)
    active_item = find_item(
        sidebar_items,
        active_path,
        NavigationItem("Models", "/models", "Model configuration workspace placeholder"),
    )
    render_page_shell(
        active_path=active_path,
        sidebar_items=sidebar_items,
        separator_before=sidebar_items[len(MODEL_STATIC_SIDEBAR_ITEMS)].path
        if len(sidebar_items) > len(MODEL_STATIC_SIDEBAR_ITEMS)
        else None,
    )
    return active_item


def _model_selection_page() -> None:
    repo = get_model_config_repository()
    active_item = _render_models_shell("/models/selection", repo)
    configs = repo.list_configs()
    config_options = {config.id: f"{config.name} ({config.model})" for config in configs}

    with ui.column().classes("w-full max-w-3xl gap-4 p-4"):
        ui.label(active_item.label).classes("text-2xl font-semibold")
        ui.label("Assign model configurations to LangGraph nodes.").classes("text-grey-7")

        with ui.card().classes("w-full gap-4"):
            for node in GRAPH_NODES:
                current_selection = repo.get_selection(node.node_id) or node.default_config_id
                with ui.row().classes("w-full items-end gap-4"):
                    with ui.column().classes("grow gap-1"):
                        ui.label(node.label).classes("font-medium")
                        ui.label(f"Default: {node.default_config_id}").classes("text-sm text-grey-7")
                    select = ui.select(
                        config_options,
                        value=current_selection if current_selection in config_options else node.default_config_id,
                        label="Configuration",
                    ).classes("min-w-80")
                    ui.button(
                        "Save",
                        on_click=_selection_save_handler(
                            repo,
                            node.node_id,
                            cast(Callable[[], str], lambda select=select: select.value),
                        ),
                    ).props("unelevated color=primary")


def _new_model_page() -> None:
    active_item = _render_models_shell("/models/new")
    with ui.column().classes("w-full max-w-3xl gap-4 p-4"):
        ui.label(active_item.label).classes("text-2xl font-semibold")
        ui.label("Create a custom reusable model configuration.").classes("text-grey-7")
        _render_config_form(ModelConfig(id="", name="", model=""), is_new=True)


def _model_configuration_page(active_path: str) -> None:
    repo = get_model_config_repository()
    active_item = _render_models_shell(active_path, repo)
    config_id = active_path.rstrip("/").rsplit("/", maxsplit=1)[-1]
    config = repo.get_config(config_id)

    with ui.column().classes("w-full max-w-3xl gap-4 p-4"):
        ui.label(active_item.label).classes("text-2xl font-semibold")
        if config is None:
            ui.label(f"No model configuration exists for '{config_id}'.").classes("text-negative")
            return

        ui.label(active_item.placeholder).classes("text-grey-7")
        _render_config_form(config, is_new=False)


def _render_config_form(config: ModelConfig, *, is_new: bool) -> None:
    repo = get_model_config_repository()
    catalog = _fetch_catalog()
    model_options = _model_options(catalog)

    with ui.card().classes("w-full gap-4"):
        config_id = ui.input("Config ID", value=config.id).classes("w-full")
        if not is_new:
            config_id.props("readonly")

        name = ui.input("Name", value=config.name).classes("w-full")

        model_id = ui.input("Model ID", value=config.model).classes("w-full")
        if model_options:
            with ui.row().classes("w-full items-end gap-3"):
                model_select = ui.select(
                    model_options,
                    value=config.model if config.model in model_options else None,
                    label="OpenRouter catalog",
                ).classes("grow")
                model_select.on_value_change(lambda event: model_id.set_value(event.value))
                ui.button(
                    "Refresh",
                    on_click=_catalog_refresh_handler(model_select),
                ).props("outline")
        else:
            with ui.row().classes("w-full items-center gap-3"):
                ui.label("Live catalog unavailable; enter the model ID manually.").classes(
                    "text-sm text-grey-7"
                )
                ui.button("Retry", on_click=lambda: ui.navigate.to(_current_config_path(config, is_new))).props(
                    "outline"
                )

        temperature = ui.number(
            "Temperature",
            value=config.temperature,
            min=0,
            max=2,
            step=0.1,
            format="%.2f",
        ).classes("w-full")
        temperature.props("clearable")

        reasoning = ui.select(
            {"": "No reasoning override", "low": "Low", "medium": "Medium", "high": "High"},
            value=config.reasoning_effort or "",
            label="Reasoning effort",
        ).classes("w-full")

        prefix = ui.textarea(
            "System prompt prefix",
            value=config.system_prompt_prefix,
            placeholder="Optional text prepended before the base writing-assistant prompt.",
        ).classes("w-full")
        prefix.props("autogrow")

        with ui.row().classes("gap-3"):
            ui.button(
                "Save",
                on_click=_config_save_handler(
                    repo,
                    cast(Callable[[], str], lambda: config_id.value),
                    cast(Callable[[], str], lambda: name.value),
                    cast(Callable[[], str], lambda: model_id.value),
                    lambda: temperature.value,
                    cast(Callable[[], str], lambda: reasoning.value),
                    cast(Callable[[], str], lambda: prefix.value),
                    is_new=is_new,
                ),
            ).props("unelevated color=primary")
            if not is_new:
                ui.button(
                    "Reset/Delete",
                    on_click=_config_delete_handler(repo, config.id),
                ).props("outline color=negative")


def _selection_save_handler(
    repo: ModelConfigRepository,
    node_id: str,
    selected_id: Callable[[], str],
) -> Callable[[], None]:
    def save_selection() -> None:
        try:
            repo.set_selection(node_id, selected_id())
        except ValueError as exc:
            ui.notify(str(exc), color="negative")
            return
        ui.notify("Model selection saved.", color="positive")

    return save_selection


def _config_save_handler(
    repo: ModelConfigRepository,
    config_id: Callable[[], str],
    name: Callable[[], str],
    model_id: Callable[[], str],
    temperature: Callable[[], float | None],
    reasoning_effort: Callable[[], str],
    system_prompt_prefix: Callable[[], str],
    *,
    is_new: bool,
) -> Callable[[], None]:
    def save_config() -> None:
        try:
            config = ModelConfig(
                id=config_id().strip(),
                name=name().strip(),
                model=model_id().strip(),
                temperature=temperature(),
                reasoning_effort=_reasoning_effort(reasoning_effort()),
                system_prompt_prefix=system_prompt_prefix() or "",
            )
        except ValidationError as exc:
            ui.notify(str(exc), color="negative")
            return

        if not config.id or not config.name or not config.model:
            ui.notify("Config ID, name, and model ID are required.", color="negative")
            return

        if is_new and repo.get_config(config.id) is not None:
            ui.notify(f"A config named '{config.id}' already exists.", color="negative")
            return

        repo.save_config(config)
        ui.notify("Model configuration saved.", color="positive")
        ui.navigate.to(f"/models/configs/{config.id}")

    return save_config


def _config_delete_handler(repo: ModelConfigRepository, config_id: str) -> Callable[[], None]:
    def delete_config() -> None:
        repo.delete_config(config_id)
        ui.notify("Default configs are reset; custom configs are deleted.", color="positive")
        ui.navigate.to("/models/selection")

    return delete_config


def _catalog_refresh_handler(model_select: ui.select) -> Callable[[], None]:
    def refresh_catalog() -> None:
        model_options = _model_options(_fetch_catalog(refresh=True))
        if model_options:
            model_select.set_options(model_options)
            ui.notify("OpenRouter catalog refreshed.", color="positive")
        else:
            ui.notify("OpenRouter catalog is unavailable.", color="warning")

    return refresh_catalog


def _fetch_catalog(*, refresh: bool = False) -> list[OpenRouterModel]:
    try:
        api_key = ModelSettings().openrouter_api_key
    except (ValidationError, ValueError):
        api_key = ""
    return fetch_openrouter_models(api_key, refresh=refresh)


def _model_options(catalog: list[OpenRouterModel]) -> dict[str, str]:
    return {model.id: f"{model.name} ({model.id})" for model in catalog}


def _reasoning_effort(value: str | None) -> ReasoningEffort | None:
    if value in {"low", "medium", "high"}:
        return cast(ReasoningEffort, value)
    return None


def _current_config_path(config: ModelConfig, is_new: bool) -> str:
    if is_new:
        return "/models/new"
    return f"/models/configs/{config.id}"


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


@ui.page("/models/configs/{config_id}")
def custom_model_config(config_id: str) -> None:
    _model_configuration_page(f"/models/configs/{config_id}")
