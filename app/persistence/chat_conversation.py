"""Conversation-level facade for chat history persistence."""

from __future__ import annotations

from langchain_core.messages import BaseMessage

from app.persistence.chat_messages import (
    ChatMessageStore,
    StoredChatMessage,
    get_chat_message_store,
    stored_to_messages,
)

_CHAT_CONVERSATION: ChatConversation | None = None


class ChatConversation:
    """Manage persisted chat turns and agent-ready message history."""

    def __init__(self, store: ChatMessageStore | None = None) -> None:
        self.store = store or get_chat_message_store()

    def history(self) -> list[StoredChatMessage]:
        """Return the persisted conversation history."""

        return self.store.load()

    def add_user_message(self, text: str) -> StoredChatMessage:
        """Persist a user turn and return the stored message."""

        return self._append("user", text)

    def add_assistant_message(self, text: str) -> StoredChatMessage:
        """Persist an assistant turn and return the stored message."""

        return self._append("assistant", text)

    def agent_messages(self) -> list[BaseMessage]:
        """Return persisted history converted for LangGraph agent input."""

        return stored_to_messages(self.store.load())

    def clear(self) -> None:
        """Clear persisted conversation history."""

        self.store.clear()

    def _append(self, role: str, text: str) -> StoredChatMessage:
        # Stored history must never carry leading whitespace. NiceGUI's
        # ``ui.markdown`` treats the first non-empty line's indent as the
        # dedent amount for every line, so a stray leading space (common at
        # the start of an LLM stream) silently chews the first character off
        # every subsequent line. Normalising here means every consumer of
        # ``history()`` can trust the content.
        message: StoredChatMessage = {"role": role, "content": text.lstrip()}
        self.store.append(message)
        return message


def get_chat_conversation() -> ChatConversation:
    """Return the process-local chat conversation singleton."""

    global _CHAT_CONVERSATION

    if _CHAT_CONVERSATION is None:
        _CHAT_CONVERSATION = ChatConversation()
    return _CHAT_CONVERSATION
