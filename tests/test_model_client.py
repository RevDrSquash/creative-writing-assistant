"""Unit tests for model client construction and prefix injection."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any, ClassVar

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import BaseModel, Field

from app.models import client
from app.models.client import PrefixedChatOpenAI
from app.models.config import ModelConfig
from app.models.settings import OPENROUTER_BASE_URL, ModelSettings

PREFIX = "Use a noir voice."
BASE_SYSTEM = "Base instructions."


class _RecordingPrefixed(PrefixedChatOpenAI):
    recorded_messages: ClassVar[list[BaseMessage]] = []

    def _record(self, messages: list[BaseMessage]) -> None:
        _RecordingPrefixed.recorded_messages = list(messages)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._record(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self._record(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        self._record(messages)
        yield ChatGenerationChunk(message=AIMessageChunk(content="ok"))

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        self._record(messages)
        yield ChatGenerationChunk(message=AIMessageChunk(content="ok"))


class _CallbackRecordingHandler(BaseCallbackHandler):
    captured_messages: ClassVar[list[BaseMessage]] = []

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        **kwargs: Any,
    ) -> None:
        type(self).captured_messages = list(messages[0]) if messages else []


class _StructuredSchema(BaseModel):
    value: str = Field(description="A short value.")


def _recording_model(**kwargs: Any) -> _RecordingPrefixed:
    return _RecordingPrefixed(
        api_key="sk-or-v1-test",
        model="example/custom",
        system_prompt_prefix=PREFIX,
        streaming=kwargs.pop("streaming", True),
        **kwargs,
    )


def _expected_merged_system() -> str:
    return f"{PREFIX}\n\n{BASE_SYSTEM}"


def test_get_chat_model_for_config_sets_model_temperature_and_reasoning() -> None:
    settings = ModelSettings(OPENROUTER_API_KEY="sk-or-v1-test")
    config = ModelConfig(
        id="custom",
        name="Custom",
        model="example/custom",
        temperature=0.3,
        reasoning_effort="medium",
        system_prompt_prefix=PREFIX,
    )

    result = client.get_chat_model_for_config(config, settings)

    assert isinstance(result, PrefixedChatOpenAI)
    assert result.model_name == "example/custom"
    assert result.temperature == 0.3
    assert result.extra_body == {"reasoning": {"effort": "medium"}}
    assert result.system_prompt_prefix == PREFIX


def test_get_chat_model_for_config_sets_max_tokens() -> None:
    settings = ModelSettings(OPENROUTER_API_KEY="sk-or-v1-test")
    config = ModelConfig(id="custom", name="Custom", model="example/custom", max_tokens=16000)

    result = client.get_chat_model_for_config(config, settings)

    assert isinstance(result, PrefixedChatOpenAI)
    assert result.max_tokens == 16000


def test_get_chat_model_for_config_omits_optional_parameters() -> None:
    settings = ModelSettings(OPENROUTER_API_KEY="sk-or-v1-test")
    config = ModelConfig(id="custom", name="Custom", model="example/custom")

    result = client.get_chat_model_for_config(config, settings)

    assert isinstance(result, PrefixedChatOpenAI)
    assert result.model_name == "example/custom"
    assert result.temperature is None
    assert result.max_tokens is None
    assert result.extra_body is None
    assert result.system_prompt_prefix == ""


def test_get_chat_model_for_config_can_disable_streaming() -> None:
    settings = ModelSettings(OPENROUTER_API_KEY="sk-or-v1-test")
    config = ModelConfig(id="custom", name="Custom", model="example/custom")

    result = client.get_chat_model_for_config(config, settings, streaming=False)

    assert result.streaming is False


def test_get_chat_model_for_config_uses_openrouter_base_url() -> None:
    settings = ModelSettings(OPENROUTER_API_KEY="sk-or-v1-test")
    config = ModelConfig(id="custom", name="Custom", model="example/custom")

    result = client.get_chat_model_for_config(config, settings)

    assert result.openai_api_base == OPENROUTER_BASE_URL


def test_prefixed_chat_openai_merges_prefix_into_existing_system_message() -> None:
    model = PrefixedChatOpenAI(
        api_key="sk-or-v1-test",
        model="example/custom",
        system_prompt_prefix=PREFIX,
    )

    messages = model._apply_prefix([SystemMessage(content=BASE_SYSTEM), HumanMessage(content="Hi")])

    assert len(messages) == 2
    assert messages[0].content == _expected_merged_system()
    assert messages[1].content == "Hi"


def test_prefixed_chat_openai_inserts_prefix_when_no_system_message() -> None:
    model = PrefixedChatOpenAI(
        api_key="sk-or-v1-test",
        model="example/custom",
        system_prompt_prefix=PREFIX,
    )

    messages = model._apply_prefix([HumanMessage(content="Hi")])

    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == PREFIX
    assert messages[1].content == "Hi"


def test_prefixed_chat_openai_is_noop_when_prefix_empty() -> None:
    model = PrefixedChatOpenAI(api_key="sk-or-v1-test", model="example/custom")
    original = [HumanMessage(content="Hi")]

    assert model._apply_prefix(original) == original


def test_apply_prefix_is_idempotent() -> None:
    model = PrefixedChatOpenAI(
        api_key="sk-or-v1-test",
        model="example/custom",
        system_prompt_prefix=PREFIX,
    )
    original = [SystemMessage(content=BASE_SYSTEM), HumanMessage(content="Hi")]
    once = model._apply_prefix(original)
    twice = model._apply_prefix(once)

    assert once == twice
    assert once[0].content == _expected_merged_system()


def test_invoke_injects_prefix_before_generate() -> None:
    _RecordingPrefixed.recorded_messages = []
    model = _recording_model(streaming=False)

    model.invoke([SystemMessage(content=BASE_SYSTEM), HumanMessage(content="Hi")])

    recorded = _RecordingPrefixed.recorded_messages
    assert isinstance(recorded[0], SystemMessage)
    assert recorded[0].content == _expected_merged_system()
    assert recorded[1].content == "Hi"


def test_stream_injects_prefix_before_stream() -> None:
    _RecordingPrefixed.recorded_messages = []
    model = _recording_model(streaming=True)

    list(model.stream([SystemMessage(content=BASE_SYSTEM), HumanMessage(content="Hi")]))

    recorded = _RecordingPrefixed.recorded_messages
    assert isinstance(recorded[0], SystemMessage)
    assert recorded[0].content == _expected_merged_system()


@pytest.mark.asyncio
async def test_ainvoke_injects_prefix_before_agenerate() -> None:
    _RecordingPrefixed.recorded_messages = []
    model = _recording_model(streaming=False)

    await model.ainvoke([SystemMessage(content=BASE_SYSTEM), HumanMessage(content="Hi")])

    recorded = _RecordingPrefixed.recorded_messages
    assert isinstance(recorded[0], SystemMessage)
    assert recorded[0].content == _expected_merged_system()


@pytest.mark.asyncio
async def test_astream_injects_prefix_before_astream() -> None:
    _RecordingPrefixed.recorded_messages = []
    model = _recording_model(streaming=True)

    async for _chunk in model.astream(
        [SystemMessage(content=BASE_SYSTEM), HumanMessage(content="Hi")]
    ):
        pass

    recorded = _RecordingPrefixed.recorded_messages
    assert isinstance(recorded[0], SystemMessage)
    assert recorded[0].content == _expected_merged_system()


def test_structured_output_injects_prefix() -> None:
    _RecordingPrefixed.recorded_messages = []

    class StructuredRecording(_RecordingPrefixed):
        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> ChatResult:
            self._record(messages)
            message = AIMessage(
                content='{"value":"ok"}',
                additional_kwargs={"parsed": {"value": "ok"}},
            )
            return ChatResult(generations=[ChatGeneration(message=message)])

    model = StructuredRecording(
        api_key="sk-or-v1-test",
        model="example/custom",
        system_prompt_prefix=PREFIX,
        streaming=False,
    )
    result = model.with_structured_output(_StructuredSchema).invoke(
        [SystemMessage(content=BASE_SYSTEM), HumanMessage(content="Hi")]
    )

    assert result.value == "ok"
    recorded = _RecordingPrefixed.recorded_messages
    assert isinstance(recorded[0], SystemMessage)
    assert recorded[0].content == _expected_merged_system()


def test_invoke_exposes_prefix_to_on_chat_model_start() -> None:
    _CallbackRecordingHandler.captured_messages = []
    _RecordingPrefixed.recorded_messages = []
    model = _recording_model(streaming=False, callbacks=[_CallbackRecordingHandler()])

    model.invoke([SystemMessage(content=BASE_SYSTEM), HumanMessage(content="Hi")])

    captured = _CallbackRecordingHandler.captured_messages
    assert isinstance(captured[0], SystemMessage)
    assert captured[0].content == _expected_merged_system()
