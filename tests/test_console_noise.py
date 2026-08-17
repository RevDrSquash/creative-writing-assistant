"""Tests for the console-noise suppression in app.ui.console_noise."""

import logging
from unittest.mock import Mock

from app.ui.console_noise import DevToolsProbeFilter, silence_connection_reset


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="nicegui",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=None,
        exc_info=None,
    )


class TestDevToolsProbeFilter:
    def test_drops_devtools_probe_404s(self) -> None:
        probe_filter = DevToolsProbeFilter()
        for path in (
            "/json",
            "/json/list",
            "/json/version",
            "/.well-known/appspecific/com.chrome.devtools.json",
        ):
            record = _record(f"http://localhost:8080{path} not found")
            assert probe_filter.filter(record) is False, path

    def test_keeps_genuine_404_warnings(self) -> None:
        probe_filter = DevToolsProbeFilter()
        record = _record("http://localhost:8080/missing-page not found")
        assert probe_filter.filter(record) is True

    def test_keeps_probe_path_with_query_string(self) -> None:
        probe_filter = DevToolsProbeFilter()
        record = _record("http://localhost:8080/json/version?x=1 not found")
        assert probe_filter.filter(record) is False

    def test_keeps_unrelated_messages(self) -> None:
        probe_filter = DevToolsProbeFilter()
        record = _record("NiceGUI ready to go on http://localhost:8080")
        assert probe_filter.filter(record) is True


class TestSilenceConnectionReset:
    def test_swallows_connection_reset(self) -> None:
        loop = Mock()
        silence_connection_reset(loop, {"exception": ConnectionResetError(10054, "reset")})
        loop.default_exception_handler.assert_not_called()

    def test_delegates_other_exceptions(self) -> None:
        loop = Mock()
        context = {"exception": RuntimeError("boom")}
        silence_connection_reset(loop, context)
        loop.default_exception_handler.assert_called_once_with(context)

    def test_delegates_contexts_without_exception(self) -> None:
        loop = Mock()
        context = {"message": "something went wrong"}
        silence_connection_reset(loop, context)
        loop.default_exception_handler.assert_called_once_with(context)
