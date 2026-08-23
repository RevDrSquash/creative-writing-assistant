"""The chat agent's single entry point for authoring timeline events.

``plan_plot`` runs the plot sub-agent (``run_plot_agent``) over a sandboxed
``PlotDraft`` of the live story bible. The briefing carries the goal and target
character arcs (shaped trajectories with waypoints, not just endpoints), a
scope (``append`` or ``revise_range``), preservation constraints (structured
pins plus free-text guidance), and a required budget that grounds bail-outs.

The run holds the coarse story-bible ``JobManager`` claim for its duration (so
it appears in the Work Queue and no second plot run can race it) and commits
the draft all-or-nothing only when the sub-agent finishes with status
``completed``. An infeasible run commits nothing and returns the structured
bail-out — reason, measured gap report, drift report — for the chat agent to
relay to the writer.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.tools import ToolException, tool

from app.tools.plot_draft import PinnedIntimacy, PlotBudget, PlotPlanResult
from app.world.draft import DraftCommitError, PlotDraft
from app.world.store import get_world

PlotScope = Literal["append", "revise_range"]


@tool
def plan_plot(
    briefing: str,
    max_new_events: int,
    max_reinterpretation_runs: int,
    scope: PlotScope = "append",
    start_event_id: str = "",
    end_event_id: str = "",
    pinned_intimacies: list[PinnedIntimacy] | None = None,
    preservation_guidance: str = "",
) -> str:
    """Delegate timeline authoring to the plot sub-agent; the only event write path.

    The sub-agent drafts events one at a time in a sandbox, runs intimacy
    interpretation after each write, watches rank movements and
    distance-to-threshold, and commits all-or-nothing on success. `briefing`
    must state the goal and each target character arc as a shaped trajectory
    with waypoints (e.g. "distrust deepens through the midpoint, then reverses
    to trust by the end"), not just an endpoint. `scope` is `append` (continue
    the timeline) or `revise_range` (rework the stretch between
    `start_event_id` and `end_event_id`; events outside it are read-only).
    `pinned_intimacies` lists intimacies that must not change - drift on them
    is measured every step. `preservation_guidance` carries free-text
    do-not-change instructions. The budget (`max_new_events`,
    `max_reinterpretation_runs`) is mandatory and grounds a budget bail-out.
    On an infeasible briefing nothing is committed and the result carries the
    reason and a measured gap report - relay it to the writer.
    """

    # Lazy imports: app.tools must stay importable without app.graphs (the
    # chat agent module imports app.tools while the graphs package initializes).
    from app.graphs.jobs import get_job_manager
    from app.graphs.plot_agent import run_plot_agent

    if not briefing.strip():
        raise ToolException("Pass a non-empty briefing (goal plus target arc shapes).")
    if max_new_events < 0 or max_reinterpretation_runs < 0:
        raise ToolException("Budget values must be zero or positive.")
    if max_new_events == 0 and max_reinterpretation_runs == 0:
        raise ToolException(
            "A zero budget cannot draft or revise anything. Pass max_new_events and/or "
            "max_reinterpretation_runs greater than zero."
        )

    revise_range: tuple[str, str] | None = None
    if scope == "revise_range":
        if not start_event_id.strip() or not end_event_id.strip():
            raise ToolException("revise_range scope requires both start_event_id and end_event_id.")
        revise_range = (start_event_id.strip(), end_event_id.strip())
    elif start_event_id.strip() or end_event_id.strip():
        raise ToolException("start_event_id/end_event_id only apply to scope='revise_range'.")

    budget = PlotBudget(
        max_new_events=max_new_events,
        max_reinterpretation_runs=max_reinterpretation_runs,
    )
    manager = get_job_manager()
    try:
        with manager.hold_story_bible_claim(label="Plot plan"):
            draft = PlotDraft(get_world().story_bible)
            try:
                result = run_plot_agent(
                    draft,
                    budget,
                    _compose_briefing(briefing, budget, revise_range, pinned_intimacies or []),
                    guidance=preservation_guidance,
                    pins=pinned_intimacies,
                    revise_range=revise_range,
                )
            except ValueError as exc:  # unknown pin or range ids
                raise ToolException(str(exc)) from exc
            committed = False
            if result.status == "completed" and draft.steps:
                try:
                    draft.commit()
                except DraftCommitError as exc:
                    raise ToolException(
                        f"The plot run finished but could not commit: {exc}"
                    ) from exc
                committed = True
    except RuntimeError as exc:  # story-bible claim already held
        raise ToolException(str(exc)) from exc

    return _format_result(result, committed=committed)


def _compose_briefing(
    briefing: str,
    budget: PlotBudget,
    revise_range: tuple[str, str] | None,
    pins: list[PinnedIntimacy],
) -> str:
    """Assemble the sub-agent's opening message from the structured briefing."""

    sections = [briefing.strip()]
    if revise_range is not None:
        sections.append(
            f"Scope: revise the timeline between events [{revise_range[0]}] and "
            f"[{revise_range[1]}] (inclusive). Events outside that range are read-only."
        )
    else:
        sections.append("Scope: append new events continuing the timeline.")
    sections.append(
        f"Budget: up to {budget.max_new_events} new events and "
        f"{budget.max_reinterpretation_runs} re-interpretation runs."
    )
    if pins:
        listing = ", ".join(f"{pin.intimacy_id} (character {pin.character_id})" for pin in pins)
        sections.append(
            f"Preservation pins (must not change; drift is measured every step): {listing}."
        )
    return "\n\n".join(sections)


