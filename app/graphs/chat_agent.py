"""LangGraph chat agent for the writing workspace."""

from __future__ import annotations

from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from app.graphs.context import ContextAssembler
from app.graphs.serialize_tools_middleware import SerializeToolCallsMiddleware
from app.graphs.state import WritingAgentState
from app.models import ModelConfig, ModelSettings, get_chat_model, get_chat_model_for_config
from app.models.config import CHAT_NODE_ID
from app.persistence import get_model_config_repository
from app.tools import WRITING_TOOLS

ChatAgentCacheKey = tuple[str, str, str, str, float | None, str | None, str]

_CHAT_AGENT: CompiledStateGraph | None = None
_CHAT_AGENT_CACHE_KEY: ChatAgentCacheKey | None = None


def build_chat_agent(
    model: BaseChatModel | None = None,
    assembler: ContextAssembler | None = None,
) -> CompiledStateGraph:
    """Build the Phase 2 compiled LangGraph chat agent."""

    assembler = assembler or ContextAssembler()
    return create_agent(
        model=model or get_chat_model(),
        tools=WRITING_TOOLS,
        state_schema=WritingAgentState,
        system_prompt=assembler.system_prompt,
        middleware=[
            SerializeToolCallsMiddleware(),
            _tool_failure_middleware(),
        ],
    )


def _tool_failure_middleware() -> ToolRetryMiddleware:
    """Surface tool failures to the model instead of crashing the agent run.

    Our tools are local and deterministic, so retrying the same call never
    helps; with ``max_retries=0`` a failing tool immediately produces an
    error ToolMessage and the loop continues, letting the model correct its
    arguments or report the problem.
    """

    return ToolRetryMiddleware(max_retries=0, on_failure="continue")


def get_chat_agent() -> CompiledStateGraph:
    """Return a lazily-created singleton chat agent for the UI."""

    global _CHAT_AGENT, _CHAT_AGENT_CACHE_KEY

    settings = ModelSettings()
    config = get_model_config_repository().resolve_model_config(CHAT_NODE_ID)
    cache_key = _chat_agent_cache_key(settings.openrouter_api_key, config)
    if _CHAT_AGENT is None or _CHAT_AGENT_CACHE_KEY != cache_key:
        _CHAT_AGENT = build_chat_agent(
            model=get_chat_model_for_config(config, settings),
            assembler=ContextAssembler(),
        )
        _CHAT_AGENT_CACHE_KEY = cache_key
    return _CHAT_AGENT


def _chat_agent_cache_key(api_key: str, config: ModelConfig) -> ChatAgentCacheKey:
    return (
        api_key,
        config.id,
        config.name,
        config.model,
        config.temperature,
        config.reasoning_effort,
        config.system_prompt_prefix,
    )
