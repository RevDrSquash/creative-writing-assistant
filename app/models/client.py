"""Chat model factory for the Phase 2 LangGraph agent."""

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.models.settings import DEFAULT_MODEL, OPENROUTER_BASE_URL, ModelSettings


def get_chat_model(settings: ModelSettings | None = None) -> BaseChatModel:
    """Create the hard-coded OpenRouter chat model."""

    model_settings = settings or ModelSettings()
    if not model_settings.openrouter_api_key:
        msg = "OPENROUTER_API_KEY is required to use the chat agent."
        raise RuntimeError(msg)

    return ChatOpenAI(
        api_key=model_settings.openrouter_api_key,
        base_url=OPENROUTER_BASE_URL,
        model=DEFAULT_MODEL,
        streaming=True,
    )