def _format_result(result: PlotPlanResult, *, committed: bool) -> str:
    """Render the sub-agent's structured result for the chat agent."""

    lines: list[str] = []
    if result.status == "completed":
        lines.append("Plot run completed.")
        if committed:
            drafted = ", ".join(result.drafted_event_ids) or "(none)"
            lines.append(f"Committed to the live timeline. New events: {drafted}.")
        else:
            lines.append("The draft made no changes, so nothing was committed.")
    else:
        lines.append(f"Plot run was infeasible ({result.reason}); nothing was committed.")
    lines.append(f"Sub-agent summary: {result.summary}")
    lines.append(
        f"Budget used: {result.new_events_used}/{result.new_events_budget} new events, "
        f"{result.reinterpretation_runs_used}/{result.reinterpretation_budget} "
        "re-interpretation runs."
    )
    if result.rank_targets:
        lines.append(f"Rank targets (plan revisions: {result.rank_target_revisions}):")
        labels = {"hit": "HIT", "transient_hit": "TRANSIENT HIT", "not_yet": "NOT YET"}
        for target in result.rank_targets:
            measurement = f"net {target.effective_net:.1f}"
            if target.threshold_distance:
                measurement = f"{measurement}; {target.threshold_distance}"
            lines.append(
                f"- {labels[target.status]} {target.character_name} [{target.character_id}] "
                f"{target.intimacy_text or target.intimacy_id} [{target.intimacy_id}]: "
                f"target {target.target_rank}; current {target.current_rank} ({measurement})"
            )
    elif result.rank_targets_note:
        lines.append(f"Rank targets: none declared. Note: {result.rank_targets_note}")
    else:
        lines.append("Rank targets: no plan was declared before the run ended.")
    if result.step_summaries:
        lines.append("Steps:")
        lines.extend(f"- {summary}" for summary in result.step_summaries)
    for gap in result.gap_report:
        lines.append(
            f"Unmet arc: {gap.character_name} [{gap.character_id}] "
            f"{gap.intimacy_text or gap.intimacy_id} [{gap.intimacy_id}] is "
            f"{gap.current_rank} (net {gap.effective_net:.1f}; {gap.threshold_distance}); "
            f"target: {gap.target}" + (f"; conflict: {gap.conflict}" if gap.conflict else "")
        )
    lines.extend(result.drift_report)
    if result.stale_event_ids:
        lines.append(
            "WARNING: stale interpretations were left unrefreshed: "
            + ", ".join(result.stale_event_ids)
        )
    return "\n".join(lines)


PLOT_PLANNING_TOOLS = [plan_plot]
