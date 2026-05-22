"""Context assembly for the Phase 2 chat agent."""

from __future__ import annotations

from collections.abc import Sequence
from typing import NotRequired, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

DEFAULT_SYSTEM_PROMPT = """You are an AI writing assistant for long-form fiction and worldbuilding.
Help the writer brainstorm, draft, revise, and reason about story continuity.
Be concrete, collaborative, and preserve the writer's intent."""


class StoredChatMessage(TypedDict):
    """Serializable chat message stored in NiceGUI user storage."""

    role: str
    content: str
    name: NotRequired[str]


class ContextAssembler:
    """Build the message list sent to the chat agent."""

    def __init__(self, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> None:
        self.system_prompt = system_prompt

    def assemble(self, chat_history: Sequence[BaseMessage]) -> list[BaseMessage]:
        """Prepend the system prompt to the current chat history."""

        return [SystemMessage(content=self.system_prompt), *chat_history]

    def from_storage(self, stored_messages: Sequence[StoredChatMessage]) -> list[BaseMessage]:
        """Convert persisted UI chat messages into LangChain messages."""

        messages: list[BaseMessage] = []
        for message in stored_messages:
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

    def to_storage(self, messages: Sequence[BaseMessage]) -> list[StoredChatMessage]:
        """Convert LangChain chat messages into persisted UI chat messages."""

        stored_messages: list[StoredChatMessage] = []
        for message in messages:
            if isinstance(message, SystemMessage):
                continue
            if isinstance(message, HumanMessage):
                stored_messages.append({"role": "user", "content": self._content_to_text(message)})
            elif isinstance(message, AIMessage):
                stored_messages.append({"role": "assistant", "content": self._content_to_text(message)})
            else:
                msg = f"Unsupported chat message type: {type(message).__name__}"
                raise ValueError(msg)
        return stored_messages

    @staticmethod
    def _content_to_text(message: BaseMessage) -> str:
        content = message.content
        return content if isinstance(content, str) else str(content)
