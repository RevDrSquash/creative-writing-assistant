"""Unit tests for OpenRouter catalog fetching."""

import httpx
import pytest

from app.models import catalog


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


def test_fetch_openrouter_models_parses_model_response(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog.clear_openrouter_models_cache()

    def fake_get(*args: object, **kwargs: object) -> FakeResponse:
        return FakeResponse(
            {
                "data": [
                    {"id": "openai/gpt-4o-mini", "name": "GPT-4o mini"},
                    {"id": "moonshotai/kimi-k2.6"},
                    {"name": "missing id"},
                ]
            }
        )

    monkeypatch.setattr(catalog.httpx, "get", fake_get)

    models = catalog.fetch_openrouter_models("sk-or-v1-test")

    assert [(model.id, model.name) for model in models] == [
        ("openai/gpt-4o-mini", "GPT-4o mini"),
        ("moonshotai/kimi-k2.6", "moonshotai/kimi-k2.6"),
    ]


def test_fetch_openrouter_models_uses_cache_until_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog.clear_openrouter_models_cache()
    calls = 0

    def fake_get(*args: object, **kwargs: object) -> FakeResponse:
        nonlocal calls
        calls += 1
        return FakeResponse({"data": [{"id": f"example/model-{calls}"}]})

    monkeypatch.setattr(catalog.httpx, "get", fake_get)

    first = catalog.fetch_openrouter_models("sk-or-v1-test")
    second = catalog.fetch_openrouter_models("sk-or-v1-test")
    refreshed = catalog.fetch_openrouter_models("sk-or-v1-test", refresh=True)

    assert first[0].id == "example/model-1"
    assert second[0].id == "example/model-1"
    assert refreshed[0].id == "example/model-2"


def test_fetch_openrouter_models_returns_empty_list_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog.clear_openrouter_models_cache()

    def fake_get(*args: object, **kwargs: object) -> FakeResponse:
        raise httpx.HTTPError("boom")

    monkeypatch.setattr(catalog.httpx, "get", fake_get)

    assert catalog.fetch_openrouter_models("sk-or-v1-test", refresh=True) == []
