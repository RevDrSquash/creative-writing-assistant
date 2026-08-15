"""NiceGUI application entry point."""

from nicegui import app as nicegui_app
from nicegui import ui

import app.ui.pages  # noqa: F401  # importing registers all @ui.page routes
from app.ui.config import APP_TITLE, STORAGE_SECRET
from app.ui.console_noise import install_logging_filters, install_loop_exception_handler


def main() -> None:
    """Run the local NiceGUI application."""

    install_logging_filters()
    nicegui_app.on_startup(install_loop_exception_handler)
    ui.run(title=APP_TITLE, reload=False, storage_secret=STORAGE_SECRET)


if __name__ in {"__main__", "__mp_main__"}:
    main()
