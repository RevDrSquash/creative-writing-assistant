"""Unit tests for model settings validation."""

import pytest
from pydantic import ValidationError

from app.models.settings import ModelSettings


def test_model_settings_accepts_openrouter_key() -> None:
    settings = ModelSettings(OPENROUTER_API_KEY="  sk-or-v1-test  ")

    assert settings.openrouter_api_key == "sk-or-v1-test"


def test_model_settings_rejects_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="Field required"):
        ModelSettings(_env_file=None)


def test_model_settings_rejects_empty_key() -> None:
    with pytest.raises(ValidationError, match="OPENROUTER_API_KEY is required"):
        ModelSettings(OPENROUTER_API_KEY="")


def test_model_settings_rejects_non_openrouter_key() -> None:
    with pytest.raises(ValidationError, match='must start with "sk-or-v1-"'):
        ModelSettings(OPENROUTER_API_KEY="sk-proj-not-openrouter")
