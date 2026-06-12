"""Shared NiceGUI layout helpers for app chrome."""

from __future__ import annotations

from collections.abc import Iterable

from nicegui import ui

from app.ui.config import APP_TITLE
from app.ui.navigation import HEADER_NAV_ITEMS, NavigationItem, SidebarGroup


def find_item(
    items: Iterable[NavigationItem],
    path: str,
    fallback: NavigationItem,
) -> NavigationItem:
    return next((item for item in items if item.path == path), fallback)


def render_header(active_path: str) -> None:
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


def render_sidebar(
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


def render_grouped_sidebar(groups: tuple[SidebarGroup, ...], active_path: str) -> None:
    with ui.left_drawer(value=True).props("bordered").classes("bg-grey-1"):
        with ui.column().classes("w-full gap-1"):
            for index, group in enumerate(groups):
                if index:
                    ui.separator().classes("my-2")
                ui.label(group.label).classes(
                    "px-3 pt-2 text-xs font-semibold uppercase tracking-wide text-grey-7"
                )
                for item in group.items:
                    button = ui.button(
                        item.label, on_click=lambda path=item.path: ui.navigate.to(path)
                    )
                    button.classes("w-full justify-start")
                    button.props("flat" if item.path != active_path else "unelevated color=primary")


def render_page_shell(
    *,
    active_path: str,
    sidebar_items: tuple[NavigationItem, ...],
    separator_before: str | None = None,
) -> None:
    top_level_path = "/" + active_path.strip("/").split("/", maxsplit=1)[0]
    render_header("/workspace" if top_level_path == "/" else top_level_path)
    render_sidebar(sidebar_items, active_path, separator_before=separator_before)
