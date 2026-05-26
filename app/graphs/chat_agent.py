"""LangGraph chat agent for the writing workspace."""

from __future__ import annotations

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from app.graphs.context import ContextAssembler
from app.graphs.state import WritingAgentState
from app.models import ModelSettings, get_chat_model
from app.tools import SCENE_TOOLS

_CHAT_AGENT: CompiledStateGraph | None = None
_CHAT_AGENT_API_KEY: str | None = None


def build_chat_agent(
    model: BaseChatModel | None = None,
    assembler: ContextAssembler | None = None,
) -> CompiledStateGraph:
    """Build the Phase 2 compiled LangGraph chat agent."""

    assembler = assembler or ContextAssembler()
    return create_agent(
        model=model or get_chat_model(),
        tools=SCENE_TOOLS,
        state_schema=WritingAgentState,
        system_prompt=assembler.system_prompt,
    )


def get_chat_agent() -> CompiledStateGraph:
    """Return a lazily-created singleton chat agent for the UI."""

    global _CHAT_AGENT, _CHAT_AGENT_API_KEY

    settings = ModelSettings()
    if _CHAT_AGENT is None or _CHAT_AGENT_API_KEY != settings.openrouter_api_key:
        _CHAT_AGENT = build_chat_agent(model=get_chat_model(settings))
        _CHAT_AGENT_API_KEY = settings.openrouter_api_key
    return _CHAT_AGENT
