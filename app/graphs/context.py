"""Context assembly for the chat agent."""

from __future__ import annotations

DEFAULT_SYSTEM_PROMPT = """You are an AI writing assistant for long-form fiction and worldbuilding.
Help the writer brainstorm, draft, revise, and reason about story continuity.
Be concrete, collaborative, and preserve the writer's intent.

Scene editing tools:
- Use read_scene before revising the active scene so your edits are grounded in the current text.
- Use replace_scene_text to replace one contiguous block in the active scene.
- Quote the target text as exactly as possible. If no exact match exists, the system performs a fuzzy lookup for small whitespace or punctuation drift.
- If the target is missing or ambiguous, call read_scene again and retry with more precise surrounding context.

Canvas drafting:
- Use <canvas>...</canvas> to append fresh prose to the open scene. Everything between the tags is appended verbatim to the scene markdown.
- Use canvas tags for new drafting; use replace_scene_text for surgical edits to existing prose.
- Always close canvas tags. Anything inside the tags is treated as prose, not chat.
- You may include multiple canvas blocks in one response; they append in order."""


class ContextAssembler:
    """Build the system prompt for the chat agent."""

    def __init__(
        self,
        prefix: str = "",
        base_prompt: str = DEFAULT_SYSTEM_PROMPT,
        system_prompt: str | None = None,
    ) -> None:
        self.prefix = prefix
        self.base_prompt = base_prompt
        self._system_prompt = system_prompt

    @property
    def system_prompt(self) -> str:
        """Return the composed system prompt."""

        if self._system_prompt is not None:
            return self._system_prompt
        return "\n\n".join(part.strip() for part in (self.prefix, self.base_prompt) if part.strip())
