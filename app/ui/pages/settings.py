"""Settings placeholder page."""

from nicegui import ui

from app.ui.layout import render_page_shell


def _settings_page() -> None:
    render_page_shell(active_path="/settings", sidebar_items=())
    with ui.column().classes("w-full gap-4 p-4"):
        ui.label("Settings").classes("text-2xl font-semibold")
        ui.label("Blank workspace settings placeholder for Phase 1.").classes("text-grey-7")


@ui.page("/settings")
def settings() -> None:
    _settings_page()
