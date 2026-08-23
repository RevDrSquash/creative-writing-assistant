"""Tests for the plot-draft agent toolset: validation, inline interpretation,
candidate chains, bounded nudges/rewords, refresh, reads, and terminal tools."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import ToolException

from app.graphs.intimacy_workflow import AnalysisOutput, EvidenceProposal, ReviewOutput
from app.graphs.scene_workflow import structured_fake_model
from app.models.config import INTIMACY_ANALYZE_NODE_ID, INTIMACY_REVIEW_NODE_ID
from app.tools.plot_draft import (
    ArcGapSpec,
    CandidateChain,
    CandidateEventSpec,
    DraftRelationSpec,
    PinnedIntimacy,
    PlotBudget,
    PlotDraftToolset,
    RankTarget,
    create_plot_draft_toolset,
)
from app.world.draft import PlotDraft
from app.world.models import (
    Character,
    CharacterBaselineState,
    CharacterIdentity,
    Event,
    EventRelation,
    EventRelationSpec,
    Intimacy,
    IntimacyEvidence,
    Signal,
    StoryBible,
    World,
)


def _mira_signal(strength: int = 2) -> Signal:
    return Signal(
        character_id="char_mira",
        interpretation="A hint",
        evidence=[
            IntimacyEvidence(intimacy_id="intim_wary", direction="supports", strength=strength)
        ],
    )


def _bible() -> StoryBible:
    """Three events: gate -> meal (directly_follows), watch follows meal."""

    return StoryBible(
        characters=[
            Character(
                id="char_mira",
                identity=CharacterIdentity(name="Mira"),
                baseline_state=CharacterBaselineState(
                    intimacies=[
                        Intimacy(id="intim_wary", text="Wary of outsiders", strength="minor")
                    ]
                ),
            ),
            Character(id="char_kael", identity=CharacterIdentity(name="Kael")),
        ],
        timeline=[
            Event(id="evt_gate", title="The gate", signals=[_mira_signal()]),
            Event(id="evt_meal", title="The meal", signals=[_mira_signal()]),
            Event(
                id="evt_watch",
                title="The watch",
                signals=[Signal(character_id="char_kael", interpretation="Quiet night")],
            ),
        ],
        event_relations=[
            EventRelation(
                id="rel_meal",
                kind="directly_follows",
                source_id="evt_meal",
                target_id="evt_gate",
            ),
            EventRelation(
                id="rel_watch", kind="follows", source_id="evt_watch", target_id="evt_meal"
            ),
        ],
    )


def _models(strength: int = 3) -> dict[str, Any]:
    analysis = AnalysisOutput(
        interpretation="I still cannot trust them.",
        evidence=[
            EvidenceProposal(
                intimacy_id="intim_wary",
                direction="supports",
                strength=strength,
                rationale="The stranger pressed too close.",
            )
        ],
    )
    review = ReviewOutput(
        decision="approved",
        notes="Sound.",
        evidence=[
            EvidenceProposal(
                intimacy_id="intim_wary",
                direction="supports",
                strength=strength,
                rationale="The stranger pressed too close.",
                novelty="novel",
            )
        ],
    )
    return {
        INTIMACY_ANALYZE_NODE_ID: structured_fake_model(analysis),
        INTIMACY_REVIEW_NODE_ID: structured_fake_model(review),
    }


def _toolset(
    draft: PlotDraft,
    *,
    max_new_events: int = 5,
    max_reinterpretation_runs: int = 5,
    strength: int = 3,
    auto_plan: bool = True,
) -> PlotDraftToolset:
    toolset = create_plot_draft_toolset(
        draft,
        PlotBudget(
            max_new_events=max_new_events,
            max_reinterpretation_runs=max_reinterpretation_runs,
        ),
        models=_models(strength),
    )
    if auto_plan:
        toolset.tool("plan_rank_targets").func(
            targets=[],
            note="This test does not intend rank movement.",
        )
    return toolset


# ---------------------------------------------------------- rank-target planning


def test_draft_writes_require_a_rank_target_plan() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft, auto_plan=False)

    with pytest.raises(ToolException, match="plan_rank_targets"):
        toolset.tool("add_draft_event").func(
            title="The alley",
            relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
        )

    assert draft.bible.get_event("evt_the_alley") is None
    assert toolset.run.new_events_used == 0


def test_rank_target_plan_validates_ids_and_empty_intent() -> None:
    toolset = _toolset(PlotDraft(_bible()), auto_plan=False)

    with pytest.raises(ToolException, match="non-empty note"):
        toolset.tool("plan_rank_targets").func(targets=[])
    with pytest.raises(ToolException, match="Valid characters"):
        toolset.tool("plan_rank_targets").func(
            targets=[
                RankTarget(
                    character_id="char_invented",
                    intimacy_id="intim_wary",
                    target_rank="moderate",
                )
            ]
        )
    with pytest.raises(ToolException, match="Valid intimacies"):
        toolset.tool("plan_rank_targets").func(
            targets=[
                RankTarget(
                    character_id="char_mira",
                    intimacy_id="intim_invented",
                    target_rank="moderate",
                )
            ]
        )

    result = toolset.tool("plan_rank_targets").func(
        targets=[],
        note="The requested edit is rank-neutral.",
    )
    assert "none declared" in result
    assert toolset.run.rank_targets == []


def test_rank_target_scoreboard_reports_hit_not_yet_and_transient_hit() -> None:
    hit_toolset = _toolset(PlotDraft(_bible()), auto_plan=False)
    hit = hit_toolset.tool("plan_rank_targets").func(
        targets=[
            RankTarget(
                character_id="char_mira",
                intimacy_id="intim_wary",
                target_rank="minor",
            )
        ]
    )
    assert "HIT Mira" in hit

    not_yet = hit_toolset.tool("plan_rank_targets").func(
        targets=[
            RankTarget(
                character_id="char_mira",
                intimacy_id="intim_wary",
                target_rank="moderate",
            )
        ]
    )
    assert "NOT YET Mira" in not_yet
    assert "from moderate" in not_yet
    assert hit_toolset.run.rank_target_revisions == 1

    intimacy = Intimacy(id="intim_wary", text="Wary of outsiders", strength="minor")
    character = Character(
        id="char_mira",
        identity=CharacterIdentity(name="Mira"),
        baseline_state=CharacterBaselineState(intimacies=[intimacy]),
    )
    observations = [
        ("supports", 3),
        ("supports", 3),
        ("supports", 3),
        ("contradicts", 5),
        ("contradicts", 5),
    ]
    events = [
        Event(
            id=f"evt_{index}",
            title=f"Beat {index}",
            signals=[
                Signal(
                    character_id=character.id,
                    evidence=[
                        IntimacyEvidence(
                            intimacy_id=intimacy.id,
                            direction=direction,
                            strength=strength,
                        )
                    ],
                )
            ],
        )
        for index, (direction, strength) in enumerate(observations, start=1)
    ]
    transient_toolset = _toolset(
        PlotDraft(StoryBible(characters=[character], timeline=events)),
        auto_plan=False,
    )
    transient = transient_toolset.tool("plan_rank_targets").func(
        targets=[
            RankTarget(
                character_id=character.id,
                intimacy_id=intimacy.id,
                target_rank="moderate",
            )
        ]
    )
    assert "TRANSIENT HIT Mira" in transient
    assert "current minor" in transient


def test_finish_rejects_or_acknowledges_unmet_rank_targets() -> None:
    toolset = _toolset(PlotDraft(_bible()), auto_plan=False)
    toolset.tool("plan_rank_targets").func(
        targets=[
            RankTarget(
                character_id="char_mira",
                intimacy_id="intim_wary",
                target_rank="moderate",
            )
        ]
    )

    with pytest.raises(ToolException, match="Rank targets remain unmet"):
        toolset.tool("finish_plot").func(summary="The shape is otherwise complete.")

    result = toolset.tool("finish_plot").func(
        summary="The shape is otherwise complete.",
        unmet_targets_note="The event budget was intentionally reserved for another arc.",
    )
    assert "Plot run completed" in result
    outcome = toolset.run.result
    assert outcome is not None
    assert outcome.rank_targets[0].status == "not_yet"
    assert outcome.rank_targets[0].target_rank == "moderate"
    assert outcome.gap_report[0].target == "moderate"
    assert "intentionally reserved" in outcome.gap_report[0].conflict


# ------------------------------------------------- write + inline interpretation


def test_add_draft_event_interprets_and_reports_rank_feedback(isolated_world: World) -> None:
    base = _bible()
    before = base.model_dump(mode="json")
    draft = PlotDraft(base)
    toolset = _toolset(draft)

    result = toolset.tool("add_draft_event").func(
        title="The alley",
        description="A shortcut goes wrong.",
        relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
        signals=[Signal(character_id="char_mira", interpretation="Trouble follows me.")],
    )

    assert "Added draft event 'The alley'" in result
    assert "supports intim_wary" in result
    assert "Wary of outsiders [intim_wary]" in result
    assert "net " in result
    assert toolset.run.new_events_used == 1
    event = draft.bible.timeline[-1]
    signal = event.signals[0]
    assert signal.interpretation == "I still cannot trust them."
    assert [entry.intimacy_id for entry in signal.evidence] == ["intim_wary"]
    assert base.model_dump(mode="json") == before


def test_add_draft_event_rejects_hallucinated_relation_target() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    before = draft.bible.model_dump(mode="json")

    with pytest.raises(ToolException, match="Valid events"):
        toolset.tool("add_draft_event").func(
            title="Floating",
            relations=[EventRelationSpec(kind="follows", event_id="evt_nope")],
        )

    assert draft.bible.model_dump(mode="json") == before
    assert toolset.run.new_events_used == 0


def test_add_draft_event_rejects_unknown_signal_character() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)

    with pytest.raises(ToolException, match="Valid characters"):
        toolset.tool("add_draft_event").func(
            title="The alley",
            relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
            signals=[Signal(character_id="char_ghost", interpretation="Boo")],
        )


def test_new_event_budget_exhaustion_points_at_terminal_tools(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft, max_new_events=1)
    toolset.tool("add_draft_event").func(
        title="The alley",
        relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
    )

    with pytest.raises(ToolException, match=r"budget exhausted.*finish_plot"):
        toolset.tool("add_draft_event").func(
            title="One too many",
            relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
        )


def test_update_draft_event_reinterprets_and_flags_downstream(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)

    result = toolset.tool("update_draft_event").func(
        event_id="evt_gate",
        description="Rewritten opening.",
    )

    assert "Updated draft event" in result
    assert "Stale downstream" in result
    assert "evt_meal" in result
    assert toolset.run.reinterpretation_runs_used == 1
    assert "evt_meal" in draft.stale_event_ids
    signal = draft.bible.get_event("evt_gate").signals[0]
    assert signal.interpretation == "I still cannot trust them."


def test_update_draft_event_rejects_unknown_id() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)

    with pytest.raises(ToolException, match="Valid events"):
        toolset.tool("update_draft_event").func(event_id="evt_hallucinated", description="Nope")


def test_update_blocked_when_reinterpretation_budget_exhausted() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft, max_reinterpretation_runs=0)

    with pytest.raises(ToolException, match="Re-interpretation budget exhausted"):
        toolset.tool("update_draft_event").func(event_id="evt_gate", description="Rewritten.")

    assert draft.bible.get_event("evt_gate").description == ""


def test_insert_draft_event_rewires_and_lists_stale(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)

    result = toolset.tool("insert_draft_event").func(
        title="The alley",
        earlier_event_id="evt_gate",
        later_event_id="evt_meal",
        signals=[Signal(character_id="char_mira", interpretation="A detour.")],
    )

    assert "Inserted draft event" in result
    assert "Stale downstream" in result
    assert "evt_meal" in result
    assert toolset.run.new_events_used == 1
    order = [event.id for event in draft.chronology()]
    inserted = draft.bible.timeline[-1].id
    assert order.index("evt_gate") < order.index(inserted) < order.index("evt_meal")


def test_insert_requires_adjacent_anchors() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)

    with pytest.raises(ToolException, match="not directly linked"):
        toolset.tool("insert_draft_event").func(
            title="The alley",
            earlier_event_id="evt_gate",
            later_event_id="evt_watch",
        )
    assert toolset.run.new_events_used == 0


def test_delete_draft_event_prunes_and_reports_stale() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)

    result = toolset.tool("delete_draft_event").func(event_id="evt_meal")

    assert "Deleted draft event 'The meal'" in result
    assert draft.bible.get_event("evt_meal") is None

    with pytest.raises(ToolException, match="Valid events"):
        toolset.tool("delete_draft_event").func(event_id="evt_hallucinated")


def test_edit_draft_relations_reports_per_op_and_flags_reorder() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    from app.tools.plot_draft import DraftRelationSpec

    result = toolset.tool("edit_draft_relations").func(
        remove_relation_ids=["rel_watch", "rel_missing"],
        add=[DraftRelationSpec(kind="follows", source_id="evt_watch", target_id="evt_gate")],
    )

    assert "- remove rel_watch: OK" in result
    assert "- remove rel_missing: ERROR" in result
    assert "- add follows [evt_watch -> evt_gate]: OK" in result
    pairs = {
        (relation.kind, relation.source_id, relation.target_id)
        for relation in draft.bible.event_relations
    }
    assert ("follows", "evt_watch", "evt_gate") in pairs

    with pytest.raises(ToolException, match="at least one"):
        toolset.tool("edit_draft_relations").func()


# --------------------------------------------------------------- candidate chains


def test_explore_candidates_compares_chains_without_drafting(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    before = draft.bible.model_dump(mode="json")
    chains = [
        CandidateChain(
            title="Confrontation",
            events=[
                CandidateEventSpec(
                    title="The alley",
                    relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
                    signals=[Signal(character_id="char_mira", interpretation="Cornered.")],
                )
            ],
        ),
        CandidateChain(
            title="Slow burn",
            events=[
                CandidateEventSpec(
                    title="The market",
                    relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
                    signals=[Signal(character_id="char_mira", interpretation="Watched.")],
                ),
                CandidateEventSpec(
                    title="The rooftop",
                    link_kind="directly_follows",
                    signals=[Signal(character_id="char_mira", interpretation="Followed.")],
                ),
            ],
        ),
    ]

    first = toolset.tool("explore_candidates").func(chains=chains)
    second = toolset.tool("explore_candidates").func(chains=chains)

    assert first == second  # deterministic with stub models
    assert "## Chain 1: Confrontation" in first
    assert "## Chain 2: Slow burn" in first
    assert "The rooftop" in first
    assert "Final state vs current draft" in first
    assert "Wary of outsiders [intim_wary]" in first
    assert draft.bible.model_dump(mode="json") == before
    assert toolset.run.new_events_used == 0
    assert toolset.run.reinterpretation_runs_used == 0
    assert draft.steps == ()


def test_explore_candidates_validates_shape_and_anchors() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    anchored = CandidateEventSpec(
        title="The alley",
        relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
    )

    with pytest.raises(ToolException, match="between 2 and 4"):
        toolset.tool("explore_candidates").func(chains=[CandidateChain(events=[anchored])])

    too_long = CandidateChain(events=[anchored.model_copy(deep=True) for _ in range(4)])
    with pytest.raises(ToolException, match="1 to 3 events"):
        toolset.tool("explore_candidates").func(
            chains=[CandidateChain(events=[anchored]), too_long]
        )

    bad_anchor = CandidateChain(
        events=[
            CandidateEventSpec(
                title="Nowhere",
                relations=[EventRelationSpec(kind="follows", event_id="evt_nope")],
            )
        ]
    )
    with pytest.raises(ToolException, match="Chain 2"):
        toolset.tool("explore_candidates").func(
            chains=[CandidateChain(events=[anchored]), bad_anchor]
        )


# ----------------------------------------------------------- nudges and rewords


def test_nudge_appends_capped_provenance_marked_entry() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)

    result = toolset.tool("nudge_intimacy").func(
        event_id="evt_meal",
        character_id="char_mira",
        intimacy_id="intim_wary",
        direction="supports",
        rationale="The shared meal cements it.",
    )

    assert "Nudged intimacy intim_wary" in result
    signal = draft.bible.get_event("evt_meal").signals[0]
    nudges = [entry for entry in signal.evidence if entry.author == "plot_agent"]
    assert len(nudges) == 1
    assert nudges[0].strength == 1
    assert nudges[0].direction == "supports"

    with pytest.raises(ToolException, match="only one nudge"):
        toolset.tool("nudge_intimacy").func(
            event_id="evt_meal",
            character_id="char_mira",
            intimacy_id="intim_wary",
            direction="contradicts",
            rationale="Second thoughts.",
        )


def test_nudge_rejects_hallucinated_ids_and_missing_signal() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)

    with pytest.raises(ToolException, match="Valid intimacies"):
        toolset.tool("nudge_intimacy").func(
            event_id="evt_meal",
            character_id="char_mira",
            intimacy_id="intim_invented",
            direction="supports",
            rationale="x",
        )

    # evt_watch has a signal for Kael only.
    with pytest.raises(ToolException, match="no signal for character"):
        toolset.tool("nudge_intimacy").func(
            event_id="evt_watch",
            character_id="char_mira",
            intimacy_id="intim_wary",
            direction="supports",
            rationale="x",
        )


def test_nudge_survives_interpretation_rerun(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    toolset.tool("nudge_intimacy").func(
        event_id="evt_gate",
        character_id="char_mira",
        intimacy_id="intim_wary",
        direction="supports",
        rationale="Keep the edge.",
    )

    toolset.tool("update_draft_event").func(event_id="evt_gate", description="Rewritten opening.")

    signal = draft.bible.get_event("evt_gate").signals[0]
    authors = [(entry.author, entry.strength) for entry in signal.evidence]
    assert ("plot_agent", 1) in authors
    interpretation_entries = [
        entry for entry in signal.evidence if entry.author == "interpretation"
    ]
    assert len(interpretation_entries) == 1
    assert interpretation_entries[0].strength == 3  # replaced by the stub's re-run


def test_reword_tools_are_rank_neutral() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    net_before = draft.explain("char_mira")["intim_wary"].effective_net

    toolset.tool("reword_signal").func(
        event_id="evt_gate",
        character_id="char_mira",
        interpretation="Strangers still mean risk.",
    )
    toolset.tool("reword_evidence_rationale").func(
        event_id="evt_gate",
        character_id="char_mira",
        intimacy_id="intim_wary",
        rationale="Sharper wording.",
    )

    signal = draft.bible.get_event("evt_gate").signals[0]
    assert signal.interpretation == "Strangers still mean risk."
    assert signal.evidence[0].rationale == "Sharper wording."
    assert draft.explain("char_mira")["intim_wary"].effective_net == net_before


def test_reword_evidence_requires_index_when_ambiguous() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    signal = draft.bible.get_event("evt_gate").signals[0]
    signal.evidence.append(
        IntimacyEvidence(intimacy_id="intim_wary", direction="contradicts", strength=1)
    )

    with pytest.raises(ToolException, match="entry_index"):
        toolset.tool("reword_evidence_rationale").func(
            event_id="evt_gate",
            character_id="char_mira",
            intimacy_id="intim_wary",
            rationale="Which one?",
        )

    toolset.tool("reword_evidence_rationale").func(
        event_id="evt_gate",
        character_id="char_mira",
        intimacy_id="intim_wary",
        rationale="The second one.",
        entry_index=1,
    )
    assert signal.evidence[1].rationale == "The second one."


# ------------------------------------------------------------------- refresh


def test_refresh_reinterprets_stale_events_and_diffs(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    toolset.tool("update_draft_event").func(event_id="evt_gate", description="Rewritten opening.")
    assert "evt_meal" in draft.stale_event_ids

    result = toolset.tool("refresh_interpretations").func()

    assert "Refreshed stale interpretations" in result
    assert "The meal [evt_meal]" in result
    assert "evidence before" in result
    assert draft.stale_event_ids == frozenset()
    assert toolset.run.reinterpretation_runs_used == 2
    signal = draft.bible.get_event("evt_meal").signals[0]
    assert signal.interpretation == "I still cannot trust them."

    assert toolset.tool("refresh_interpretations").func().startswith(
        "No stale events to refresh."
    )


def test_refresh_stops_at_budget_and_lists_remaining(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft, max_reinterpretation_runs=1)
    toolset.tool("update_draft_event").func(event_id="evt_gate", description="Rewritten opening.")

    result = toolset.tool("refresh_interpretations").func()

    assert "budget exhausted" in result
    assert "evt_meal" in result
    assert "evt_meal" in draft.stale_event_ids
    assert toolset.run.reinterpretation_runs_used == 1


# --------------------------------------------------------------------- reads


def test_read_draft_timeline_marks_stale_and_orders_events() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    draft.update_event("evt_gate", description="Rewritten opening.")

    result = toolset.tool("read_draft_timeline").func()

    assert "1. The gate [id: evt_gate]" in result
    assert "[STALE]" in result
    assert "Stale interpretations" in result
    assert "evt_meal" in result


def test_read_draft_state_shows_ranks_and_thresholds() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)

    result = toolset.tool("read_draft_state").func()

    assert "Draft Derived State" in result
    assert "Mira" in result
    assert "Wary of outsiders" in result
    assert "net " in result

    with pytest.raises(ToolException, match="Valid events"):
        toolset.tool("read_draft_state").func(at_event_id="evt_nope")


# ---------------------------------------------------------------- terminal tools


def test_finish_plot_produces_completed_result(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    toolset.tool("add_draft_event").func(
        title="The alley",
        relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
    )

    result = toolset.tool("finish_plot").func(summary="Added the alley confrontation.")

    assert "Plot run completed" in result
    outcome = toolset.run.result
    assert outcome is not None
    assert outcome.status == "completed"
    assert outcome.summary == "Added the alley confrontation."
    assert len(outcome.drafted_event_ids) == 1
    assert outcome.new_events_used == 1
    assert outcome.new_events_budget == 5
    assert outcome.step_summaries

    with pytest.raises(ToolException, match="already produced"):
        toolset.tool("add_draft_event").func(
            title="Too late",
            relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
        )
    with pytest.raises(ToolException, match="already produced"):
        toolset.tool("finish_plot").func(summary="Again.")


def test_bail_out_builds_measured_gap_report() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)

    result = toolset.tool("bail_out").func(
        reason="overconstrained",
        explanation="Reaching major would violate the preservation pin on Kael's trust.",
        gaps=[
            ArcGapSpec(
                character_id="char_mira",
                intimacy_id="intim_wary",
                target="major by the midpoint",
                conflict="pinned: Kael's trust in Mira",
            )
        ],
    )

    assert "bailed out (overconstrained)" in result
    outcome = toolset.run.result
    assert outcome is not None
    assert outcome.status == "infeasible"
    assert outcome.reason == "overconstrained"
    gap = outcome.gap_report[0]
    assert gap.character_name == "Mira"
    assert gap.intimacy_text == "Wary of outsiders"
    assert gap.current_rank == "minor"
    assert gap.threshold_distance  # measured, not vibes
    assert gap.conflict == "pinned: Kael's trust in Mira"


def test_bail_out_rejects_hallucinated_gap_ids() -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)

    with pytest.raises(ToolException, match="Valid intimacies"):
        toolset.tool("bail_out").func(
            reason="budget",
            explanation="Cannot close the gap.",
            gaps=[
                ArcGapSpec(
                    character_id="char_mira",
                    intimacy_id="intim_invented",
                    target="major",
                )
            ],
        )
    assert toolset.run.result is None


# --------------------------------------------------- preservation pins and drift


def _pinned_toolset(draft: PlotDraft, **kwargs: Any) -> PlotDraftToolset:
    toolset = create_plot_draft_toolset(
        draft,
        PlotBudget(max_new_events=5, max_reinterpretation_runs=5),
        models=_models(5),
        pins=[PinnedIntimacy(character_id="char_mira", intimacy_id="intim_wary")],
        **kwargs,
    )
    toolset.tool("plan_rank_targets").func(
        targets=[],
        note="This test measures preservation drift only.",
    )
    return toolset


def test_pin_drift_is_measured_in_write_results(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _pinned_toolset(draft)

    result = toolset.tool("add_draft_event").func(
        title="The alley",
        relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
        signals=[Signal(character_id="char_mira", interpretation="Trouble follows me.")],
    )

    assert "Preservation pins" in result
    pin_line = next(line for line in result.splitlines() if "[intim_wary]" in line and "->" in line)
    # Strength-5 approved evidence moves the pinned net, so the pin is not stable.
    assert "stable" not in pin_line


def test_pin_reports_stable_when_untouched(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _pinned_toolset(draft)

    # Kael has no intimacies, so the stub proposal for intim_wary is dropped by
    # interpretation validation and the pinned intimacy never moves.
    result = toolset.tool("add_draft_event").func(
        title="The watchtower",
        relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
        signals=[Signal(character_id="char_kael", interpretation="A quiet climb.")],
    )

    assert "Preservation pins" in result
    pin_line = next(line for line in result.splitlines() if "[intim_wary]" in line)
    assert "stable" in pin_line
    assert "PIN DRIFT" not in result


def test_pin_drift_lands_in_plan_result(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _pinned_toolset(draft)

    toolset.tool("finish_plot").func(summary="No changes needed.")

    outcome = toolset.run.result
    assert outcome is not None
    assert any("Preservation pins" in line for line in outcome.drift_report)


def test_unknown_pin_ids_are_rejected() -> None:
    draft = PlotDraft(_bible())

    with pytest.raises(ValueError, match="Valid characters"):
        create_plot_draft_toolset(
            draft,
            PlotBudget(max_new_events=1, max_reinterpretation_runs=1),
            pins=[PinnedIntimacy(character_id="char_invented", intimacy_id="intim_wary")],
        )
    with pytest.raises(ValueError, match="Valid intimacies"):
        create_plot_draft_toolset(
            draft,
            PlotBudget(max_new_events=1, max_reinterpretation_runs=1),
            pins=[PinnedIntimacy(character_id="char_mira", intimacy_id="intim_invented")],
        )


# ------------------------------------------------------ revise-range containment


def _revise_toolset(draft: PlotDraft, start: str, end: str) -> PlotDraftToolset:
    toolset = create_plot_draft_toolset(
        draft,
        PlotBudget(max_new_events=5, max_reinterpretation_runs=5),
        models=_models(),
        revise_range=(start, end),
    )
    toolset.tool("plan_rank_targets").func(
        targets=[],
        note="This test exercises revise-range containment.",
    )
    return toolset


def test_revise_range_makes_outside_events_read_only(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _revise_toolset(draft, "evt_gate", "evt_meal")

    with pytest.raises(ToolException, match="read-only"):
        toolset.tool("update_draft_event").func(event_id="evt_watch", title="Renamed")
    with pytest.raises(ToolException, match="read-only"):
        toolset.tool("delete_draft_event").func(event_id="evt_watch")
    with pytest.raises(ToolException, match="read-only"):
        toolset.tool("reword_signal").func(
            event_id="evt_watch", character_id="char_kael", interpretation="New wording."
        )
    assert draft.bible.get_event("evt_watch").title == "The watch"


def test_revise_range_allows_in_range_edits_and_reports_end_state_drift(
    isolated_world: World,
) -> None:
    draft = PlotDraft(_bible())
    toolset = _revise_toolset(draft, "evt_gate", "evt_meal")

    result = toolset.tool("update_draft_event").func(
        event_id="evt_meal", description="The meal turns tense."
    )

    assert "Updated draft event" in result
    assert "End-state drift vs original timeline" in result


def test_insert_needs_an_anchor_inside_the_revise_range(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _revise_toolset(draft, "evt_gate", "evt_gate")

    with pytest.raises(ToolException, match="outside this run's revise range"):
        toolset.tool("insert_draft_event").func(
            title="Between meal and watch",
            earlier_event_id="evt_meal",
            later_event_id="evt_watch",
        )

    result = toolset.tool("insert_draft_event").func(
        title="Between gate and meal",
        earlier_event_id="evt_gate",
        later_event_id="evt_meal",
    )
    assert "Inserted draft event" in result


def test_add_event_needs_an_anchor_inside_the_revise_range(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _revise_toolset(draft, "evt_gate", "evt_gate")

    with pytest.raises(ToolException, match="inside the revise range"):
        toolset.tool("add_draft_event").func(
            title="The alley",
            relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
        )

    result = toolset.tool("add_draft_event").func(
        title="The alley",
        relations=[EventRelationSpec(kind="follows", event_id="evt_gate")],
    )
    assert "Added draft event" in result


def test_relation_edits_reject_protected_endpoints(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _revise_toolset(draft, "evt_gate", "evt_gate")

    result = toolset.tool("edit_draft_relations").func(
        add=[DraftRelationSpec(kind="depends_on", source_id="evt_watch", target_id="evt_gate")],
        remove_relation_ids=["rel_watch"],
    )

    assert result.count("ERROR") == 2
    assert "read-only" in result
    assert draft.bible.get_event_relation("rel_watch") is not None
    assert len(draft.bible.event_relations) == 2


def test_candidate_chains_respect_the_revise_range(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _revise_toolset(draft, "evt_gate", "evt_gate")

    with pytest.raises(ToolException, match="Chain 1"):
        toolset.tool("explore_candidates").func(
            chains=[
                CandidateChain(
                    events=[
                        CandidateEventSpec(
                            title="Out of range",
                            relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
                        )
                    ]
                ),
                CandidateChain(
                    events=[
                        CandidateEventSpec(
                            title="In range",
                            relations=[EventRelationSpec(kind="follows", event_id="evt_gate")],
                        )
                    ]
                ),
            ]
        )


def test_unknown_revise_range_ids_are_rejected() -> None:
    draft = PlotDraft(_bible())

    with pytest.raises(ValueError, match="Valid events"):
        create_plot_draft_toolset(
            draft,
            PlotBudget(max_new_events=1, max_reinterpretation_runs=1),
            revise_range=("evt_gate", "evt_invented"),
        )
