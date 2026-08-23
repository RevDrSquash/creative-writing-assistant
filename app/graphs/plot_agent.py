"""Plot sub-agent: a per-run tool loop that drafts events in a ``PlotDraft``.

``build_plot_agent`` is a ``create_agent``-style loop (like ``build_chat_agent``)
whose tools are created per run via ``create_plot_draft_toolset``, closing over
one ``PlotDraft`` and budget — so the compiled graph is per-run and never
cached. It is registered as ``plan_plot`` in the workflow registry.

``run_plot_agent`` is the blocking entry point: it builds the toolset and
graph, drives the loop with the briefing until a terminal tool (``finish_plot``
or ``bail_out``) records a structured ``PlotPlanResult``, and returns that
result. The loop cannot end without one: a run that stops talking is nudged
once to finalize, and a run that still refuses (or exhausts its step limit) is
force-bailed so the caller always receives a ``PlotPlanResult``. Committing the
draft is the caller's responsibility and only makes sense on ``completed``.

Two middleware shape the loop: ``SerializeToolCallsMiddleware`` (batched calls
apply in emission order) and ``SingleWritePerMessageMiddleware`` (at most one
draft-write tool call per AI message, so drafting blind is impossible by
construction — each write's interpretation feedback must be read before the
next write is issued).
"""

from __future__ import annotations

from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from langgraph.graph.state import CompiledStateGraph

from app.graphs.context import STORY_BIBLE_PRIMER
from app.graphs.serialize_tools_middleware import SerializeToolCallsMiddleware
from app.graphs.single_write_middleware import SingleWritePerMessageMiddleware
from app.models.client import get_chat_model_for_node
from app.models.config import PLOT_AGENT_NODE_ID
from app.tools.plot_draft import (
    DRAFT_WRITE_TOOL_NAMES,
    PlotBudget,
    PlotDraftToolset,
    PlotPlanResult,
    create_plot_draft_toolset,
)
from app.world.draft import PlotDraft

# Graph steps allowed beyond the budget-derived allowance: orientation reads,
# candidate exploration, staleness repair, and the terminal call.
_BASE_RECURSION_STEPS = 24

PLOT_AGENT_SYSTEM_PROMPT = f"""You are the plot sub-agent for a fiction-writing workspace. \
You draft timeline events inside a sandboxed copy of the story bible (a plot draft) to \
fulfill a briefing: a goal, target character arcs, constraints, and a budget. Nothing you \
do touches the live world; the caller commits the draft only if you finish successfully.

{STORY_BIBLE_PRIMER}

How to work:
- Orient first: read_draft_timeline and read_draft_state show the current draft, derived
  ranks, distance-to-threshold, and any stale interpretations.
- Draft one step at a time. Write tools (add_draft_event, insert_draft_event,
  update_draft_event, delete_draft_event, edit_draft_relations, nudge_intimacy,
  reword_signal, reword_evidence_rationale, refresh_interpretations, finish_plot,
  bail_out) are limited to one per message; batching several is rejected. Each write's
  result carries the interpretation feedback (reviewed evidence, rank movements,
  distance-to-threshold) — read it before choosing the next step.
- Use explore_candidates to compare 2-4 candidate event chains speculatively before
  committing to one. Adopt a chain (or a prefix of one) by re-issuing its events through
  the write tools, or discard all of them. It consumes no budget.
- Signals you author are hints (character_id + interpretation only); the interpretation
  workflow produces the canonical evidence. Never fabricate evidence yourself.
- nudge_intimacy is bounded editorial smoothing for when a derived rank lands one point
  short of a target threshold and a whole extra event would be contrived. Use it
  sparingly; it is capped at strength 1 and one nudge per signal per intimacy.
- Structural edits (inserts, relation rewires, mid-timeline content edits) flag
  downstream interpretations stale. Repair them with refresh_interpretations before
  finishing.
- Watch the budget line in every write result. When it runs low, converge or bail out.

Ending the run (mandatory): every run ends with exactly one terminal call —
finish_plot(summary) when the briefing's goals are met, or bail_out(reason, explanation,
gaps) when they cannot be. Bail out when the budget cannot plausibly close the measured
gap ('budget'), when closing it would contradict the briefing's arc shape or established
characterization ('judgment'), or when a preservation constraint conflicts with the
target ('overconstrained' — name the conflict). Quantify unmet arcs with the gaps
parameter so the report is measured, not vibes. Never stop responding without a
terminal call."""

