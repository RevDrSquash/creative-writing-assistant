"""Unit tests for chat UI configuration behavior."""

import pytest
from pydantic import ValidationError

from app.models.settings import ModelSettings
from app.ui.components.canvas_stream_parser import ParseEvents
from app.ui.components.chat import (
    _apply_canvas_flush_events,
    _chat_configuration_error,
    _write_scene_updates_from_payload,
)


def test_chat_configuration_error_is_none_for_valid_settings() -> None:
    error = _chat_configuration_error(lambda: ModelSettings(OPENROUTER_API_KEY="sk-or-v1-test"))

    assert error is None


def test_chat_configuration_error_reports_invalid_settings() -> None:
    def invalid_settings() -> ModelSettings:
        raise ValidationError.from_exception_data(
            "ModelSettings",
            [
                {
                    "type": "value_error",
                    "loc": ("OPENROUTER_API_KEY",),
                    "msg": 'OPENROUTER_API_KEY must start with "sk-or-v1-".',
                    "input": "bad-key",
                    "ctx": {"error": ValueError('OPENROUTER_API_KEY must start with "sk-or-v1-".')},
                }
            ],
        )

    error = _chat_configuration_error(invalid_settings)

    assert error is not None
    assert 'OPENROUTER_API_KEY must start with "sk-or-v1-".' in error


def test_chat_configuration_error_does_not_swallow_unexpected_errors() -> None:
    def broken_settings() -> ModelSettings:
        msg = "unexpected"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError, match="unexpected"):
        _chat_configuration_error(broken_settings)


def test_chat_panel_writes_current_scene_updates_to_world() -> None:
    written: list[tuple[str, str]] = []
    run_scene = {"id": "scene-1", "authoritative_text": "old text"}

    _write_scene_updates_from_payload(
        {"tools": {"current_scene": "edited scene"}},
        run_scene,
        lambda scene_id, text: written.append((scene_id, text)),
    )

    assert written == [("scene-1", "edited scene")]
    assert run_scene["authoritative_text"] == "edited scene"


def test_chat_panel_writes_middleware_scene_updates_to_world() -> None:
    written: list[tuple[str, str]] = []
    run_scene = {"id": "scene-1", "authoritative_text": "existing scene"}

    _write_scene_updates_from_payload(
        {"CanvasAppendMiddleware": {"current_scene": "existing scene\n\nnew prose"}},
        run_scene,
        lambda scene_id, text: written.append((scene_id, text)),
    )

    assert written == [("scene-1", "existing scene\n\nnew prose")]


def test_chat_panel_applies_scene_switch_before_scene_text() -> None:
    written: list[tuple[str, str]] = []
    run_scene = {"id": "scene-1", "authoritative_text": "old text"}

    _write_scene_updates_from_payload(
        {"tools": {"current_scene": "new scene text", "current_scene_id": "scene-2"}},
        run_scene,
        lambda scene_id, text: written.append((scene_id, text)),
    )

    assert run_scene["id"] == "scene-2"
    assert written == [("scene-2", "new scene text")]


def test_canvas_flush_events_roll_back_to_last_authoritative_text() -> None:
    written: list[tuple[str, str]] = []
    run_scene = {"id": "scene-1", "authoritative_text": "last committed text"}

    did_roll_back = _apply_canvas_flush_events(
        ParseEvents(unterminated_canvas=True),
        run_scene,
        lambda scene_id, text: written.append((scene_id, text)),
    )

    assert did_roll_back is True
    assert written == [("scene-1", "last committed text")]


def test_canvas_flush_events_no_rollback_when_canvas_terminated() -> None:
    written: list[tuple[str, str]] = []
    run_scene = {"id": "scene-1", "authoritative_text": "text"}

    did_roll_back = _apply_canvas_flush_events(
        ParseEvents(chat_text="trailing chat"),
        run_scene,
        lambda scene_id, text: written.append((scene_id, text)),
    )

    assert did_roll_back is False
    assert written == []
