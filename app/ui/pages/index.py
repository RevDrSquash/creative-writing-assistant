"""Root route for the NiceGUI app."""

from nicegui import ui


@ui.page("/")
def index() -> None:
    ui.navigate.to("/workspace")
