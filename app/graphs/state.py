"""Custom LangGraph state for the writing agent."""

from __future__ import annotations

from langchain.agents import AgentState


class WritingAgentState(AgentState):
    """Agent state extended with the scene currently open in the workspace."""

    current_scene: str
