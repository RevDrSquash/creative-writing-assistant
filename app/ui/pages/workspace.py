"""Workspace pages for editor, Story Bible, scenes, and chat placeholders."""

from __future__ import annotations

from nicegui import app, ui

from app.ui.layout import render_grouped_sidebar, render_header
from app.ui.navigation import NavigationItem, SidebarGroup

WORKSPACE_SPLIT_KEY = "workspace_split"
WORKSPACE_SPLIT_DEFAULT = 75

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


def _workspace_page(active_path: str = "/workspace") -> None:
    render_header("/workspace")
    render_grouped_sidebar(WORKSPACE_SIDEBAR_GROUPS, active_path)

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
