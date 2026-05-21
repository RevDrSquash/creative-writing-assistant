"""Phase 1 NiceGUI application skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from nicegui import app, ui

APP_TITLE = "Writing Agent"

WORKSPACE_SPLIT_KEY = "workspace_split"
WORKSPACE_SPLIT_DEFAULT = 75

# Signs the session cookie that backs `app.storage.user`. Local-only and single-user
# for now; move to an env var with a random value before any shared deployment.
STORAGE_SECRET = "writing-agent-local-storage-secret"


@dataclass(frozen=True)
class NavigationItem:
    """Static navigation metadata for Phase 1 placeholder screens."""

    label: str
    path: str
    placeholder: str


@dataclass(frozen=True)
class SidebarGroup:
    """Static sidebar section with a non-clickable heading."""

    label: str
    items: tuple[NavigationItem, ...]


HEADER_NAV_ITEMS: tuple[NavigationItem, ...] = (
    NavigationItem("Workspace", "/workspace", "Main writing workspace"),
    NavigationItem("Models", "/models", "Model configuration and selection"),
    NavigationItem("Settings", "/settings", "Workspace settings"),
)

WORKSPACE_STORY_BIBLE_ITEMS: tuple[NavigationItem, ...] = (
    NavigationItem(
        "Narrative Style",
        "/workspace/narrative-style",
        "Narrative style guide placeholder",
    ),
    NavigationItem("Characters", "/workspace/characters", "Character list placeholder"),
    NavigationItem("Locations", "/workspace/locations", "Location list placeholder"),
    NavigationItem("Lore", "/workspace/lore", "Lore notes placeholder"),
)

WORKSPACE_SCENE_ITEMS: tuple[NavigationItem, ...] = (
    NavigationItem("New Scene", "/workspace/scenes/new", "New scene placeholder"),
)

WORKSPACE_SIDEBAR_GROUPS: tuple[SidebarGroup, ...] = (
    SidebarGroup("Story Bible", WORKSPACE_STORY_BIBLE_ITEMS),
    SidebarGroup("Scenes", WORKSPACE_SCENE_ITEMS),
)

WORKSPACE_SIDEBAR_ITEMS: tuple[NavigationItem, ...] = (
    *WORKSPACE_STORY_BIBLE_ITEMS,
    *WORKSPACE_SCENE_ITEMS,
)

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


def _find_item(items: Iterable[NavigationItem], path: str, fallback: NavigationItem) -> NavigationItem:
    return next((item for item in items if item.path == path), fallback)


def _render_header(active_path: str) -> None:
    with ui.header().classes("items-center justify-between"):
        with ui.row().classes("items-center gap-2"):
            ui.label(APP_TITLE).classes("text-lg font-semibold mr-4")
            for item in HEADER_NAV_ITEMS:
                button = ui.button(item.label, on_click=lambda path=item.path: ui.navigate.to(path))
                if item.path == active_path:
                    button.props("unelevated color=white text-color=primary")
                else:
                    button.props("flat color=white")

        with ui.button(icon="more_vert").props("flat round color=white"):
            with ui.menu():
                ui.menu_item("Import", on_click=lambda: ui.notify("Import placeholder"))
                ui.menu_item("Export", on_click=lambda: ui.notify("Export placeholder"))


def _render_sidebar(
    items: tuple[NavigationItem, ...],
    active_path: str,
    *,
    separator_before: str | None = None,
) -> None:
    with ui.left_drawer(value=True).props("bordered").classes("bg-grey-1"):
        with ui.column().classes("w-full gap-1"):
            for item in items:
                if item.path == separator_before:
                    ui.separator().classes("my-2")
                button = ui.button(item.label, on_click=lambda path=item.path: ui.navigate.to(path))
                button.classes("w-full justify-start")
                button.props("flat" if item.path != active_path else "unelevated color=primary")


def _render_grouped_sidebar(groups: tuple[SidebarGroup, ...], active_path: str) -> None:
    with ui.left_drawer(value=True).props("bordered").classes("bg-grey-1"):
        with ui.column().classes("w-full gap-1"):
            for index, group in enumerate(groups):
                if index:
                    ui.separator().classes("my-2")
                ui.label(group.label).classes(
                    "px-3 pt-2 text-xs font-semibold uppercase tracking-wide text-grey-7"
                )
                for item in group.items:
                    button = ui.button(item.label, on_click=lambda path=item.path: ui.navigate.to(path))
                    button.classes("w-full justify-start")
                    button.props("flat" if item.path != active_path else "unelevated color=primary")


def _render_page_shell(
    *,
    active_path: str,
    sidebar_items: tuple[NavigationItem, ...],
    separator_before: str | None = None,
) -> None:
    top_level_path = "/" + active_path.strip("/").split("/", maxsplit=1)[0]
    _render_header("/workspace" if top_level_path == "/" else top_level_path)
    _render_sidebar(sidebar_items, active_path, separator_before=separator_before)


def _workspace_page(active_path: str = "/workspace") -> None:
    _render_header("/workspace")
    _render_grouped_sidebar(WORKSPACE_SIDEBAR_GROUPS, active_path)

    app.storage.user.setdefault(WORKSPACE_SPLIT_KEY, WORKSPACE_SPLIT_DEFAULT)

    with ui.column().classes("w-full p-4"):
        splitter = ui.splitter(value=app.storage.user[WORKSPACE_SPLIT_KEY])
        splitter.bind_value(app.storage.user, WORKSPACE_SPLIT_KEY)
        with splitter.classes("w-full min-h-[78vh]"):
            with splitter.before:
                with ui.column().classes("w-full h-full gap-4 pr-4"):
                    ui.label("Editor Panel").classes("text-xl font-semibold")
                    ui.label(
                        "Phase 1 placeholder for Markdown scenes and Story Bible editing."
                    ).classes("text-grey-7")

            with splitter.after:
                with ui.column().classes("w-full h-full gap-4 pl-4"):
                    ui.label("AI Chat Interface").classes("text-xl font-semibold")
                    ui.label(
                        "Phase 1 placeholder for the future LangGraph-powered chat."
                    ).classes("text-grey-7")


def _render_models_shell(active_path: str) -> NavigationItem:
    active_item = _find_item(
        MODELS_SIDEBAR_ITEMS,
        active_path,
        NavigationItem("Models", "/models", "Model configuration workspace placeholder"),
    )
    _render_page_shell(
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


def _settings_page() -> None:
    _render_page_shell(active_path="/settings", sidebar_items=())
    with ui.column().classes("w-full gap-4 p-4"):
        ui.label("Settings").classes("text-2xl font-semibold")
        ui.label("Blank workspace settings placeholder for Phase 1.").classes("text-grey-7")


@ui.page("/")
def index() -> None:
    ui.navigate.to("/workspace")


@ui.page("/workspace")
def workspace() -> None:
    _workspace_page("/workspace")


@ui.page("/workspace/story-bible")
def workspace_story_bible() -> None:
    ui.navigate.to("/workspace/characters")


@ui.page("/workspace/characters")
def workspace_characters() -> None:
    _workspace_page("/workspace/characters")


@ui.page("/workspace/locations")
def workspace_locations() -> None:
    _workspace_page("/workspace/locations")


@ui.page("/workspace/lore")
def workspace_lore() -> None:
    _workspace_page("/workspace/lore")


@ui.page("/workspace/narrative-style")
def workspace_narrative_style() -> None:
    _workspace_page("/workspace/narrative-style")


@ui.page("/workspace/scenes")
def workspace_scenes() -> None:
    ui.navigate.to("/workspace/scenes/new")


@ui.page("/workspace/scenes/new")
def workspace_new_scene() -> None:
    _workspace_page("/workspace/scenes/new")


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


@ui.page("/settings")
def settings() -> None:
    _settings_page()


def main() -> None:
    """Run the local NiceGUI application."""

    ui.run(title=APP_TITLE, reload=False, storage_secret=STORAGE_SECRET)


if __name__ in {"__main__", "__mp_main__"}:
    main()
