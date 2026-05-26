"""Unit tests for chat UI configuration behavior."""

import pytest
from pydantic import ValidationError

from app.models.settings import ModelSettings
from app.ui.components.chat import _chat_configuration_error, _write_scene_updates_from_payload
from app.world.scene import SCENE_CONTENT_KEY, set_current_scene_text


def test_chat_configuration_error_is_none_for_valid_settings() -> None:
    error = _chat_configuration_error(
        lambda: ModelSettings(OPENROUTER_API_KEY="sk-or-v1-test")
    )

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
                    "ctx": {
                        "error": ValueError(
                            'OPENROUTER_API_KEY must start with "sk-or-v1-".'
                        )
                    },
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


def test_chat_panel_writes_current_scene_updates_to_user_storage() -> None:
    backing_store: dict[str, str] = {}

    _write_scene_updates_from_payload(
        {"tools": {"current_scene": "edited scene"}},
        lambda text: set_current_scene_text(text, backing_store),
    )

    assert backing_store[SCENE_CONTENT_KEY] == "edited scene"
