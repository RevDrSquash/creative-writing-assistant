"""Suppress harmless console noise from browser probes and dropped connections.

Two kinds of log pollution show up when running locally and closing browser windows:

- Chromium-based browsers and IDE debuggers probe DevTools-protocol discovery endpoints
  (e.g. ``/json/version``) on local servers. The app does not serve them, so NiceGUI's
  404 handler logs an ``<url> not found`` warning for each probe.
- On Windows, the asyncio Proactor event loop reports ``ConnectionResetError``
  (WinError 10054) with a full traceback when the browser force-closes its TCP
  connection, e.g. when the user closes the window.

Both are side-effect free; the filters here drop only these specific messages.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

_DEVTOOLS_PROBE_PATHS = {
    "/json",
    "/json/list",
    "/json/version",
    "/.well-known/appspecific/com.chrome.devtools.json",
}

_NOT_FOUND_SUFFIX = " not found"


class DevToolsProbeFilter(logging.Filter):
    """Drop NiceGUI ``<url> not found`` warnings caused by DevTools discovery probes."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if not message.endswith(_NOT_FOUND_SUFFIX):
            return True
        url = message[: -len(_NOT_FOUND_SUFFIX)]
        return urlsplit(url).path not in _DEVTOOLS_PROBE_PATHS


def silence_connection_reset(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """Asyncio exception handler that drops browser-disconnect ConnectionResetError noise."""

    if isinstance(context.get("exception"), ConnectionResetError):
        return
    loop.default_exception_handler(context)


def install_logging_filters() -> None:
    """Attach the DevTools probe filter to NiceGUI's logger. Call before ``ui.run``."""

    logging.getLogger("nicegui").addFilter(DevToolsProbeFilter())


def install_loop_exception_handler() -> None:
    """Install the connection-reset handler on the running loop. Call from ``on_startup``."""

    asyncio.get_running_loop().set_exception_handler(silence_connection_reset)
