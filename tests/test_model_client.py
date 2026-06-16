"""Unit tests for model client construction."""

import pytest

from app.models import client
from app.models.config import ModelConfig
from app.models.settings import OPENROUTER_BASE_URL, ModelSettings


def test_get_chat_model_for_config_sets_model_temperature_and_reasoning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_chat_openai(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(client, "ChatOpenAI", fake_chat_openai)
    settings = ModelSettings(OPENROUTER_API_KEY="sk-or-v1-test")
    config = ModelConfig(
        id="custom",
        name="Custom",
        model="example/custom",
        temperature=0.3,
        reasoning_effort="medium",
    )

    result = client.get_chat_model_for_config(config, settings)

    assert result is captured
    assert captured["api_key"] == "sk-or-v1-test"
    assert captured["base_url"] == OPENROUTER_BASE_URL
    assert captured["model"] == "example/custom"
    assert captured["streaming"] is True
    assert "callbacks" in captured
    assert captured["temperature"] == 0.3
    assert captured["extra_body"] == {"reasoning": {"effort": "medium"}}


def test_get_chat_model_for_config_omits_optional_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_chat_openai(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return kwargs

    monkeypatch.setattr(client, "ChatOpenAI", fake_chat_openai)
    settings = ModelSettings(OPENROUTER_API_KEY="sk-or-v1-test")
    config = ModelConfig(id="custom", name="Custom", model="example/custom")

    client.get_chat_model_for_config(config, settings)

    assert "temperature" not in captured
    assert "extra_body" not in captured


def test_get_chat_model_for_config_can_disable_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_chat_openai(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return captured

    monkeypatch.setattr(client, "ChatOpenAI", fake_chat_openai)
    settings = ModelSettings(OPENROUTER_API_KEY="sk-or-v1-test")
    config = ModelConfig(id="custom", name="Custom", model="example/custom")

    client.get_chat_model_for_config(config, settings, streaming=False)

    assert captured["streaming"] is False
