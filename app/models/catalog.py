"""Live OpenRouter model catalog helpers."""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from app.models.settings import OPENROUTER_BASE_URL

_OPENROUTER_MODELS_CACHE: list[OpenRouterModel] | None = None


class OpenRouterModel(BaseModel):
    """Display metadata for an OpenRouter model option."""

    id: str
    name: str


def fetch_openrouter_models(
    api_key: str,
    *,
    refresh: bool = False,
    timeout: float = 10.0,
) -> list[OpenRouterModel]:
    """Fetch available OpenRouter models, returning an empty list on failure."""

    global _OPENROUTER_MODELS_CACHE

    if _OPENROUTER_MODELS_CACHE is not None and not refresh:
        return _copy_models(_OPENROUTER_MODELS_CACHE)

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    try:
        response = httpx.get(
            f"{OPENROUTER_BASE_URL}/models",
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        models = _parse_openrouter_models(response.json())
    except (httpx.HTTPError, ValueError, TypeError):
        return []

    _OPENROUTER_MODELS_CACHE = models
    return _copy_models(models)


def clear_openrouter_models_cache() -> None:
    """Clear the process-local OpenRouter model catalog cache."""

    global _OPENROUTER_MODELS_CACHE

    _OPENROUTER_MODELS_CACHE = None


def _parse_openrouter_models(payload: object) -> list[OpenRouterModel]:
    if not isinstance(payload, dict):
        return []

    raw_models = payload.get("data")
    if not isinstance(raw_models, list):
        return []

    models: list[OpenRouterModel] = []
    for raw_model in raw_models:
        if not isinstance(raw_model, dict):
            continue
        model_id = raw_model.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        name = raw_model.get("name")
        models.append(
            OpenRouterModel(
                id=model_id,
                name=name if isinstance(name, str) and name else model_id,
            )
        )
    return models


def _copy_models(models: list[OpenRouterModel]) -> list[OpenRouterModel]:
    return [model.model_copy(deep=True) for model in models]
