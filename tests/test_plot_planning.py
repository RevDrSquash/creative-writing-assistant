"""Tests for the plan_plot chat tool: validation, claim handling, commit-on-success,
no-commit-on-infeasible, and the chat toolset boundary (event writes live only in
the plot sub-agent)."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import ToolException

import app.graphs.plot_agent as plot_agent_module
from app.graphs.context import DEFAULT_SYSTEM_PROMPT
from app.graphs.intimacy_workflow import AnalysisOutput, EvidenceProposal, ReviewOutput
from app.graphs.jobs import get_job_manager
from app.graphs.scene_workflow import structured_fake_model
from app.models.config import INTIMACY_ANALYZE_NODE_ID, INTIMACY_REVIEW_NODE_ID
from app.tools import WRITING_TOOLS
from app.tools.plot_draft import PinnedIntimacy, create_plot_draft_toolset
from app.tools.plot_planning import plan_plot
from app.world.models import (
    Character,
    CharacterBaselineState,
    CharacterIdentity,
    Event,
    EventRelation,
    EventRelationSpec,
    Intimacy,
    Signal,
    StoryBible,
    World,
)


def _bible() -> StoryBible:
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
        ],
        timeline=[
            Event(id="evt_gate", title="The gate"),
            Event(id="evt_meal", title="The meal"),
        ],
        event_relations=[
            EventRelation(
                id="rel_meal", kind="follows", source_id="evt_meal", target_id="evt_gate"
            ),
        ],
    )


def _models() -> dict[str, Any]:
    analysis = AnalysisOutput(
        interpretation="I still cannot trust them.",
        evidence=[
            EvidenceProposal(
                intimacy_id="intim_wary",
                direction="supports",
                strength=3,
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
                strength=3,
                rationale="The stranger pressed too close.",
                novelty="novel",
            )
        ],
    )
    return {
        INTIMACY_ANALYZE_NODE_ID: structured_fake_model(analysis),
        INTIMACY_REVIEW_NODE_ID: structured_fake_model(review),
    }


def _stub_run_plot_agent(outcome: str):
    """A run_plot_agent stand-in that drives the real toolset against the draft."""

    def fake_run(
        draft,
        budget,
        briefing,
        *,
        model=None,
        models=None,
        guidance="",
        pins=None,
        revise_range=None,
        recursion_limit=None,
    ):
        toolset = create_plot_draft_toolset(
            draft, budget, models=_models(), pins=pins, revise_range=revise_range
        )
        if outcome == "completed":
            toolset.tool("add_draft_event").func(
                title="The alley",
                relations=[EventRelationSpec(kind="follows", event_id="evt_meal")],
                signals=[Signal(character_id="char_mira", interpretation="Trouble.")],
            )
            toolset.tool("finish_plot").func(summary="Mira's wariness deepens.")
        elif outcome == "no_changes":
            toolset.tool("finish_plot").func(summary="The timeline already fits the goal.")
        else:
            toolset.tool("bail_out").func(
                reason="budget",
                explanation="One event cannot close the measured gap.",
            )
        return toolset.run.result

    return fake_run


def _seed_world(world: World) -> None:
    world.story_bible = _bible()


# -------------------------------------------------------------------- outcomes


def test_completed_run_commits_to_the_live_world(
    isolated_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_world(isolated_world)
    monkeypatch.setattr(plot_agent_module, "run_plot_agent", _stub_run_plot_agent("completed"))

    result = plan_plot.func(
        briefing="Deepen Mira's wariness through the midpoint.",
        max_new_events=2,
        max_reinterpretation_runs=2,
    )

    assert "Plot run completed" in result
    assert "Committed to the live timeline" in result
    titles = [event.title for event in isolated_world.story_bible.timeline]
    assert "The alley" in titles
    # The new event carries interpretation-authored evidence from the draft run.
    alley = next(e for e in isolated_world.story_bible.timeline if e.title == "The alley")
    assert alley.signals
    assert alley.signals[0].evidence
    jobs = get_job_manager().finished_jobs()
    assert any(job.kind == "plot_draft" and job.status == "finished" for job in jobs)


def test_infeasible_run_commits_nothing_and_reports_the_reason(
    isolated_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_world(isolated_world)
    before = isolated_world.story_bible.model_dump(mode="json")
    monkeypatch.setattr(plot_agent_module, "run_plot_agent", _stub_run_plot_agent("infeasible"))

    result = plan_plot.func(
        briefing="Reach defining wariness in one event.",
        max_new_events=1,
        max_reinterpretation_runs=1,
    )

    assert "infeasible (budget)" in result
    assert "nothing was committed" in result
    assert isolated_world.story_bible.model_dump(mode="json") == before


def test_completed_run_with_no_steps_commits_nothing(
    isolated_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_world(isolated_world)
    monkeypatch.setattr(plot_agent_module, "run_plot_agent", _stub_run_plot_agent("no_changes"))

    result = plan_plot.func(
        briefing="Verify the arc already lands.",
        max_new_events=1,
        max_reinterpretation_runs=1,
    )

    assert "no changes" in result
    assert len(isolated_world.story_bible.timeline) == 2


def test_plan_plot_rejects_concurrent_runs(
    isolated_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_world(isolated_world)
    monkeypatch.setattr(plot_agent_module, "run_plot_agent", _stub_run_plot_agent("completed"))

    with get_job_manager().hold_story_bible_claim(label="Other plot run"):
        with pytest.raises(ToolException, match="already claimed"):
            plan_plot.func(
                briefing="Deepen Mira's wariness.",
                max_new_events=1,
                max_reinterpretation_runs=1,
            )


def test_unknown_pin_ids_surface_as_tool_errors(
    isolated_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_world(isolated_world)
    monkeypatch.setattr(plot_agent_module, "run_plot_agent", _stub_run_plot_agent("completed"))

    with pytest.raises(ToolException, match="Valid characters"):
        plan_plot.func(
            briefing="Deepen Mira's wariness.",
            max_new_events=1,
            max_reinterpretation_runs=1,
            pinned_intimacies=[
                PinnedIntimacy(character_id="char_invented", intimacy_id="intim_wary")
            ],
        )
    assert len(isolated_world.story_bible.timeline) == 2


# ------------------------------------------------------------------- validation


def test_plan_plot_validates_briefing_and_budget(isolated_world: World) -> None:
    _seed_world(isolated_world)

    with pytest.raises(ToolException, match="non-empty briefing"):
        plan_plot.func(briefing="  ", max_new_events=1, max_reinterpretation_runs=1)
    with pytest.raises(ToolException, match="zero or positive"):
        plan_plot.func(briefing="Goal.", max_new_events=-1, max_reinterpretation_runs=1)
    with pytest.raises(ToolException, match="zero budget"):
        plan_plot.func(briefing="Goal.", max_new_events=0, max_reinterpretation_runs=0)


def test_plan_plot_validates_scope_arguments(isolated_world: World) -> None:
    _seed_world(isolated_world)

    with pytest.raises(ToolException, match="requires both"):
        plan_plot.func(
            briefing="Rework the middle.",
            max_new_events=1,
            max_reinterpretation_runs=1,
            scope="revise_range",
            start_event_id="evt_gate",
        )
    with pytest.raises(ToolException, match="only apply to"):
        plan_plot.func(
            briefing="Continue the story.",
            max_new_events=1,
            max_reinterpretation_runs=1,
            start_event_id="evt_gate",
        )


def test_unknown_revise_range_ids_surface_as_tool_errors(
    isolated_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_world(isolated_world)
    monkeypatch.setattr(plot_agent_module, "run_plot_agent", _stub_run_plot_agent("completed"))

    with pytest.raises(ToolException, match="Valid events"):
        plan_plot.func(
            briefing="Rework the middle.",
            max_new_events=1,
            max_reinterpretation_runs=1,
            scope="revise_range",
            start_event_id="evt_gate",
            end_event_id="evt_invented",
        )


# ------------------------------------------------------------ toolset boundary


def test_chat_toolset_routes_event_writes_through_plan_plot() -> None:
    names = {tool.name for tool in WRITING_TOOLS}

    assert "plan_plot" in names
    assert names.isdisjoint(
        {
            "add_event",
            "update_event",
            "delete_event",
            "add_event_relation",
            "remove_event_relation",
        }
    )


def test_chat_prompt_describes_the_plan_plot_contract() -> None:
    assert "plan_plot" in DEFAULT_SYSTEM_PROMPT
    assert "revise_range" in DEFAULT_SYSTEM_PROMPT
    assert "pinned_intimacies" in DEFAULT_SYSTEM_PROMPT
