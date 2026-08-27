"""Named workflow registry for enforced LangGraph pipelines."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.graphs.intimacy_workflow import build_intimacy_interpreter_graph
from app.graphs.plot_agent import build_plot_agent
from app.graphs.scene_workflow import build_scene_writer_graph

WorkflowBuilder = Callable[..., CompiledStateGraph]

WORKFLOWS: dict[str, WorkflowBuilder] = {
    "generate_scene": build_scene_writer_graph,
    "interpret_intimacy": build_intimacy_interpreter_graph,
    "plan_plot": build_plot_agent,
}


def get_workflow(name: str, **kwargs: Any) -> CompiledStateGraph:
    """Build and return a named workflow graph."""

    builder = WORKFLOWS.get(name)
    if builder is None:
        msg = f"Unknown workflow: {name}"
        raise KeyError(msg)
    return builder(**kwargs)
