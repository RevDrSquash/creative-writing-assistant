"""Unit tests for chat message persistence."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.persistence import (
    JsonFileChatMessageStore,
    messages_to_stored,
    stored_to_messages,
)


def test_load_missing_file_returns_empty_list(tmp_path) -> None:
    store = JsonFileChatMessageStore(tmp_path / "chat_history.json")

    assert store.load() == []


def test_append_then_load_round_trips_from_fresh_instance(tmp_path) -> None:
    path = tmp_path / "chat_history.json"
    store = JsonFileChatMessageStore(path)

    store.append({"role": "user", "content": "Draft a scene."})

    assert JsonFileChatMessageStore(path).load() == [
        {"role": "user", "content": "Draft a scene."}
    ]


def test_clear_empties_subsequent_load(tmp_path) -> None:
    store = JsonFileChatMessageStore(tmp_path / "chat_history.json")

    store.append({"role": "assistant", "content": "Here is a scene."})
    store.clear()

    assert store.load() == []


def test_append_leaves_no_tmp_file(tmp_path) -> None:
    path = tmp_path / "chat_history.json"
    store = JsonFileChatMessageStore(path)

    store.append({"role": "user", "content": "Hello"})

    assert not path.with_suffix(".json.tmp").exists()


def test_converter_round_trip_preserves_roles_and_content() -> None:
    stored_messages = [
        {"role": "user", "content": "Draft a scene."},
        {"role": "assistant", "content": "Here is a scene."},
    ]

    messages = stored_to_messages(stored_messages)

    assert messages_to_stored(messages) == stored_messages


def test_stored_to_messages_rejects_unknown_roles() -> None:
    with pytest.raises(ValueError, match="Unsupported stored chat message role"):
        stored_to_messages([{"role": "system", "content": "Nope"}])


def test_messages_to_stored_skips_system_messages() -> None:
    stored = messages_to_stored(
        [
            SystemMessage(content="System instructions"),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there"),
        ]
    )

    assert stored == [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]
