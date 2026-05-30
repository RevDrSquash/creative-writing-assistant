"""Middleware for appending streamed canvas prose to agent state."""

from __future__ import annotations

import re
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

from app.graphs.state import WritingAgentState

_CANVAS_BLOCK_PATTERN = re.compile(r"<canvas>(.*?)</canvas>", re.DOTALL)


class CanvasAppendMiddleware(AgentMiddleware[WritingAgentState, None]):
    """Append well-formed ``<canvas>`` blocks to the active scene."""

    def after_model(
        self,
        state: WritingAgentState,
        runtime: Any,
    ) -> dict[str, str] | None:
        messages = state.get("messages", [])
        if not messages:
            return None

        last_message = messages[-1]
        if not isinstance(last_message, AIMessage) or not isinstance(last_message.content, str):
            return None

        blocks = _CANVAS_BLOCK_PATTERN.findall(last_message.content)
        if not blocks:
            return None

        current_scene = state.get("current_scene", "")
        for block in blocks:
            current_scene = _append_canvas_block(current_scene, block)
        return {"current_scene": current_scene}


def _append_canvas_block(current_scene: str, block: str) -> str:
    if not current_scene:
        return block
    if current_scene.endswith("\n"):
        return f"{current_scene}{block}"
    return f"{current_scene}\n\n{block}"
