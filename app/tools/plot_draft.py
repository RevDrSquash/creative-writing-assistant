"""Per-run agent tools over a ``PlotDraft`` sandbox.

``create_plot_draft_toolset`` builds the plot sub-agent's tools as closures
over one ``PlotDraft`` and a run budget. Write tools validate every id against
the draft (hallucinated or drifted ids are resolved or rejected with the valid
options), run intimacy interpretation for the event's signal characters
synchronously (parallel threads, awaited), apply the reviewed results to the
draft, and return the resulting evidence, rank movements, and
distance-to-threshold in the tool result — the feedback loop lives in the tool
result itself. ``explore_candidates`` gives multi-event lookahead against
throwaway copies; ``nudge_intimacy`` and the reword tools are bounded,
provenance-marked editorial smoothing; ``finish_plot`` / ``bail_out`` are the
terminal tools producing a structured ``PlotPlanResult``.

Two briefing-level constraints are enforced here rather than by prompt:

- **Preservation pins** (``pins``): specific character intimacies the run must
  not change. Every write result carries a drift report diffing each pin's
  rank and net against the original timeline, so drift is measured, not vibes.
- **Revise-range containment** (``revise_range``): events outside the range
  are read-only — write tools reject edits to them outright. Downstream
  interpretations may still refresh via the stale ripple; in revise mode the
  drift report additionally diffs the full end-state against the original.

Nothing here touches the live world: all reads and writes target the draft's
sandbox bible. Committing the draft is the caller's responsibility.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from langchain_core.tools import BaseTool, ToolException, tool
from pydantic import BaseModel, Field

from app.tools.story_bible import _signals_as_hints
from app.world.draft import PlotDraft
from app.world.evidence import RankState, format_threshold_distance
from app.world.models import (
    Event,
    EventRelationKind,
    EventRelationSpec,
    EvidenceDirection,
    IntimacyEvidence,
    Signal,
    StoryBible,
    WorldStateEffect,
)
from app.world.relations import (
    RelationValidationError,
    chronological_order,
    format_diagnostics,
    relation_diagnostics,
)
from app.world.replay import effect_diagnostics, explain_intimacies, format_effect_diagnostics

if TYPE_CHECKING:
    from app.graphs.intimacy_workflow import InterpretationResult

BailOutReason = Literal["budget", "judgment", "overconstrained"]

MAX_CANDIDATE_CHAINS = 4
MIN_CANDIDATE_CHAINS = 2
MAX_CHAIN_EVENTS = 3

# Tools that mutate the draft or end the run. The plot agent's
# one-write-per-message middleware (SingleWritePerMessageMiddleware) rejects
# batching these so every write's interpretation feedback is read before the
# next write is chosen. Read-only tools (read_draft_timeline, read_draft_state,
# explore_candidates) may batch freely.
DRAFT_WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "add_draft_event",
        "insert_draft_event",
        "update_draft_event",
        "delete_draft_event",
        "edit_draft_relations",
        "nudge_intimacy",
        "reword_signal",
        "reword_evidence_rationale",
        "refresh_interpretations",
        "finish_plot",
        "bail_out",
    }
)


class PlotBudget(BaseModel):
    """Run budget from the briefing. Exhaustion grounds a budget-based bail-out."""

    max_new_events: int = Field(ge=0)
    max_reinterpretation_runs: int = Field(ge=0)


class PinnedIntimacy(BaseModel):
    """One character intimacy the briefing pins: the run must not change it.

    Pins are mechanically checked: every write result diffs each pin's derived
    rank and net against the original timeline. Drift is a red flag the agent
    must resolve or bail out on (reason ``overconstrained``).
    """

    character_id: str
    intimacy_id: str


class DraftRelationSpec(BaseModel):
    """One relation to add between existing draft events.

    For directed kinds, ``source_id`` is the later event and ``target_id`` the
    earlier one.
    """

    kind: EventRelationKind
    source_id: str
    target_id: str


class CandidateEventSpec(BaseModel):
    """One speculative event inside a candidate chain.

    ``relations`` anchor the event to existing draft events (required for the
    first event of a chain when the timeline is not empty). Events after the
    first are automatically linked to the previous chain event with
    ``link_kind``. ``signals`` are hints: character_id and interpretation only.
    """

    title: str
    description: str = ""
    link_kind: Literal["follows", "directly_follows"] = "follows"
    relations: list[EventRelationSpec] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)


class CandidateChain(BaseModel):
    """A candidate sequence of 1-3 event specs, adopted or discarded whole.

    Every event spec requires a ``title``; ``title`` on the chain itself is an
    optional short name shown in the comparison output.
    """

    title: str = ""
    events: list[CandidateEventSpec]


class ArcGapSpec(BaseModel):
    """One target arc the run could not reach, named by the bailing agent."""

    character_id: str
    intimacy_id: str
    target: str
    conflict: str = ""


class ArcGapReport(BaseModel):
    """Measured gap between a target arc waypoint and the draft's derived state."""

    character_id: str
    character_name: str = ""
    intimacy_id: str
    intimacy_text: str = ""
    target: str = ""
    conflict: str = ""
    current_rank: str = ""
    effective_net: float = 0.0
    threshold_distance: str = ""


class PlotPlanResult(BaseModel):
    """Structured outcome of a plot run, produced by finish_plot or bail_out."""

    status: Literal["completed", "infeasible"]
    reason: str = ""
    summary: str = ""
    drafted_event_ids: list[str] = Field(default_factory=list)
    step_summaries: list[str] = Field(default_factory=list)
    stale_event_ids: list[str] = Field(default_factory=list)
    new_events_used: int = 0
    new_events_budget: int = 0
    reinterpretation_runs_used: int = 0
    reinterpretation_budget: int = 0
    gap_report: list[ArcGapReport] = Field(default_factory=list)
    drift_report: list[str] = Field(default_factory=list)


@dataclass
class PlotDraftRun:
    """Mutable state shared by one run's tools: draft, budget, and outcome."""

    draft: PlotDraft
    budget: PlotBudget
    models: dict[str, Any] | None = None
    pins: list[PinnedIntimacy] = field(default_factory=list)
    protected_event_ids: frozenset[str] = frozenset()
    revise_active: bool = False
    new_events_used: int = 0
    reinterpretation_runs_used: int = 0
    result: PlotPlanResult | None = None


@dataclass
class PlotDraftToolset:
    """The per-run tools plus the shared run state the agent loop inspects."""

    run: PlotDraftRun
    tools: list[BaseTool] = field(default_factory=list)

    def tool(self, name: str) -> BaseTool:
        match = next((item for item in self.tools if item.name == name), None)
        if match is None:
            msg = f"No plot draft tool named {name}"
            raise KeyError(msg)
        return match


# ---------------------------------------------------------------- helpers


