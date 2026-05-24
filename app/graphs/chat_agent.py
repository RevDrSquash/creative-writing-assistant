"""LangGraph chat agent for the writing workspace."""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, RemoveMessage
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.graph.state import CompiledStateGraph

from app.graphs.context import ContextAssembler
from app.models import ModelSettings, get_chat_model

_CHAT_AGENT: CompiledStateGraph | None = None
_CHAT_AGENT_API_KEY: str | None = None


class ContextAssemblyMiddleware(AgentMiddleware):
    """Inject the assembled system prompt before each model call."""

    def __init__(self, assembler: ContextAssembler) -> None:
        super().__init__()
        self.assembler = assembler

    def before_model(
        self,
        state: dict[str, Any],
        runtime: Any,
    ) -> dict[str, list[BaseMessage]]:
        """Assemble model messages idempotently inside the agent loop."""

        assembled_messages = self.assembler.assemble(state["messages"])
        return {
            "messages": [
                RemoveMessage(id=REMOVE_ALL_MESSAGES),
                *assembled_messages,
            ]
        }


def build_chat_agent(
    model: BaseChatModel | None = None,
    assembler: ContextAssembler | None = None,
) -> CompiledStateGraph:
    """Build the Phase 2 compiled LangGraph chat agent."""

    assembler = assembler or ContextAssembler()
    return create_agent(
        model=model or get_chat_model(),
        tools=[],
        middleware=[ContextAssemblyMiddleware(assembler)],
    )


def get_chat_agent() -> CompiledStateGraph:
    """Return a lazily-created singleton chat agent for the UI."""

    global _CHAT_AGENT, _CHAT_AGENT_API_KEY

    settings = ModelSettings()
    if _CHAT_AGENT is None or _CHAT_AGENT_API_KEY != settings.openrouter_api_key:
        _CHAT_AGENT = build_chat_agent(model=get_chat_model(settings))
        _CHAT_AGENT_API_KEY = settings.openrouter_api_key
    return _CHAT_AGENT