_FINALIZE_NUDGE = (
    "You stopped without calling a terminal tool. Call finish_plot if the briefing's "
    "goals are met, or bail_out with a quantified gap report if they are not. "
    "This is required."
)


def build_plot_agent(
    toolset: PlotDraftToolset,
    model: BaseChatModel | None = None,
    guidance: str = "",
) -> CompiledStateGraph:
    """Build the plot sub-agent loop over one run's draft toolset.

    The tools close over a single ``PlotDraft`` and budget, so the compiled
    graph is per-run — build a fresh one for every run, never cache it.
    ``guidance`` appends the briefing's free-text preservation guidance to the
    system prompt.
    """

    system_prompt = PLOT_AGENT_SYSTEM_PROMPT
    if guidance.strip():
        system_prompt = f"{system_prompt}\n\nBriefing-specific guidance:\n{guidance.strip()}"
    return create_agent(
        model=model or get_chat_model_for_node(PLOT_AGENT_NODE_ID),
        tools=toolset.tools,
        system_prompt=system_prompt,
        middleware=[
            # Order matters: the serializer must be outermost (first) so its
            # per-batch gate still advances when the write limiter rejects a
            # call without executing it.
            SerializeToolCallsMiddleware(),
            SingleWritePerMessageMiddleware(DRAFT_WRITE_TOOL_NAMES),
            _tool_failure_middleware(),
        ],
    )


def run_plot_agent(
    draft: PlotDraft,
    budget: PlotBudget,
    briefing: str,
    *,
    model: BaseChatModel | None = None,
    models: dict[str, Any] | None = None,
    guidance: str = "",
    recursion_limit: int | None = None,
) -> PlotPlanResult:
    """Run the plot sub-agent over ``draft`` and return its structured result.

    Blocking. The draft is mutated in place; committing it is the caller's
    decision (and only sensible when the result's status is ``completed``).
    ``model`` overrides the loop model and ``models`` the interpretation
    workflow's per-node models (both used by tests). ``recursion_limit`` caps
    graph steps; the default scales with the budget. A run that ends without a
    terminal call — including by hitting the step limit — is force-bailed as
    infeasible so a ``PlotPlanResult`` is always returned.
    """

    toolset = create_plot_draft_toolset(draft, budget, models=models)
    agent = build_plot_agent(toolset, model=model, guidance=guidance)
    limit = recursion_limit or _default_recursion_limit(budget)
    config = {"recursion_limit": limit}
    try:
        state = agent.invoke({"messages": [HumanMessage(content=briefing)]}, config=config)
        if toolset.run.result is None:
            nudged = [*state["messages"], HumanMessage(content=_FINALIZE_NUDGE)]
            agent.invoke({"messages": nudged}, config=config)
    except GraphRecursionError:
        pass
    if toolset.run.result is None:
        _force_bail_out(toolset, limit)
    assert toolset.run.result is not None  # bail_out always records a result
    return toolset.run.result


def _default_recursion_limit(budget: PlotBudget) -> int:
    """Step allowance scaling with the budget.

    Each budgeted operation gets four graph steps (a model turn plus tool turn
    for the write itself and for a read or exploration around it) on top of a
    fixed base for orientation and finalization.
    """

    return _BASE_RECURSION_STEPS + 4 * (
        budget.max_new_events + budget.max_reinterpretation_runs
    )


def _force_bail_out(toolset: PlotDraftToolset, recursion_limit: int) -> None:
    """Record an infeasible result for a run that never called a terminal tool."""

    toolset.tool("bail_out").func(
        reason="budget",
        explanation=(
            "The plot run ended without calling finish_plot or bail_out "
            f"(step limit {recursion_limit}). The run is reported as infeasible; "
            "the draft is left uncommitted."
        ),
    )


def _tool_failure_middleware() -> ToolRetryMiddleware:
    """Surface tool failures to the model instead of crashing the run.

    Draft tools are local and deterministic, so retrying never helps; with
    ``max_retries=0`` a failing tool immediately produces an error ToolMessage
    and the loop continues, letting the model correct its arguments.
    """

    return ToolRetryMiddleware(max_retries=0, on_failure="continue")
