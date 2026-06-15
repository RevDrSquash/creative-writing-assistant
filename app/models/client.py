"""Chat model factory for the LangGraph chat agent."""

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.models.config import CHAT_NODE_ID, ModelConfig
from app.models.debug_logging import get_llm_debug_handler
from app.models.settings import OPENROUTER_BASE_URL, ModelSettings


def get_chat_model_for_node(
    node_id: str,
    settings: ModelSettings | None = None,
) -> BaseChatModel:
    """Create an OpenRouter chat model for a registered graph node."""

    from app.persistence.model_configs import get_model_config_repository

    config = get_model_config_repository().resolve_model_config(node_id)
    return get_chat_model_for_config(config, settings)


def get_chat_model(settings: ModelSettings | None = None) -> BaseChatModel:
    """Create the resolved chat-node OpenRouter model."""

    from app.persistence.model_configs import get_model_config_repository

    config = get_model_config_repository().resolve_model_config(CHAT_NODE_ID)
    return get_chat_model_for_config(config, settings)


def get_chat_model_for_config(
    config: ModelConfig,
    settings: ModelSettings | None = None,
) -> BaseChatModel:
    """Create an OpenRouter chat model from a persisted model config."""

    model_settings = settings or ModelSettings()
    if not model_settings.openrouter_api_key:
        msg = "OPENROUTER_API_KEY is required to use the chat agent."
        raise RuntimeError(msg)

    model_kwargs: dict[str, object] = {
        "api_key": model_settings.openrouter_api_key,
        "base_url": OPENROUTER_BASE_URL,
        "callbacks": [get_llm_debug_handler()],
        "model": config.model,
        "streaming": True,
    }
    if config.temperature is not None:
        model_kwargs["temperature"] = config.temperature
    if config.reasoning_effort is not None:
        model_kwargs["extra_body"] = {"reasoning": {"effort": config.reasoning_effort}}

    return ChatOpenAI(**model_kwargs)
