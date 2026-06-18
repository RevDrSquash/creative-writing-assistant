"""Chat model factory for the LangGraph chat agent."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import Callbacks
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.outputs import LLMResult
from langchain_openai import ChatOpenAI

from app.models.config import CHAT_NODE_ID, ModelConfig
from app.models.debug_logging import get_llm_debug_handler
from app.models.settings import OPENROUTER_BASE_URL, ModelSettings


class PrefixedChatOpenAI(ChatOpenAI):
    """OpenRouter chat model that always applies a config-bound system prompt prefix."""

    system_prompt_prefix: str = ""

    def _apply_prefix(self, messages: Sequence[BaseMessage]) -> list[BaseMessage]:
        if not self.system_prompt_prefix:
            return list(messages)

        normalized = list(messages)
        for index, message in enumerate(normalized):
            if isinstance(message, SystemMessage):
                content = message.content
                if content == self.system_prompt_prefix or (
                    isinstance(content, str)
                    and content.startswith(f"{self.system_prompt_prefix}\n\n")
                ):
                    return normalized
                merged = f"{self.system_prompt_prefix}\n\n{content}".strip()
                normalized[index] = SystemMessage(content=merged)
                return normalized
        return [SystemMessage(content=self.system_prompt_prefix), *normalized]

    def _prefix_input(self, input: LanguageModelInput) -> LanguageModelInput:
        if not self.system_prompt_prefix:
            return input
        messages = self._convert_input(input).to_messages()
        return self._apply_prefix(messages)

    def generate(
        self,
        messages: list[list[BaseMessage]],
        stop: list[str] | None = None,
        callbacks: Callbacks = None,
        *,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        run_name: str | None = None,
        run_id: Any = None,
        **kwargs: Any,
    ) -> LLMResult:
        prefixed = [self._apply_prefix(message_list) for message_list in messages]
        return super().generate(
            prefixed,
            stop,
            callbacks,
            tags=tags,
            metadata=metadata,
            run_name=run_name,
            run_id=run_id,
            **kwargs,
        )

    async def agenerate(
        self,
        messages: list[list[BaseMessage]],
        stop: list[str] | None = None,
        callbacks: Callbacks = None,
        *,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        run_name: str | None = None,
        run_id: Any = None,
        **kwargs: Any,
    ) -> LLMResult:
        prefixed = [self._apply_prefix(message_list) for message_list in messages]
        return await super().agenerate(
            prefixed,
            stop,
            callbacks,
            tags=tags,
            metadata=metadata,
            run_name=run_name,
            run_id=run_id,
            **kwargs,
        )

    def stream(
        self,
        input: LanguageModelInput,
        config: Any = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> Iterator[Any]:
        yield from super().stream(self._prefix_input(input), config=config, stop=stop, **kwargs)

    async def astream(
        self,
        input: LanguageModelInput,
        config: Any = None,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        async for chunk in super().astream(
            self._prefix_input(input),
            config=config,
            stop=stop,
            **kwargs,
        ):
            yield chunk


def get_chat_model_for_node(
    node_id: str,
    settings: ModelSettings | None = None,
    *,
    streaming: bool = True,
) -> BaseChatModel:
    """Create an OpenRouter chat model for a registered graph node."""

    from app.persistence.model_configs import get_model_config_repository

    config = get_model_config_repository().resolve_model_config(node_id)
    return get_chat_model_for_config(config, settings, streaming=streaming)


def get_chat_model(settings: ModelSettings | None = None) -> BaseChatModel:
    """Create the resolved chat-node OpenRouter model."""

    from app.persistence.model_configs import get_model_config_repository

    config = get_model_config_repository().resolve_model_config(CHAT_NODE_ID)
    return get_chat_model_for_config(config, settings)


def get_chat_model_for_config(
    config: ModelConfig,
    settings: ModelSettings | None = None,
    *,
    streaming: bool = True,
) -> BaseChatModel:
    """Create an OpenRouter chat model from a persisted model config.

    Pass ``streaming=False`` for one-shot structured-output calls: streaming
    aggregation serializes the structured ``parsed`` payload and emits noisy
    Pydantic serializer warnings, while the non-streaming path excludes it.
    """

    model_settings = settings or ModelSettings()
    if not model_settings.openrouter_api_key:
        msg = "OPENROUTER_API_KEY is required to use the chat agent."
        raise RuntimeError(msg)

    model_kwargs: dict[str, object] = {
        "api_key": model_settings.openrouter_api_key,
        "base_url": OPENROUTER_BASE_URL,
        "callbacks": [get_llm_debug_handler()],
        "model": config.model,
        "streaming": streaming,
    }
    if config.temperature is not None:
        model_kwargs["temperature"] = config.temperature
    if config.reasoning_effort is not None:
        model_kwargs["extra_body"] = {"reasoning": {"effort": config.reasoning_effort}}

    return PrefixedChatOpenAI(**model_kwargs, system_prompt_prefix=config.system_prompt_prefix)
