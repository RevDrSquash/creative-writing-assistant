"""Persistence facade for chat message history."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import NotRequired, Protocol, TypedDict, cast

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.persistence.paths import get_data_dir

DEFAULT_CHAT_HISTORY_PATH = get_data_dir() / "chat_history.json"

_CHAT_MESSAGE_STORE: ChatMessageStore | None = None


class StoredChatMessage(TypedDict):
    """Serializable chat message persisted outside UI state."""

    role: str
    content: str
    name: NotRequired[str]


class ChatMessageStore(Protocol):
    """Minimal persistence facade for stored chat history."""

    def load(self) -> list[StoredChatMessage]:
        """Return all persisted chat messages."""

    def append(self, message: StoredChatMessage) -> None:
        """Append one persisted chat message."""

    def clear(self) -> None:
        """Clear persisted chat messages."""


class JsonFileChatMessageStore:
    """JSON-file-backed chat message store."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_CHAT_HISTORY_PATH

    def load(self) -> list[StoredChatMessage]:
        """Load stored chat messages from disk."""

        if not self.path.exists():
            return []

        raw = self.path.read_text(encoding="utf-8")
        if not raw.strip():
            return []

        data = json.loads(raw)
        if not isinstance(data, list):
            msg = f"Expected chat history JSON list at {self.path}"
            raise ValueError(msg)
        return cast(list[StoredChatMessage], data)

    def append(self, message: StoredChatMessage) -> None:
        """Append a message and write the full JSON file atomically."""

        messages = self.load()
        messages.append(message)
        self._write(messages)

    def clear(self) -> None:
        """Persist an empty chat history."""

        self._write([])

    def _write(self, messages: Sequence[StoredChatMessage]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(list(messages), indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, self.path)


def stored_to_messages(stored: Sequence[StoredChatMessage]) -> list[BaseMessage]:
    """Convert persisted chat messages into LangChain messages."""

    messages: list[BaseMessage] = []
    for message in stored:
        role = message["role"]
        content = message["content"]
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role in {"assistant", "ai"}:
            messages.append(AIMessage(content=content))
        else:
            msg = f"Unsupported stored chat message role: {role}"
            raise ValueError(msg)
    return messages


def messages_to_stored(messages: Sequence[BaseMessage]) -> list[StoredChatMessage]:
    """Convert LangChain messages into persisted chat messages."""

    stored_messages: list[StoredChatMessage] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            continue
        if isinstance(message, HumanMessage):
            stored_messages.append({"role": "user", "content": _content_to_text(message)})
        elif isinstance(message, AIMessage):
            stored_messages.append({"role": "assistant", "content": _content_to_text(message)})
        else:
            msg = f"Unsupported chat message type: {type(message).__name__}"
            raise ValueError(msg)
    return stored_messages


def get_chat_message_store() -> ChatMessageStore:
    """Return the process-local chat message store singleton."""

    global _CHAT_MESSAGE_STORE

    if _CHAT_MESSAGE_STORE is None:
        _CHAT_MESSAGE_STORE = JsonFileChatMessageStore()
    return _CHAT_MESSAGE_STORE


def _content_to_text(message: BaseMessage) -> str:
    content = message.content
    return content if isinstance(content, str) else str(content)