def _event_listing(bible: StoryBible) -> str:
    if not bible.timeline:
        return "No events exist yet."
    listing = ", ".join(f"{event.title or 'Untitled'} [{event.id}]" for event in bible.timeline)
    return f"Valid events: {listing}"


def _character_listing(bible: StoryBible) -> str:
    if not bible.characters:
        return "No characters exist yet."
    listing = ", ".join(
        f"{character.identity.name or 'Unnamed'} [{character.id}]" for character in bible.characters
    )
    return f"Valid characters: {listing}"


def _intimacy_listing(bible: StoryBible, character_id: str) -> str:
    catalog = bible.intimacy_catalog(character_id)
    if not catalog:
        return "This character has no intimacies yet."
    listing = ", ".join(f"{text or intimacy_id} [{intimacy_id}]" for intimacy_id, text in catalog)
    return f"Valid intimacies: {listing}"


def _resolve_event_id(bible: StoryBible, event_id: str) -> str:
    resolved = bible.resolve_event_id(event_id)
    if resolved is None:
        raise ToolException(f"No event with id {event_id}. {_event_listing(bible)}")
    return resolved


def _resolve_character_id(bible: StoryBible, character_id: str) -> str:
    resolved = bible.resolve_character_id(character_id)
    if resolved is None:
        raise ToolException(f"No character with id {character_id}. {_character_listing(bible)}")
    return resolved


def _resolve_intimacy_id(bible: StoryBible, character_id: str, intimacy_id: str) -> str:
    resolved = bible.resolve_intimacy_id(intimacy_id, character_id=character_id)
    if resolved is None:
        raise ToolException(
            f"No intimacy with id {intimacy_id} for character {character_id}. "
            f"{_intimacy_listing(bible, character_id)}"
        )
    return resolved


def _resolve_relation_specs(
    bible: StoryBible,
    specs: list[EventRelationSpec],
) -> list[EventRelationSpec]:
    return [
        EventRelationSpec(kind=spec.kind, event_id=_resolve_event_id(bible, spec.event_id))
        for spec in specs
    ]


def _signal_character_ids(bible: StoryBible, event: Event) -> list[str]:
    ordered: list[str] = []
    for signal in event.signals:
        character_id = signal.character_id
        if not character_id or character_id in ordered:
            continue
        if bible.get_character(character_id) is None:
            continue
        ordered.append(character_id)
    return ordered


def _hint_character_ids(bible: StoryBible, signals: list[Signal]) -> list[str]:
    ordered: list[str] = []
    for signal in signals:
        character_id = signal.character_id
        if character_id and character_id not in ordered and bible.get_character(character_id):
            ordered.append(character_id)
    return ordered


def _ranks_for(bible: StoryBible, character_ids: list[str]) -> dict[str, dict[str, RankState]]:
    ranks: dict[str, dict[str, RankState]] = {}
    for character_id in character_ids:
        try:
            ranks[character_id] = explain_intimacies(bible, character_id)
        except ValueError:
            ranks[character_id] = {}
    return ranks


def _run_interpretations(
    bible: StoryBible,
    event_id: str,
    character_ids: list[str],
    models: dict[str, Any] | None,
) -> tuple[dict[str, InterpretationResult], dict[str, str]]:
    """Interpret one event for several characters in parallel threads, awaited."""

    # Lazy import: app.tools must stay importable without app.graphs (the chat
    # agent module imports app.tools while the graphs package initializes).
    from app.graphs.intimacy_workflow import run_intimacy_interpretation

    results: dict[str, InterpretationResult] = {}
    errors: dict[str, str] = {}
    if not character_ids:
        return results, errors
    with ThreadPoolExecutor(max_workers=len(character_ids)) as pool:
        futures = {
            character_id: pool.submit(
                run_intimacy_interpretation,
                event_id,
                character_id,
                models=models,
                bible=bible,
            )
            for character_id in character_ids
        }
    for character_id, future in futures.items():
        try:
            results[character_id] = future.result()
        except Exception as exc:  # reported per character in the tool result
            errors[character_id] = str(exc)
    return results, errors


def _interpret_and_apply(
    draft: PlotDraft,
    event: Event,
    models: dict[str, Any] | None,
) -> tuple[dict[str, InterpretationResult], dict[str, str]]:
    """Run inline interpretation for an event's signal characters and apply results."""

    from app.graphs.intimacy_interpretation import apply_interpretation_to_bible

    character_ids = _signal_character_ids(draft.bible, event)
    results, errors = _run_interpretations(draft.bible, event.id, character_ids, models)
    for result in results.values():
        apply_interpretation_to_bible(draft.bible, result)
    if character_ids and not errors:
        draft.mark_interpreted(event.id)
    if results:
        noun = "character" if len(results) == 1 else "characters"
        draft.record_semantic_edit(
            f"Applied interpretation for {len(results)} {noun} on [{event.id}]",
            (event.id,),
        )
    return results, errors


def _character_name(bible: StoryBible, character_id: str) -> str:
    character = bible.get_character(character_id)
    if character is None:
        return character_id
    return character.identity.name or "Unnamed"


def _rank_movement_lines(
    bible: StoryBible,
    character_id: str,
    before: dict[str, RankState],
    focus_ids: list[str],
) -> list[str]:
    after = _ranks_for(bible, [character_id]).get(character_id, {})
    catalog = dict(bible.intimacy_catalog(character_id))
    lines: list[str] = []
    seen: set[str] = set()
    for intimacy_id in focus_ids:
        if intimacy_id in seen:
            continue
        seen.add(intimacy_id)
        state = after.get(intimacy_id)
        if state is None:
            continue
        prior = before.get(intimacy_id)
        previous_rank = prior.rank if prior is not None else "new"
        movement = (
            f"{state.rank} (unchanged)"
            if previous_rank == state.rank
            else f"{previous_rank} -> {state.rank}"
        )
        text = catalog.get(intimacy_id, intimacy_id)
        lines.append(
            f"  - {text} [{intimacy_id}]: {movement}; net {state.effective_net:.1f}; "
            f"{format_threshold_distance(state)}"
        )
    return lines


def _interpretation_report(
    bible: StoryBible,
    results: dict[str, InterpretationResult],
    errors: dict[str, str],
    ranks_before: dict[str, dict[str, RankState]],
) -> list[str]:
    if not results and not errors:
        return ["No signal characters on this event; nothing was interpreted."]
    lines: list[str] = []
    for character_id in [*results, *errors]:
        name = _character_name(bible, character_id)
        if character_id in errors:
            lines.append(
                f"- {name} [{character_id}]: interpretation FAILED: {errors[character_id]}"
            )
            continue
        result = results[character_id]
        decision = result.review.decision or "approved"
        lines.append(
            f"- {name} [{character_id}] ({decision}): {result.interpretation or '(no signal)'}"
        )
        if decision == "rejected":
            lines.append(f"  - rejected: {result.review.notes or '-'} (contributes nothing)")
            continue
        for entry in result.evidence:
            lines.append(
                f"  - {entry.direction} {entry.intimacy_id} "
                f"(strength {entry.strength}, {entry.novelty}): {entry.rationale or '-'}"
            )
        focus = [entry.intimacy_id for entry in result.evidence]
        focus.extend(item.id for item in result.new_intimacies)
        lines.extend(
            _rank_movement_lines(bible, character_id, ranks_before.get(character_id, {}), focus)
        )
    return lines


