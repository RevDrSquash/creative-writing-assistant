"""LangChain callback handler for local LLM debug logging."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from app.persistence import LLMCallLogStore, LLMCallRecord, get_llm_call_log_store

LOGGER = logging.getLogger("app.llm_debug")
SECRET_KEY_PARTS = ("api_key", "authorization", "token", "secret")

_LLM_DEBUG_HANDLER: LLMDebugCallbackHandler | None = None


class LLMDebugCallbackHandler(BaseCallbackHandler):
    """Capture model calls into the local debug log store."""

    def __init__(self, store: LLMCallLogStore | None = None) -> None:
        super().__init__()
        self.store = store or get_llm_call_log_store()
        self._started_at: dict[str, datetime] = {}

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Persist the model invocation request."""

        run_id_text = str(run_id)
        started_at = _now()
        self._started_at[run_id_text] = started_at

        invocation_params = kwargs.get("invocation_params")
        params = _scrub_secrets(invocation_params if isinstance(invocation_params, dict) else {})
        model = _model_name(params, serialized)
        node = (metadata or {}).get("langgraph_node")
        record = LLMCallRecord(
            run_id=run_id_text,
            status="running",
            started_at=_format_time(started_at),
            node=str(node) if node else None,
            model=model,
            params=params,
            prompt=_serialize_messages(messages[0] if messages else []),
            prompt_messages=_serialize_prompt_messages(messages[0] if messages else []),
        )
        self.store.start(record)
        LOGGER.info("LLM call started run_id=%s node=%s model=%s params=%s", run_id_text, node, model, params)

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Persist a successful model response."""

        run_id_text = str(run_id)
        response_metadata = _response_metadata(response)
        self.store.finish(
            run_id_text,
            status="success",
            finished_at=_format_time(_now()),
            response_text=_response_text(response),
            response_metadata=response_metadata,
            duration_ms=self._duration_ms(run_id_text),
        )
        LOGGER.info("LLM call finished run_id=%s response_metadata=%s", run_id_text, response_metadata)

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        **kwargs: Any,
    ) -> None:
        """Persist a failed model response."""

        run_id_text = str(run_id)
        self.store.finish(
            run_id_text,
            status="error",
            finished_at=_format_time(_now()),
            error=str(error),
            duration_ms=self._duration_ms(run_id_text),
        )
        LOGGER.info("LLM call failed run_id=%s error=%s", run_id_text, error)

    def _duration_ms(self, run_id: str) -> int | None:
        started_at = self._started_at.pop(run_id, None)
        if started_at is None:
            return None
        return int((_now() - started_at).total_seconds() * 1000)


def get_llm_debug_handler() -> LLMDebugCallbackHandler:
    """Return the process-local LLM debug callback handler singleton."""

    global _LLM_DEBUG_HANDLER

    if _LLM_DEBUG_HANDLER is None:
        _LLM_DEBUG_HANDLER = LLMDebugCallbackHandler()
    return _LLM_DEBUG_HANDLER


def _serialize_messages(messages: list[BaseMessage]) -> str:
    rendered: list[str] = []
    for message in messages:
        role = _message_role(message)
        parts = [f"{role}: {_content_to_text(message.content)}"]
        tool_calls = getattr(message, "tool_calls", None) or message.additional_kwargs.get("tool_calls")
        if tool_calls:
            parts.append(f"tool_calls: {json.dumps(_jsonable(tool_calls), indent=2)}")
        rendered.append("\n".join(parts))
    return "\n\n".join(rendered)


def _serialize_prompt_messages(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    return [_serialize_prompt_message(message) for message in messages]


def _serialize_prompt_message(message: BaseMessage) -> dict[str, Any]:
    data: dict[str, Any] = {
        "role": _message_role(message),
        "content": _content_to_text(message.content),
    }
    tool_calls = _normalize_tool_calls(message)
    if tool_calls:
        data["tool_calls"] = tool_calls
    name = getattr(message, "name", None)
    if name:
        data["name"] = name
    tool_call_id = getattr(message, "tool_call_id", None)
    if tool_call_id:
        data["tool_call_id"] = tool_call_id
    return data


def _normalize_tool_calls(message: BaseMessage) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []

    parsed_calls = getattr(message, "tool_calls", None)
    if parsed_calls:
        for call in parsed_calls:
            normalized.append(
                {
                    "name": call.get("name"),
                    "args": _jsonable(call.get("args")),
                    "id": call.get("id"),
                }
            )
        return normalized

    raw_calls = getattr(message, "additional_kwargs", {}).get("tool_calls")
    if raw_calls:
        for call in raw_calls:
            function = call.get("function") or {}
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (TypeError, ValueError):
                    pass
            normalized.append(
                {
                    "name": function.get("name"),
                    "args": _jsonable(arguments),
                    "id": call.get("id"),
                }
            )
    return normalized


def _message_role(message: BaseMessage) -> str:
    role = getattr(message, "type", message.__class__.__name__)
    return {"human": "user", "ai": "assistant"}.get(role, str(role))


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(_jsonable(content), indent=2)


def _scrub_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if _is_secret_key(key) else _scrub_secrets(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [_scrub_secrets(item) for item in value]
    return _jsonable(value)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(secret_part in lowered for secret_part in SECRET_KEY_PARTS)


def _model_name(params: dict[str, Any], serialized: dict[str, Any]) -> str | None:
    for key in ("model", "model_name"):
        value = params.get(key)
        if isinstance(value, str):
            return value

    serialized_kwargs = serialized.get("kwargs")
    if isinstance(serialized_kwargs, dict):
        for key in ("model", "model_name"):
            value = serialized_kwargs.get(key)
            if isinstance(value, str):
                return value
    return None


def _response_text(response: LLMResult) -> str | None:
    generation = _first_generation(response)
    if generation is None:
        return None

    text = getattr(generation, "text", None)
    if isinstance(text, str) and text:
        return text

    message = getattr(generation, "message", None)
    content = getattr(message, "content", None)
    return _content_to_text(content) if content is not None else None


def _response_metadata(response: LLMResult) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    llm_output = getattr(response, "llm_output", None)
    if isinstance(llm_output, dict):
        metadata.update(_jsonable(llm_output))

    generation = _first_generation(response)
    message = getattr(generation, "message", None) if generation is not None else None
    message_metadata = getattr(message, "response_metadata", None)
    if isinstance(message_metadata, dict):
        metadata["message_response_metadata"] = _jsonable(message_metadata)
    usage_metadata = getattr(message, "usage_metadata", None)
    if usage_metadata is not None:
        metadata["usage_metadata"] = _jsonable(usage_metadata)
    return metadata


def _first_generation(response: LLMResult) -> Any | None:
    generations = getattr(response, "generations", None)
    if not generations or not generations[0]:
        return None
    return generations[0][0]


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _jsonable(nested_value) for key, nested_value in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(item) for item in value]
        return str(value)
    return value


def _now() -> datetime:
    return datetime.now(UTC)


def _format_time(value: datetime) -> str:
    return value.isoformat()
