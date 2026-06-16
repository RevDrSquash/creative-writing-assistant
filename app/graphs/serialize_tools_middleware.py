"""Middleware that runs batched tool calls one at a time, in emission order.

LangGraph's tool node executes the tool calls from a single AI message
concurrently: ``asyncio.gather`` in the async path and a thread pool in the
sync path. Several of our tools mutate shared, order-sensitive world state -
``add_event`` appends to the timeline and ``update_event`` inserts at a
position - so concurrent execution races on ordering. The timeline can then be
persisted in a different order than the model emitted, which breaks
event-sourced replay whenever one event references state created by an earlier
one (e.g. ``set_intimacy_strength`` for an intimacy added by a prior event).

A simple mutex is not enough: the tool node performs awaits (state injection,
etc.) before the wrap hook runs, so coroutines reach a plain lock out of order.
Instead this middleware gates each call on its index within the emitting AI
message's ``tool_calls`` list and releases them strictly in that order, for both
the sync and async execution paths.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command


def _batch_position(request: ToolCallRequest) -> tuple[Any, int, int]:
    """Return (batch_key, index, total) for this call within its AI message.

    Falls back to a solo batch when the emitting message can't be located, so a
    call never blocks waiting for siblings that will not arrive.
    """

    call_id = request.tool_call.get("id")
    state = request.state
    messages = (
        state.get("messages") if isinstance(state, dict) else getattr(state, "messages", None)
    )
    for message in reversed(messages or []):
        if isinstance(message, AIMessage) and message.tool_calls:
            ids = [call.get("id") for call in message.tool_calls]
            if call_id in ids:
                key = message.id or tuple(ids)
                return key, ids.index(call_id), len(ids)
    return (call_id, 0, 1)


class _AsyncGate:
    def __init__(self, total: int) -> None:
        self.total = total
        self.current = 0
        self.cond = asyncio.Condition()

    async def wait_turn(self, index: int) -> None:
        async with self.cond:
            await self.cond.wait_for(lambda: self.current == index)

    async def advance(self) -> None:
        async with self.cond:
            self.current += 1
            self.cond.notify_all()


class _SyncGate:
    def __init__(self, total: int) -> None:
        self.total = total
        self.current = 0
        self.cond = threading.Condition()

    def wait_turn(self, index: int) -> None:
        with self.cond:
            self.cond.wait_for(lambda: self.current == index)

    def advance(self) -> None:
        with self.cond:
            self.current += 1
            self.cond.notify_all()


class SerializeToolCallsMiddleware(AgentMiddleware):
    """Serialize a batch of tool calls so they apply in the order emitted."""

    def __init__(self) -> None:
        super().__init__()
        self._registry_lock = threading.Lock()
        self._async_gates: dict[Any, _AsyncGate] = {}
        self._sync_gates: dict[Any, _SyncGate] = {}

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        key, index, total = _batch_position(request)
        if total <= 1:
            return handler(request)
        gate = self._gate(self._sync_gates, key, total, _SyncGate)
        gate.wait_turn(index)
        try:
            return handler(request)
        finally:
            gate.advance()
            self._maybe_drop(self._sync_gates, key, gate.current)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        key, index, total = _batch_position(request)
        if total <= 1:
            return await handler(request)
        gate = self._gate(self._async_gates, key, total, _AsyncGate)
        await gate.wait_turn(index)
        try:
            return await handler(request)
        finally:
            await gate.advance()
            self._maybe_drop(self._async_gates, key, gate.current)

    def _gate(self, gates: dict[Any, Any], key: Any, total: int, factory: type) -> Any:
        with self._registry_lock:
            gate = gates.get(key)
            if gate is None:
                gate = factory(total)
                gates[key] = gate
            return gate

    def _maybe_drop(self, gates: dict[Any, Any], key: Any, current: int) -> None:
        with self._registry_lock:
            gate = gates.get(key)
            if gate is not None and current >= gate.total:
                gates.pop(key, None)
