"""Shared NiceGUI layout helpers for app chrome."""

from __future__ import annotations

import re
from collections.abc import Iterable

from nicegui import app, events, ui

from app.graphs.jobs import get_job_manager
from app.persistence.story_export import export_story_zip
from app.persistence.world_zip import export_world_zip, import_world_zip
from app.ui.config import APP_TITLE
from app.ui.navigation import HEADER_NAV_ITEMS, NavigationItem
from app.world.store import clear_world, get_world, replace_world


def find_item(
    items: Iterable[NavigationItem],
    path: str,
    fallback: NavigationItem,
) -> NavigationItem:
    return next((item for item in items if item.path == path), fallback)


def render_header(active_path: str) -> None:
    manager = get_job_manager()

    with ui.header().classes("items-center justify-between"):
        with ui.row().classes("items-center gap-2"):
            ui.label(APP_TITLE).classes("text-lg font-semibold mr-4")
            for item in HEADER_NAV_ITEMS:
                button = ui.button(item.label, on_click=lambda path=item.path: ui.navigate.to(path))
                if item.path == active_path:
                    button.props("unelevated color=white text-color=primary")
                else:
                    button.props("flat color=white")

            @ui.refreshable
            def running_jobs_indicator() -> None:
                count = len(manager.running_jobs())
                if count:
                    with ui.row().classes("items-center gap-1 ml-2"):
                        ui.spinner(size="sm").mark("header-jobs-spinner")
                        ui.label(str(count)).classes("text-sm").mark("header-jobs-count")

            running_jobs_indicator()
            ui.timer(1.0, running_jobs_indicator.refresh)

        overflow_button = ui.button(icon="more_vert").props("flat round color=white")
        overflow_button.mark("header-overflow-menu")
        with overflow_button:
            with ui.menu():
                ui.menu_item("Import World", on_click=_open_import_dialog)
                ui.menu_item("Export World", on_click=_export_world)
                ui.menu_item("Export Scenes", on_click=_export_scenes)
                clear_item = ui.menu_item("Clear State...", on_click=_open_clear_dialog)
                clear_item.mark("clear-state-menu-item")

    _render_job_completion_toasts()


def _render_job_completion_toasts() -> None:
    manager = get_job_manager()
    notified: list[str] = app.storage.user.setdefault("notified_job_ids", [])

    def poll_finished_jobs() -> None:
        for job in manager.finished_jobs():
            if job.id in notified:
                continue
            notified.append(job.id)
            if job.status == "finished":
                if job.kind == "scene_generation":
                    ui.notify(f"{job.label} generated", type="positive")
                elif job.kind == "chat_turn":
                    ui.notify("Agent reply ready", type="positive")
            elif job.status == "failed":
                if job.kind == "scene_generation":
                    ui.notify(
                        f"Scene generation failed: {job.error or 'unknown error'}",
                        type="negative",
                    )
                elif job.kind == "chat_turn":
                    ui.notify(job.error or "Chat agent error", type="negative")

    ui.timer(1.0, poll_finished_jobs)


def _slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "world"


def _export_world() -> None:
    world = get_world()
    ui.download.content(export_world_zip(world), f"{_slugify(world.metadata.title)}.zip")


def _export_scenes() -> None:
    world = get_world()
    ui.download.content(
        export_story_zip(world),
        f"{_slugify(world.metadata.title)}-story.zip",
    )


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


def _open_clear_dialog() -> None:
    with ui.dialog() as dialog, ui.card():
        ui.label("Clear State").classes("text-lg font-semibold")
        ui.label(
            "This permanently removes selected story content. "
            "Export the current world first if you want to keep it."
        ).classes("text-grey-7")

        everything = ui.checkbox("Everything", value=False)
        story_bible = ui.checkbox("Story Bible", value=False)
        scenes = ui.checkbox("Scenes", value=False)

        def sync_everything(event: events.ValueChangeEventArguments) -> None:
            story_bible.value = event.value
            scenes.value = event.value

        everything.on_value_change(sync_everything)

        def handle_clear() -> None:
            if not story_bible.value and not scenes.value:
                ui.notify("Select at least one item to clear.", type="warning")
                return
            clear_world(story_bible=story_bible.value, scenes=scenes.value)
            dialog.close()
            ui.notify("State cleared.", type="positive")
            ui.navigate.to("/workspace")

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Cancel", on_click=dialog.close).props("flat")
            clear_button = ui.button("Clear", on_click=handle_clear).props("color=negative")
            clear_button.mark("clear-state-confirm-button")

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
