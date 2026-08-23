"""Middleware enforcing at most one draft-write tool call per AI message.

The plot sub-agent's feedback loop lives inside each write tool's result: a
write runs interpretation synchronously and returns the reviewed evidence,
rank movements, and distance-to-threshold. A model that batches several writes
into one AI message is acting blind — the second write was chosen before the
first write's feedback existed. This middleware makes blind batching
impossible by construction rather than by prompt: within one AI message, only
the first tool call whose name is in the configured write set executes; every
later write call in that message is rejected with an error ``ToolMessage``
telling the model to read the first result and re-issue. Read-only calls
batched alongside a write are unaffected.

Ordering: list this middleware *after* ``SerializeToolCallsMiddleware`` (the
first middleware in the list is outermost). The serializer's per-batch gate
must observe every call so that a rejected call still takes and releases its
turn; if the rejection short-circuited outside the gate, later calls in the
batch would wait forever.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command


class SingleWritePerMessageMiddleware(AgentMiddleware):
    """Reject all but the first write tool call within one AI message."""

    def __init__(self, write_tool_names: Collection[str]) -> None:
        super().__init__()
        self._write_tool_names = frozenset(write_tool_names)

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        rejection = self._rejection(request)
        if rejection is not None:
            return rejection
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        rejection = self._rejection(request)
        if rejection is not None:
            return rejection
        return await handler(request)

    def _rejection(self, request: ToolCallRequest) -> ToolMessage | None:
        """Return an error ToolMessage for a non-first write in a batch, else None."""

        name = request.tool_call.get("name", "")
        if name not in self._write_tool_names:
            return None
        message = _emitting_message(request)
        if message is None:
            return None
        writes = [
            call for call in message.tool_calls if call.get("name") in self._write_tool_names
        ]
        if len(writes) <= 1 or request.tool_call.get("id") == writes[0].get("id"):
            return None
        batched = ", ".join(call.get("name") or "?" for call in writes)
        return ToolMessage(
            content=(
                f"Rejected {name}: only one draft-write tool call is allowed per "
                f"message, but this message batched {len(writes)} ({batched}). Only "
                f"the first ({writes[0].get('name')}) was executed. Read its result — "
                "the interpretation feedback, rank movements, and "
                "distance-to-threshold — then issue the next write in a new message."
            ),
            tool_call_id=request.tool_call.get("id") or "",
            name=name,
            status="error",
        )


def _emitting_message(request: ToolCallRequest) -> AIMessage | None:
    """Locate the AI message whose ``tool_calls`` include this request's call.

    Returns ``None`` when the emitting message cannot be found, in which case
    the call is treated as a solo batch and never rejected.
    """

    call_id = request.tool_call.get("id")
    state = request.state
    messages = (
        state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
    )
    for message in reversed(messages or []):
        if isinstance(message, AIMessage) and message.tool_calls:
            if any(call.get("id") == call_id for call in message.tool_calls):
                return message
    return None