def _stale_note(draft: PlotDraft, stale_added: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    if stale_added:
        lines.append(
            "Stale downstream interpretations (run refresh_interpretations): "
            + ", ".join(stale_added)
        )
    remaining = sorted(draft.stale_event_ids)
    if remaining and set(remaining) != set(stale_added):
        lines.append("All currently stale events: " + ", ".join(remaining))
    return lines


def _evidence_summary(signal_evidence: list[IntimacyEvidence]) -> list[str]:
    return [
        f"{entry.direction} {entry.intimacy_id} (strength {entry.strength}, {entry.novelty})"
        for entry in signal_evidence
        if entry.author == "interpretation"
    ]


_DRIFT_EPSILON = 0.05


def _pin_state(bible: StoryBible, pin: PinnedIntimacy) -> RankState | None:
    ranks = _ranks_for(bible, [pin.character_id]).get(pin.character_id, {})
    return ranks.get(pin.intimacy_id)


def _pin_drift_lines(run: PlotDraftRun) -> list[str]:
    draft = run.draft
    entries: list[str] = []
    drifted = False
    for pin in run.pins:
        name = _character_name(draft.base, pin.character_id)
        catalog = dict(draft.base.intimacy_catalog(pin.character_id))
        text = catalog.get(pin.intimacy_id, pin.intimacy_id)
        base_state = _pin_state(draft.base, pin)
        base_rank = base_state.rank if base_state is not None else "unknown"
        base_net = base_state.effective_net if base_state is not None else 0.0
        draft_state = _pin_state(draft.bible, pin)
        if draft_state is None:
            drifted = True
            entries.append(
                f"  - DRIFT {name}: '{text}' [{pin.intimacy_id}] is no longer present "
                f"(was {base_rank}, net {base_net:.1f})"
            )
            continue
        if draft_state.rank != base_rank:
            drifted = True
            marker = "DRIFT"
        elif abs(draft_state.effective_net - base_net) >= _DRIFT_EPSILON:
            marker = "net shifted"
        else:
            marker = "stable"
        entries.append(
            f"  - {marker} {name}: '{text}' [{pin.intimacy_id}]: {base_rank} "
            f"(net {base_net:.1f}) -> {draft_state.rank} (net {draft_state.effective_net:.1f})"
        )
    header = "Preservation pins (vs original timeline):"
    if drifted:
        header = (
            "Preservation pins (vs original timeline) - PIN DRIFT: undo the drift "
            "or bail_out (overconstrained):"
        )
    return [header, *entries]


def _end_state_drift_lines(draft: PlotDraft) -> list[str]:
    """Diff the draft's final derived ranks against the original timeline's."""

    changes: list[str] = []
    for character in draft.bible.characters:
        character_id = character.id
        base_ranks = _ranks_for(draft.base, [character_id]).get(character_id, {})
        draft_ranks = _ranks_for(draft.bible, [character_id]).get(character_id, {})
        catalog = dict(draft.bible.intimacy_catalog(character_id))
        name = _character_name(draft.bible, character_id)
        for intimacy_id, state in draft_ranks.items():
            base = base_ranks.get(intimacy_id)
            text = catalog.get(intimacy_id, intimacy_id)
            if base is None:
                changes.append(
                    f"  - {name}: NEW intimacy '{text}' [{intimacy_id}] at {state.rank} "
                    f"(net {state.effective_net:.1f})"
                )
            elif base.rank != state.rank:
                changes.append(f"  - {name}: '{text}' [{intimacy_id}]: {base.rank} -> {state.rank}")
        for intimacy_id, base in base_ranks.items():
            if intimacy_id not in draft_ranks:
                changes.append(f"  - {name}: intimacy [{intimacy_id}] removed (was {base.rank})")
    if not changes:
        return ["End-state drift vs original timeline: none (all ranks unchanged)."]
    return ["End-state drift vs original timeline:", *changes]


def _drift_note(run: PlotDraftRun) -> list[str]:
    """Drift report lines for write results; empty when no pins and not revising."""

    lines: list[str] = []
    if run.pins:
        lines.extend(_pin_drift_lines(run))
    if run.revise_active:
        lines.extend(_end_state_drift_lines(run.draft))
    return lines


def _editable_listing(run: PlotDraftRun, bible: StoryBible) -> str:
    editable = [
        f"{event.title or 'Untitled'} [{event.id}]"
        for event in bible.timeline
        if event.id not in run.protected_event_ids
    ]
    return f"Editable events: {', '.join(editable) or '(none)'}"


def _require_editable(run: PlotDraftRun, event_id: str) -> None:
    if event_id in run.protected_event_ids:
        raise ToolException(
            f"Event {event_id} is outside this run's revise range and is read-only. "
            f"{_editable_listing(run, run.draft.bible)}"
        )


def _require_anchor_in_range(
    run: PlotDraftRun,
    specs: list[EventRelationSpec],
    *,
    context: str = "",
) -> None:
    """In revise mode, new events must anchor to at least one in-range event."""

    if not run.revise_active or not specs:
        return
    if all(spec.event_id in run.protected_event_ids for spec in specs):
        prefix = f"{context}: " if context else ""
        raise ToolException(
            f"{prefix}in revise mode a new event must link to at least one event inside "
            f"the revise range. {_editable_listing(run, run.draft.bible)}"
        )


def _build_result(
    run: PlotDraftRun,
    *,
    status: Literal["completed", "infeasible"],
    summary: str,
    reason: str = "",
    gap_report: list[ArcGapReport] | None = None,
) -> PlotPlanResult:
    draft = run.draft
    drafted = [
        step.event_ids[0]
        for step in draft.steps
        if step.action in ("add_event", "insert_between")
        and step.event_ids
        and draft.bible.get_event(step.event_ids[0]) is not None
    ]
    return PlotPlanResult(
        status=status,
        reason=reason,
        summary=summary,
        drafted_event_ids=drafted,
        step_summaries=[step.summary for step in draft.steps],
        stale_event_ids=sorted(draft.stale_event_ids),
        new_events_used=run.new_events_used,
        new_events_budget=run.budget.max_new_events,
        reinterpretation_runs_used=run.reinterpretation_runs_used,
        reinterpretation_budget=run.budget.max_reinterpretation_runs,
        gap_report=gap_report or [],
        drift_report=_drift_note(run),
    )


def _require_active(run: PlotDraftRun) -> None:
    if run.result is not None:
        raise ToolException(
            "This plot run already produced a result (finish_plot or bail_out was called); "
            "no further draft actions are allowed."
        )


def _require_new_event_budget(run: PlotDraftRun) -> None:
    if run.new_events_used >= run.budget.max_new_events:
        raise ToolException(
            f"New-event budget exhausted ({run.new_events_used} of "
            f"{run.budget.max_new_events} used). Call finish_plot if the goal is met, "
            "or bail_out with reason 'budget' and a gap report if it is not."
        )


def _require_reinterpretation_budget(run: PlotDraftRun) -> None:
    if run.reinterpretation_runs_used >= run.budget.max_reinterpretation_runs:
        raise ToolException(
            f"Re-interpretation budget exhausted ({run.reinterpretation_runs_used} of "
            f"{run.budget.max_reinterpretation_runs} used). Call finish_plot if the goal "
            "is met, or bail_out with reason 'budget' and a gap report if it is not."
        )


def _budget_line(run: PlotDraftRun) -> str:
    return (
        f"Budget: {run.new_events_used}/{run.budget.max_new_events} new events, "
        f"{run.reinterpretation_runs_used}/{run.budget.max_reinterpretation_runs} "
        "re-interpretation runs used."
    )


# ------------------------------------------------------------------ factory


def _resolve_pins(bible: StoryBible, pins: list[PinnedIntimacy]) -> list[PinnedIntimacy]:
    """Resolve pin references against the bible; unknown ids raise ValueError."""

    resolved: list[PinnedIntimacy] = []
    for pin in pins:
        character_id = bible.resolve_character_id(pin.character_id)
        if character_id is None:
            raise ValueError(
                f"Unknown character_id '{pin.character_id}' in pinned intimacy. "
                f"{_character_listing(bible)}"
            )
        intimacy_id = bible.resolve_intimacy_id(pin.intimacy_id, character_id=character_id)
        if intimacy_id is None:
            raise ValueError(
                f"Unknown intimacy_id '{pin.intimacy_id}' for character {character_id} "
                f"in pinned intimacy. {_intimacy_listing(bible, character_id)}"
            )
        resolved.append(PinnedIntimacy(character_id=character_id, intimacy_id=intimacy_id))
    return resolved


def _protected_ids(bible: StoryBible, revise_range: tuple[str, str]) -> frozenset[str]:
    """Base-timeline events outside ``revise_range`` in chronological order."""

    order = [event.id for event in chronological_order(bible)]
    resolved: list[str] = []
    for raw in revise_range:
        event_id = bible.resolve_event_id(raw)
        if event_id is None:
            raise ValueError(f"Unknown event id '{raw}' in revise_range. {_event_listing(bible)}")
        resolved.append(event_id)
    start_pos = order.index(resolved[0])
    end_pos = order.index(resolved[1])
    if start_pos > end_pos:
        start_pos, end_pos = end_pos, start_pos
    return frozenset(order) - frozenset(order[start_pos : end_pos + 1])


def create_plot_draft_toolset(
    draft: PlotDraft,
    budget: PlotBudget,
    *,
    models: dict[str, Any] | None = None,
    pins: list[PinnedIntimacy] | None = None,
    revise_range: tuple[str, str] | None = None,
) -> PlotDraftToolset:
    """Build the plot sub-agent's tools as closures over one draft and budget.

    ``models`` overrides the interpretation workflow's per-node models (used by
    tests; production resolves per-node model configs). ``pins`` are briefing
    preservation constraints diffed in every write result. ``revise_range`` is
    a (start, end) pair of base-timeline event ids; events outside it become
    read-only and write results include an end-state drift report. Unknown pin
    or range ids raise ``ValueError``.
    """

    run = PlotDraftRun(
        draft=draft,
        budget=budget,
        models=models,
        pins=_resolve_pins(draft.base, pins or []),
        protected_event_ids=(
            _protected_ids(draft.base, revise_range) if revise_range is not None else frozenset()
        ),
        revise_active=revise_range is not None,
    )

    @tool
    def add_draft_event(
        title: str,
        description: str = "",
        relations: list[EventRelationSpec] | None = None,
        world_state_effects: list[WorldStateEffect] | None = None,
        signals: list[Signal] | None = None,
    ) -> str:
        """Add an event to the draft timeline and interpret it immediately.

        When other events exist, `relations` is required: each entry links the
        new event to an existing draft event (for directed kinds the new event
        is the later source and `event_id` the earlier target). `signals` are
        hints: pass `character_id` and `interpretation` only. Interpretation
        runs synchronously for every signal character; the result below shows
        the reviewed evidence, rank movements, and distance-to-threshold, so
        read it before drafting the next event. Consumes one new-event budget
        slot.
        """

        _require_active(run)
        _require_new_event_budget(run)
        hints = _signals_as_hints(signals or [])
        ranks_before = _ranks_for(draft.bible, _hint_character_ids(draft.bible, hints))
        resolved = _resolve_relation_specs(draft.bible, relations or [])
        _require_anchor_in_range(run, resolved)
        try:
            event = draft.add_event(
                title,
                description=description,
                relations=resolved,
                world_state_effects=world_state_effects,
                signals=hints,
            )
        except (RelationValidationError, ValueError) as exc:
            raise ToolException(str(exc)) from exc
        run.new_events_used += 1

        results, errors = _interpret_and_apply(draft, event, run.models)
        lines = [f"Added draft event '{event.title or 'Untitled'}' (id: {event.id})."]
        lines.append(_budget_line(run))
        lines.extend(_interpretation_report(draft.bible, results, errors, ranks_before))
        lines.extend(_stale_note(draft, ()))
        lines.extend(_drift_note(run))
        return "\n".join(lines)

    @tool
    def insert_draft_event(
        title: str,
        earlier_event_id: str,
        later_event_id: str,
        description: str = "",
        world_state_effects: list[WorldStateEffect] | None = None,
        signals: list[Signal] | None = None,
    ) -> str:
        """Insert a new event between two directly linked draft events.

        The anchors must be adjacent: the later event must follow the earlier
        one via a follows/directly_follows relation. That edge is atomically
        replaced by two edges of the same kind through the new event, so the
        chain can never be half-rewired. `signals` are hints (character_id +
        interpretation). Interpretation runs synchronously as in
        add_draft_event; the result also lists downstream events whose
        interpretations went stale (repair with refresh_interpretations).
        Consumes one new-event budget slot.
        """

        _require_active(run)
        _require_new_event_budget(run)
        hints = _signals_as_hints(signals or [])
        ranks_before = _ranks_for(draft.bible, _hint_character_ids(draft.bible, hints))
        earlier = _resolve_event_id(draft.bible, earlier_event_id)
        later = _resolve_event_id(draft.bible, later_event_id)
        if (
            run.revise_active
            and earlier in run.protected_event_ids
            and later in run.protected_event_ids
        ):
            raise ToolException(
                "Both anchors are outside this run's revise range; insertions must touch "
                f"the range. {_editable_listing(run, draft.bible)}"
            )
        try:
            event = draft.insert_event_between(
                title,
                earlier_event_id=earlier,
                later_event_id=later,
                description=description,
                world_state_effects=world_state_effects,
                signals=hints,
            )
        except (RelationValidationError, ValueError) as exc:
            raise ToolException(str(exc)) from exc
        run.new_events_used += 1
        stale_added = draft.steps[-1].stale_added

        results, errors = _interpret_and_apply(draft, event, run.models)
        lines = [
            f"Inserted draft event '{event.title or 'Untitled'}' (id: {event.id}) "
            f"between [{earlier}] and [{later}]."
        ]
        lines.append(_budget_line(run))
        lines.extend(_interpretation_report(draft.bible, results, errors, ranks_before))
        lines.extend(_stale_note(draft, stale_added))
        lines.extend(_drift_note(run))
        return "\n".join(lines)

    @tool
    def update_draft_event(
        event_id: str,
        title: str | None = None,
        description: str | None = None,
        world_state_effects: list[WorldStateEffect] | None = None,
        signals: list[Signal] | None = None,
    ) -> str:
        """Partially update a draft event and re-interpret it immediately.

        Only provided fields change. `signals` replaces the whole list and
        entries are hints (character_id + interpretation); prior evidence for
        the same character is preserved until the inline re-interpretation
        replaces it. Re-interpretation runs synchronously for every signal
        character and consumes one re-interpretation budget slot; the result
        shows evidence, rank movements, distance-to-threshold, and any newly
        stale downstream events.
        """

        _require_active(run)
        resolved_id = _resolve_event_id(draft.bible, event_id)
        _require_editable(run, resolved_id)
        event = draft.bible.get_event(resolved_id)
        hints = _signals_as_hints(signals, existing=event.signals) if signals is not None else None
        prospective = hints if hints is not None else event.signals
        character_ids = _hint_character_ids(draft.bible, list(prospective))
        if character_ids:
            _require_reinterpretation_budget(run)
        ranks_before = _ranks_for(draft.bible, character_ids)
        try:
            event = draft.update_event(
                resolved_id,
                title=title,
                description=description,
                world_state_effects=world_state_effects,
                signals=hints,
            )
        except ValueError as exc:
            raise ToolException(str(exc)) from exc
        stale_added = draft.steps[-1].stale_added
        if character_ids:
            run.reinterpretation_runs_used += 1

        results, errors = _interpret_and_apply(draft, event, run.models)
        lines = [f"Updated draft event '{event.title or 'Untitled'}' (id: {event.id})."]
        lines.append(_budget_line(run))
        lines.extend(_interpretation_report(draft.bible, results, errors, ranks_before))
        lines.extend(_stale_note(draft, stale_added))
        lines.extend(_drift_note(run))
        return "\n".join(lines)

    @tool
    def delete_draft_event(event_id: str) -> str:
        """Delete a draft event and every relation touching it.

        Downstream events whose interpretations went stale are listed; repair
        them with refresh_interpretations.
        """

        _require_active(run)
        resolved_id = _resolve_event_id(draft.bible, event_id)
        _require_editable(run, resolved_id)
        try:
            event = draft.delete_event(resolved_id)
        except ValueError as exc:
            raise ToolException(str(exc)) from exc
        stale_added = draft.steps[-1].stale_added
        lines = [f"Deleted draft event '{event.title or 'Untitled'}' (id: {resolved_id})."]
        lines.extend(_stale_note(draft, stale_added))
        lines.extend(_drift_note(run))
        return "\n".join(lines)

    @tool
    def edit_draft_relations(
        add: list[DraftRelationSpec] | None = None,
        remove_relation_ids: list[str] | None = None,
    ) -> str:
        """Add and/or remove typed relations between draft events, batched.

        Removals apply before additions, so an edge can be rewired in one
        call. For directed kinds `source_id` is the later event and
        `target_id` the earlier one. Each operation reports success or an
        error independently; failed operations do not undo earlier ones.
        Relation edits do not re-run interpretation, but reordered events are
        flagged stale — repair with refresh_interpretations.
        """

        _require_active(run)
        if not add and not remove_relation_ids:
            raise ToolException("Pass at least one relation to add or remove.")
        report: list[str] = []
        stale: list[str] = []
        for relation_id in remove_relation_ids or []:
            existing = draft.bible.get_event_relation(relation_id)
            if existing is not None and (
                existing.source_id in run.protected_event_ids
                or existing.target_id in run.protected_event_ids
            ):
                report.append(
                    f"- remove {relation_id}: ERROR: this relation touches an event outside "
                    "the revise range and is read-only."
                )
                continue
            try:
                removed = draft.remove_relation(relation_id)
            except ValueError as exc:
                report.append(f"- remove {relation_id}: ERROR: {exc}")
                continue
            stale.extend(draft.steps[-1].stale_added)
            report.append(
                f"- remove {relation_id}: OK ({removed.kind} "
                f"[{removed.source_id} -> {removed.target_id}])"
            )
        for spec in add or []:
            try:
                source = _resolve_event_id(draft.bible, spec.source_id)
                target = _resolve_event_id(draft.bible, spec.target_id)
                if source in run.protected_event_ids or target in run.protected_event_ids:
                    raise ToolException(
                        "relations may not touch events outside the revise range "
                        "(they are read-only)."
                    )
                relation = draft.add_relation(spec.kind, source, target)
            except (RelationValidationError, ValueError, ToolException) as exc:
                report.append(
                    f"- add {spec.kind} [{spec.source_id} -> {spec.target_id}]: ERROR: {exc}"
                )
                continue
            stale.extend(draft.steps[-1].stale_added)
            report.append(
                f"- add {spec.kind} [{relation.source_id} -> {relation.target_id}]: OK "
                f"(relation id: {relation.id})"
            )
        lines = ["Relation edits:", *report]
        lines.extend(_stale_note(draft, tuple(dict.fromkeys(stale))))
        lines.extend(_drift_note(run))
        return "\n".join(lines)

    @tool
    def explore_candidates(chains: list[CandidateChain]) -> str:
        """Compare 2-4 candidate event chains speculatively, without drafting.

        Each chain is 1-3 event specs; give the chain a short `title` and give
        every event spec its own `title` (required, like add_draft_event) plus
        `description` and `signals`. The first event of a chain must anchor
        to existing draft events via `relations`; later events are linked to
        the previous chain event with `link_kind` automatically. Every chain
        is interpreted against a throwaway copy of the draft in parallel; the
        comparison shows per-event evidence and the rank trajectory plus final
        distance-to-threshold per touched intimacy. Nothing is written and no
        budget is consumed: adopt one chain (or a prefix) by re-issuing its
        events through add_draft_event / insert_draft_event, or discard all.
        """

        _require_active(run)
        if not MIN_CANDIDATE_CHAINS <= len(chains) <= MAX_CANDIDATE_CHAINS:
            raise ToolException(
                f"Pass between {MIN_CANDIDATE_CHAINS} and {MAX_CANDIDATE_CHAINS} chains "
                f"(got {len(chains)})."
            )

        prepared: list[tuple[PlotDraft, list[str]]] = []
        for chain_number, chain in enumerate(chains, start=1):
            if not 1 <= len(chain.events) <= MAX_CHAIN_EVENTS:
                raise ToolException(
                    f"Chain {chain_number}: chains hold 1 to {MAX_CHAIN_EVENTS} events "
                    f"(got {len(chain.events)})."
                )
            scratch = PlotDraft(draft.bible)
            event_ids: list[str] = []
            previous_id: str | None = None
            for spec in chain.events:
                try:
                    relation_specs = _resolve_relation_specs(scratch.bible, spec.relations)
                except ToolException as exc:
                    raise ToolException(f"Chain {chain_number}: {exc}") from exc
                if previous_id is None:
                    _require_anchor_in_range(run, relation_specs, context=f"Chain {chain_number}")
                if previous_id is not None:
                    relation_specs.append(
                        EventRelationSpec(kind=spec.link_kind, event_id=previous_id)
                    )
                try:
                    event = scratch.add_event(
                        spec.title,
                        description=spec.description,
                        relations=relation_specs,
                        signals=_signals_as_hints(spec.signals),
                    )
                except (RelationValidationError, ValueError) as exc:
                    raise ToolException(f"Chain {chain_number}: {exc}") from exc
                event_ids.append(event.id)
                previous_id = event.id
            prepared.append((scratch, event_ids))

        def _evaluate(scratch: PlotDraft, event_ids: list[str]) -> list[str]:
            from app.graphs.intimacy_interpretation import apply_interpretation_to_bible

            lines: list[str] = []
            for event_id in event_ids:
                event = scratch.bible.get_event(event_id)
                character_ids = _signal_character_ids(scratch.bible, event)
                ranks_before = _ranks_for(scratch.bible, character_ids)
                results, errors = _run_interpretations(
                    scratch.bible, event_id, character_ids, run.models
                )
                for result in results.values():
                    apply_interpretation_to_bible(scratch.bible, result)
                lines.append(f"### {event.title or 'Untitled'} [{event_id}]")
                lines.extend(_interpretation_report(scratch.bible, results, errors, ranks_before))
            return lines

        with ThreadPoolExecutor(max_workers=len(prepared)) as pool:
            futures = [
                pool.submit(_evaluate, scratch, event_ids) for scratch, event_ids in prepared
            ]
        reports = [future.result() for future in futures]

        lines: list[str] = ["# Candidate chain comparison (speculative; nothing drafted)"]
        for chain_number, (chain, (scratch, _event_ids), report) in enumerate(
            zip(chains, prepared, reports, strict=True), start=1
        ):
            label = f": {chain.title}" if chain.title else ""
            lines.append(f"## Chain {chain_number}{label}")
            lines.extend(report)
            lines.append("### Final state vs current draft")
            lines.extend(_chain_final_state_lines(draft.bible, scratch.bible, chain))
        return "\n".join(lines)

    @tool
    def nudge_intimacy(
        event_id: str,
        character_id: str,
        intimacy_id: str,
        direction: EvidenceDirection,
        rationale: str,
    ) -> str:
        """Append one bounded plot-agent evidence nudge to an existing signal.

        Use when derived rank lands just short of a target threshold and a
        whole extra event would be contrived. The nudge is capped at strength
        1, provenance-marked as plot-agent-authored (so interpretation re-runs
        never remove it), and limited to one nudge per signal per intimacy.
        The signal must already exist on the event for this character.
        """

        _require_active(run)
        if not rationale.strip():
            raise ToolException("A nudge requires a non-empty rationale.")
        resolved_event = _resolve_event_id(draft.bible, event_id)
        _require_editable(run, resolved_event)
        resolved_character = _resolve_character_id(draft.bible, character_id)
        resolved_intimacy = _resolve_intimacy_id(draft.bible, resolved_character, intimacy_id)
        event = draft.bible.get_event(resolved_event)
        signal = next(
            (item for item in event.signals if item.character_id == resolved_character),
            None,
        )
        if signal is None:
            with_signals = ", ".join(
                f"{_character_name(draft.bible, item.character_id)} [{item.character_id}]"
                for item in event.signals
                if item.character_id
            )
            raise ToolException(
                f"Event {resolved_event} has no signal for character {resolved_character}; "
                "nudges append to existing signals only. Characters with signals on this "
                f"event: {with_signals or '(none)'}."
            )
        already = any(
            entry.author == "plot_agent" and entry.intimacy_id == resolved_intimacy
            for entry in signal.evidence
        )
        if already:
            raise ToolException(
                f"Signal already carries a plot-agent nudge for {resolved_intimacy}; "
                "only one nudge per signal per intimacy is allowed."
            )
        ranks_before = _ranks_for(draft.bible, [resolved_character])
        signal.evidence.append(
            IntimacyEvidence(
                intimacy_id=resolved_intimacy,
                direction=direction,
                strength=1,
                rationale=rationale.strip(),
                author="plot_agent",
            )
        )
        draft.record_semantic_edit(
            f"Nudged {resolved_intimacy} ({direction}) on [{resolved_event}] "
            f"for {resolved_character}",
            (resolved_event,),
        )
        lines = [
            f"Nudged intimacy {resolved_intimacy} ({direction}, strength 1) on event "
            f"{resolved_event} for {resolved_character}."
        ]
        lines.extend(
            _rank_movement_lines(
                draft.bible,
                resolved_character,
                ranks_before.get(resolved_character, {}),
                [resolved_intimacy],
            )
        )
        lines.extend(_drift_note(run))
        return "\n".join(lines)

    @tool
    def reword_signal(event_id: str, character_id: str, interpretation: str) -> str:
        """Reword a signal's interpretation text. Rank-neutral.

        Changes wording only; evidence and derived rank are untouched. A later
        interpretation re-run for this character replaces the wording again
        (interpretation owns its text).
        """

        _require_active(run)
        if not interpretation.strip():
            raise ToolException("Pass a non-empty interpretation text.")
        resolved_event = _resolve_event_id(draft.bible, event_id)
        _require_editable(run, resolved_event)
        resolved_character = _resolve_character_id(draft.bible, character_id)
        event = draft.bible.get_event(resolved_event)
        signal = next(
            (item for item in event.signals if item.character_id == resolved_character),
            None,
        )
        if signal is None:
            raise ToolException(
                f"Event {resolved_event} has no signal for character {resolved_character}."
            )
        signal.interpretation = interpretation.strip()
        draft.record_semantic_edit(
            f"Reworded signal on [{resolved_event}] for {resolved_character}",
            (resolved_event,),
        )
        return (
            f"Reworded the signal on event {resolved_event} for {resolved_character}. "
            "Rank is unchanged; a later re-interpretation will replace this wording."
        )

    @tool
    def reword_evidence_rationale(
        event_id: str,
        character_id: str,
        intimacy_id: str,
        rationale: str,
        entry_index: int | None = None,
    ) -> str:
        """Reword one evidence entry's rationale. Rank-neutral.

        Targets the signal's evidence for `intimacy_id`; when several entries
        reference the same intimacy, pass `entry_index` (0-based among those
        entries). Direction and strength are untouched. Interpretation-owned
        rationales may be replaced by a later re-run.
        """

        _require_active(run)
        if not rationale.strip():
            raise ToolException("Pass a non-empty rationale.")
        resolved_event = _resolve_event_id(draft.bible, event_id)
        _require_editable(run, resolved_event)
        resolved_character = _resolve_character_id(draft.bible, character_id)
        resolved_intimacy = _resolve_intimacy_id(draft.bible, resolved_character, intimacy_id)
        event = draft.bible.get_event(resolved_event)
        signal = next(
            (item for item in event.signals if item.character_id == resolved_character),
            None,
        )
        if signal is None:
            raise ToolException(
                f"Event {resolved_event} has no signal for character {resolved_character}."
            )
        matches = [entry for entry in signal.evidence if entry.intimacy_id == resolved_intimacy]
        if not matches:
            present = ", ".join(dict.fromkeys(entry.intimacy_id for entry in signal.evidence))
            raise ToolException(
                f"The signal has no evidence for {resolved_intimacy}. "
                f"Evidence exists for: {present or '(none)'}."
            )
        if len(matches) > 1 and entry_index is None:
            listing = "; ".join(
                f"{index}: {entry.direction} strength {entry.strength} ({entry.rationale or '-'})"
                for index, entry in enumerate(matches)
            )
            raise ToolException(
                f"Multiple evidence entries reference {resolved_intimacy}; pass "
                f"entry_index. Entries: {listing}"
            )
        index = entry_index or 0
        if not 0 <= index < len(matches):
            raise ToolException(
                f"entry_index must be between 0 and {len(matches) - 1}, got {index}."
            )
        matches[index].rationale = rationale.strip()
        draft.record_semantic_edit(
            f"Reworded evidence rationale for {resolved_intimacy} on [{resolved_event}]",
            (resolved_event,),
        )
        return (
            f"Reworded the {resolved_intimacy} evidence rationale on event {resolved_event}. "
            "Rank is unchanged."
        )

    @tool
    def refresh_interpretations() -> str:
        """Re-interpret every stale-flagged event, oldest first, and diff the ripple.

        Structural edits (inserts, relation rewires, mid-timeline content
        edits) flag downstream events whose interpretations went semantically
        stale. This re-runs interpretation for each flagged event in
        chronological order (parallel per character within an event) and
        reports how evidence and rank trajectories changed. Each refreshed
        event consumes one re-interpretation budget slot; the tool stops when
        the budget runs out and lists what is still stale.
        """

        _require_active(run)
        from app.graphs.intimacy_interpretation import apply_interpretation_to_bible

        stale = draft.stale_event_ids
        if not stale:
            return "No stale events to refresh."
        ordered = [event for event in draft.chronology() if event.id in stale]
        lines = ["Refreshed stale interpretations:"]
        refreshed: list[str] = []
        for event in ordered:
            character_ids = _signal_character_ids(draft.bible, event)
            if not character_ids:
                draft.mark_interpreted(event.id)
                lines.append(f"## {event.title or 'Untitled'} [{event.id}]")
                lines.append("(no signal characters; cleared without re-running)")
                continue
            if run.reinterpretation_runs_used >= run.budget.max_reinterpretation_runs:
                remaining = sorted(draft.stale_event_ids)
                lines.append(
                    "Re-interpretation budget exhausted; still stale: " + ", ".join(remaining)
                )
                break
            evidence_before = {
                signal.character_id: _evidence_summary(signal.evidence)
                for signal in event.signals
                if signal.character_id
            }
            ranks_before = _ranks_for(draft.bible, character_ids)
            run.reinterpretation_runs_used += 1
            results, errors = _run_interpretations(draft.bible, event.id, character_ids, run.models)
            for result in results.values():
                apply_interpretation_to_bible(draft.bible, result)
            if not errors:
                draft.mark_interpreted(event.id)
                refreshed.append(event.id)
            lines.append(f"## {event.title or 'Untitled'} [{event.id}]")
            for character_id in character_ids:
                before_summary = evidence_before.get(character_id, [])
                lines.append(
                    f"- {_character_name(draft.bible, character_id)} [{character_id}] "
                    f"evidence before: {'; '.join(before_summary) or '(none)'}"
                )
            lines.extend(_interpretation_report(draft.bible, results, errors, ranks_before))
        if refreshed:
            draft.record_semantic_edit(
                f"Refreshed interpretations for {len(refreshed)} stale event(s)",
                tuple(refreshed),
            )
        lines.append(_budget_line(run))
        lines.extend(_drift_note(run))
        return "\n".join(lines)

    @tool
    def read_draft_timeline() -> str:
        """Return the draft's ordered timeline with ids, signal counts, stale flags,
        and diagnostics warnings."""

        bible = draft.bible
        ordered = draft.chronology()
        if not ordered:
            return "The draft timeline has no events yet."
        lines: list[str] = []
        for position, event in enumerate(ordered, start=1):
            relations = bible.relations_for_event(event.id)
            relation_count = (
                len(relations.incoming) + len(relations.outgoing) + len(relations.concurrent)
            )
            stale_marker = " [STALE]" if event.id in draft.stale_event_ids else ""
            description = f" - {event.description}" if event.description else ""
            lines.append(
                f"{position}. {event.title or 'Untitled'} [id: {event.id}] "
                f"({len(event.signals)} signals, {relation_count} relations)"
                f"{stale_marker}{description}"
            )
        stale = sorted(draft.stale_event_ids)
        if stale:
            lines.append("")
            lines.append("Stale interpretations (run refresh_interpretations): " + ", ".join(stale))
        relation_warnings = format_diagnostics(relation_diagnostics(bible))
        if relation_warnings:
            lines.append("")
            lines.append(relation_warnings)
        effect_warnings = format_effect_diagnostics(effect_diagnostics(bible))
        if effect_warnings:
            lines.append("")
            lines.append(effect_warnings)
        return "\n".join(lines)

    @tool
    def read_draft_state(at_event_id: str = "") -> str:
        """Return the draft's derived world and character state at a timeline position.

        With `at_event_id`, derives state after that event; without it, after
        the full draft timeline. Character intimacies include derived rank,
        accumulated net, and distance-to-threshold.
        """

        bible = draft.bible
        resolved = _resolve_event_id(bible, at_event_id) if at_event_id.strip() else None
        derived = draft.derived_state(resolved)
        lines = [
            f"# Draft Derived State (after {derived.events_applied} of "
            f"{len(bible.timeline)} events)",
            "",
            "## World State",
        ]
        if not derived.world_state:
            lines.append("(no active entries)")
        for entry in derived.world_state:
            lines.append(f"- ({entry.kind}) {entry.text} [id: {entry.id}]")
        for character in derived.characters.values():
            lines.append("")
            lines.append(f"## {character.name or 'Unnamed'} [id: {character.character_id}]")
            ranks = explain_intimacies(bible, character.character_id, resolved)
            if not character.intimacies:
                lines.append("(no intimacies)")
            for intimacy in character.intimacies:
                state = ranks.get(intimacy.id)
                extra = ""
                if state is not None:
                    extra = f" -- net {state.effective_net:.1f}; {format_threshold_distance(state)}"
                lines.append(f"- {intimacy.text} ({intimacy.strength}) [id: {intimacy.id}]{extra}")
        stale = sorted(draft.stale_event_ids)
        if stale:
            lines.append("")
            lines.append("Stale interpretations (run refresh_interpretations): " + ", ".join(stale))
        effect_warnings = format_effect_diagnostics(effect_diagnostics(bible))
        if effect_warnings:
            lines.append("")
            lines.append(effect_warnings)
        return "\n".join(lines)

    @tool
    def finish_plot(summary: str) -> str:
        """Finish the plot run successfully. Terminal: no draft edits afterwards.

        Call once the briefing's goals are met. `summary` describes what was
        drafted and why it satisfies the briefing. Refresh stale
        interpretations first; unrepaired staleness is reported as a warning.
        """

        _require_active(run)
        if not summary.strip():
            raise ToolException("Pass a non-empty summary of the drafted plot.")
        run.result = _build_result(run, status="completed", summary=summary.strip())
        lines = [
            "Plot run completed.",
            f"Drafted events: {', '.join(run.result.drafted_event_ids) or '(none)'}",
            _budget_line(run),
        ]
        if run.result.stale_event_ids:
            lines.append(
                "WARNING: stale interpretations were not refreshed: "
                + ", ".join(run.result.stale_event_ids)
            )
        lines.extend(run.result.drift_report)
        return "\n".join(lines)

    @tool
    def bail_out(
        reason: BailOutReason,
        explanation: str,
        gaps: list[ArcGapSpec] | None = None,
    ) -> str:
        """Declare the briefing infeasible. Terminal: no draft edits afterwards.

        Reasons: 'budget' (the allowed events/re-runs cannot plausibly close
        the quantified gap), 'judgment' (closing it would contradict the
        briefing's arc shape or established characterization), or
        'overconstrained' (a preservation pin conflicts with the target —
        name the pin in `conflict`). Each gap names a target arc that was not
        reached; the tool measures the current rank, net, and
        distance-to-threshold for it, so the report is quantified, not vibes.
        """

        _require_active(run)
        if not explanation.strip():
            raise ToolException("Pass a non-empty explanation for bailing out.")
        gap_report: list[ArcGapReport] = []
        for gap in gaps or []:
            character_id = _resolve_character_id(draft.bible, gap.character_id)
            intimacy_id = _resolve_intimacy_id(draft.bible, character_id, gap.intimacy_id)
            state = _ranks_for(draft.bible, [character_id])[character_id].get(intimacy_id)
            catalog = dict(draft.bible.intimacy_catalog(character_id))
            gap_report.append(
                ArcGapReport(
                    character_id=character_id,
                    character_name=_character_name(draft.bible, character_id),
                    intimacy_id=intimacy_id,
                    intimacy_text=catalog.get(intimacy_id, ""),
                    target=gap.target,
                    conflict=gap.conflict,
                    current_rank=state.rank if state is not None else "unknown",
                    effective_net=state.effective_net if state is not None else 0.0,
                    threshold_distance=(
                        format_threshold_distance(state) if state is not None else ""
                    ),
                )
            )
        run.result = _build_result(
            run,
            status="infeasible",
            summary=explanation.strip(),
            reason=reason,
            gap_report=gap_report,
        )
        lines = [f"Plot run bailed out ({reason}): {explanation.strip()}", _budget_line(run)]
        for item in gap_report:
            lines.append(
                f"- {item.character_name} [{item.character_id}] "
                f"{item.intimacy_text or item.intimacy_id} [{item.intimacy_id}]: "
                f"currently {item.current_rank} (net {item.effective_net:.1f}; "
                f"{item.threshold_distance}); target: {item.target}"
                + (f"; conflict: {item.conflict}" if item.conflict else "")
            )
        lines.extend(run.result.drift_report)
        return "\n".join(lines)

    toolset = PlotDraftToolset(
        run=run,
        tools=[
            add_draft_event,
            insert_draft_event,
            update_draft_event,
            delete_draft_event,
            edit_draft_relations,
            explore_candidates,
            nudge_intimacy,
            reword_signal,
            reword_evidence_rationale,
            refresh_interpretations,
            read_draft_timeline,
            read_draft_state,
            finish_plot,
            bail_out,
        ],
    )
    return toolset


def _chain_final_state_lines(
    base_bible: StoryBible,
    final_bible: StoryBible,
    chain: CandidateChain,
) -> list[str]:
    """Compare final ranks after a chain against the current draft, per character."""

    character_ids: list[str] = []
    for spec in chain.events:
        for signal in spec.signals:
            character_id = signal.character_id
            if (
                character_id
                and character_id not in character_ids
                and final_bible.get_character(character_id) is not None
            ):
                character_ids.append(character_id)
    if not character_ids:
        return ["(no signal characters in this chain)"]

    lines: list[str] = []
    for character_id in character_ids:
        base_ranks = _ranks_for(base_bible, [character_id]).get(character_id, {})
        final_ranks = _ranks_for(final_bible, [character_id]).get(character_id, {})
        catalog = dict(final_bible.intimacy_catalog(character_id))
        name = _character_name(final_bible, character_id)
        moved = False
        for intimacy_id, state in final_ranks.items():
            base = base_ranks.get(intimacy_id)
            base_rank = base.rank if base is not None else "new"
            base_net = base.effective_net if base is not None else 0.0
            if base is not None and abs(state.effective_net - base_net) < 0.05:
                continue
            moved = True
            lines.append(
                f"- {name}: {catalog.get(intimacy_id, intimacy_id)} [{intimacy_id}]: "
                f"{base_rank} (net {base_net:.1f}) -> {state.rank} "
                f"(net {state.effective_net:.1f}); {format_threshold_distance(state)}"
            )
        if not moved:
            lines.append(f"- {name}: no rank movement")
    return lines
