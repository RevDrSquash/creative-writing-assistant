"""Unit tests for LLM debug callback logging."""

from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.models.debug_logging import LLMDebugCallbackHandler
from app.persistence import JsonFileLLMCallLogStore


def test_handler_creates_running_record_on_chat_model_start(tmp_path) -> None:
    store = JsonFileLLMCallLogStore(tmp_path / "llm_call_logs.json")
    handler = LLMDebugCallbackHandler(store)
    run_id = uuid4()

    handler.on_chat_model_start(
        {"kwargs": {}},
        [[HumanMessage(content="Draft a scene.")]],
        run_id=run_id,
        metadata={"langgraph_node": "chat"},
        invocation_params={
            "model": "example/model",
            "openai_api_key": "secret",
            "extra_body": {"api_key": "nested-secret"},
        },
    )

    record = store.get(str(run_id))
    assert record is not None
    assert record.status == "running"
    assert record.node == "chat"
    assert record.model == "example/model"
    assert record.params["openai_api_key"] == "[redacted]"
    assert record.params["extra_body"]["api_key"] == "[redacted]"
    assert "user: Draft a scene." in record.prompt


def test_handler_captures_structured_prompt_messages(tmp_path) -> None:
    store = JsonFileLLMCallLogStore(tmp_path / "llm_call_logs.json")
    handler = LLMDebugCallbackHandler(store)
    run_id = uuid4()
    tool_call = {
        "name": "replace_scene_text",
        "args": {"target": "old", "replacement": "new"},
        "id": "call-1",
        "type": "tool_call",
    }

    handler.on_chat_model_start(
        {"kwargs": {}},
        [
            [
                SystemMessage(content="System instructions"),
                HumanMessage(content="Revise the door line."),
                AIMessage(content="", tool_calls=[tool_call]),
                ToolMessage(content="Replaced.", tool_call_id="call-1", name="replace_scene_text"),
            ]
        ],
        run_id=run_id,
        invocation_params={"model": "example/model"},
    )

    record = store.get(str(run_id))
    assert record is not None
    roles = [message["role"] for message in record.prompt_messages]
    assert roles == ["system", "user", "assistant", "tool"]
    assistant_message = record.prompt_messages[2]
    assert assistant_message["tool_calls"][0]["name"] == "replace_scene_text"
    assert assistant_message["tool_calls"][0]["args"] == {"target": "old", "replacement": "new"}
    assert record.prompt_messages[3]["name"] == "replace_scene_text"


def test_handler_finalizes_success_on_llm_end(tmp_path) -> None:
    store = JsonFileLLMCallLogStore(tmp_path / "llm_call_logs.json")
    handler = LLMDebugCallbackHandler(store)
    run_id = uuid4()
    handler.on_chat_model_start(
        {"kwargs": {}},
        [[HumanMessage(content="Hello")]],
        run_id=run_id,
        invocation_params={"model": "example/model"},
    )

    handler.on_llm_end(
        LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="Hello writer."))]],
            llm_output={"token_usage": {"total_tokens": 12}, "model_name": "example/model"},
        ),
        run_id=run_id,
    )

    record = store.get(str(run_id))
    assert record is not None
    assert record.status == "success"
    assert record.response_text == "Hello writer."
    assert record.response_metadata["token_usage"] == {"total_tokens": 12}
    assert record.response_metadata["model_name"] == "example/model"
    assert record.duration_ms is not None


def test_handler_finalizes_error_on_llm_error(tmp_path) -> None:
    store = JsonFileLLMCallLogStore(tmp_path / "llm_call_logs.json")
    handler = LLMDebugCallbackHandler(store)
    run_id = uuid4()
    handler.on_chat_model_start(
        {"kwargs": {}},
        [[HumanMessage(content="Hello")]],
        run_id=run_id,
        invocation_params={"model": "example/model"},
    )

    handler.on_llm_error(RuntimeError("OpenRouter unavailable"), run_id=run_id)

    record = store.get(str(run_id))
    assert record is not None
    assert record.status == "error"
    assert record.error == "OpenRouter unavailable"
    assert record.duration_ms is not None
