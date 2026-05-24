"""Context assembly for the Phase 2 chat agent."""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage, SystemMessage

DEFAULT_SYSTEM_PROMPT = """You are an AI writing assistant for long-form fiction and worldbuilding.
Help the writer brainstorm, draft, revise, and reason about story continuity.
Be concrete, collaborative, and preserve the writer's intent."""


class ContextAssembler:
    """Build the message list sent to the chat agent."""

    def __init__(self, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> None:
        self.system_prompt = system_prompt

    def assemble(self, chat_history: Sequence[BaseMessage]) -> list[BaseMessage]:
        """Prepend the system prompt to the current chat history."""

        non_system_messages = [
            message for message in chat_history if not isinstance(message, SystemMessage)
        ]
        return [SystemMessage(content=self.system_prompt), *non_system_messages]
