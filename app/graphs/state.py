"""Custom LangGraph state for the writing agent."""

from __future__ import annotations

from langchain.agents import AgentState


class WritingAgentState(AgentState):
    """Agent state extended with the scene currently open in the workspace.

    ``current_scene`` holds the markdown text of the open scene and stays
    authoritative for scene text during a run; the UI writes state updates
    through to the ``World`` object. ``current_scene_id`` identifies which
    world scene that text belongs to.
    """

    current_scene: str
    current_scene_id: str
