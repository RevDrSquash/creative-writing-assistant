"""NiceGUI application entry point."""

from nicegui import ui

import app.ui.pages  # noqa: F401  # importing registers all @ui.page routes
from app.ui.config import APP_TITLE, STORAGE_SECRET


def main() -> None:
    """Run the local NiceGUI application."""

    ui.run(title=APP_TITLE, reload=False, storage_secret=STORAGE_SECRET)


if __name__ in {"__main__", "__mp_main__"}:
    main()
