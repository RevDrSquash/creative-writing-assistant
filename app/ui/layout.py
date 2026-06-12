"""Shared NiceGUI layout helpers for app chrome."""

from __future__ import annotations

import re
from collections.abc import Iterable

from nicegui import events, ui

from app.persistence.world_zip import export_world_zip, import_world_zip
from app.ui.config import APP_TITLE
from app.ui.navigation import HEADER_NAV_ITEMS, NavigationItem
from app.world.store import get_world, replace_world


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
                ui.menu_item("Import World", on_click=_open_import_dialog)
                ui.menu_item("Export World", on_click=_export_world)


def _export_world() -> None:
    world = get_world()
    slug = re.sub(r"[^a-z0-9]+", "-", world.metadata.title.lower()).strip("-") or "world"
    ui.download.content(export_world_zip(world), f"{slug}.zip")


def _open_import_dialog() -> None:
    async def handle_upload(event: events.UploadEventArguments) -> None:
        data = await event.file.read()
        try:
            world = import_world_zip(data)
        except ValueError as exc:
            ui.notify(f"Import failed: {exc}", type="negative")
            return
        replace_world(world)
        dialog.close()
        ui.notify("World imported.", type="positive")
        ui.navigate.to("/workspace")

    with ui.dialog() as dialog, ui.card():
        ui.label("Import World").classes("text-lg font-semibold")
        ui.label(
            "Importing a world ZIP replaces the current world entirely. "
            "Export the current world first if you want to keep it."
        ).classes("text-grey-7")
        ui.upload(on_upload=handle_upload, auto_upload=True).props('accept=".zip"').classes(
            "w-full"
        )
        ui.button("Cancel", on_click=dialog.close).props("flat")

    dialog.open()


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


def render_page_shell(
    *,
    active_path: str,
    sidebar_items: tuple[NavigationItem, ...],
    separator_before: str | None = None,
) -> None:
    top_level_path = "/" + active_path.strip("/").split("/", maxsplit=1)[0]
    render_header("/workspace" if top_level_path == "/" else top_level_path)
    render_sidebar(sidebar_items, active_path, separator_before=separator_before)
