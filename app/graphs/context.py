"""Context assembly for the chat agent."""

from __future__ import annotations

DEFAULT_SYSTEM_PROMPT = """You are an AI writing assistant for long-form fiction and worldbuilding.
Help the writer brainstorm, draft, revise, and reason about story continuity.
Be concrete, collaborative, and preserve the writer's intent."""


class ContextAssembler:
    """Build the system prompt for the chat agent."""

    def __init__(self, system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> None:
        self.system_prompt = system_prompt
