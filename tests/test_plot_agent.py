"""Tests for the plot sub-agent loop: one-write-per-message middleware,
per-run tool binding, and the structured PlotPlanResult contract."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.graphs.intimacy_workflow import AnalysisOutput, EvidenceProposal, ReviewOutput
from app.graphs.plot_agent import (
    PLOT_AGENT_SYSTEM_PROMPT,
    build_plot_agent,
    run_plot_agent,
)
from app.graphs.registry import WORKFLOWS, get_workflow
from app.graphs.scene_workflow import structured_fake_model
from app.graphs.single_write_middleware import SingleWritePerMessageMiddleware
from app.models.config import INTIMACY_ANALYZE_NODE_ID, INTIMACY_REVIEW_NODE_ID
from app.tools.plot_draft import (
    DRAFT_WRITE_TOOL_NAMES,
    PlotBudget,
    PlotDraftToolset,
    create_plot_draft_toolset,
)
from app.world.draft import PlotDraft
from app.world.models import (
    Character,
    CharacterBaselineState,
    CharacterIdentity,
    Event,
    EventRelation,
    Intimacy,
    IntimacyEvidence,
    Signal,
    StoryBible,
    World,
)


class ToolAwareFakeChatModel(GenericFakeChatModel):
    def bind_tools(
        self,
        tools: Any,
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> ToolAwareFakeChatModel:
        return self


class RecordingFakeChatModel(ToolAwareFakeChatModel):
    recorded_messages: ClassVar[list[BaseMessage]] = []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Any:
        type(self).recorded_messages = list(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _mira_signal() -> Signal:
    return Signal(
        character_id="char_mira",
        interpretation="A hint",
        evidence=[IntimacyEvidence(intimacy_id="intim_wary", direction="supports", strength=2)],
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


def _toolset(draft: PlotDraft) -> PlotDraftToolset:
    toolset = create_plot_draft_toolset(
        draft,
        PlotBudget(max_new_events=5, max_reinterpretation_runs=5),
        models=_models(),
    )
    toolset.tool("plan_rank_targets").func(
        targets=[],
        note="This middleware test does not intend rank movement.",
    )
    return toolset


_CALL_COUNTER = iter(range(10_000))


def _tool_call_message(*calls: tuple[str, dict[str, Any]]) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": args, "id": f"call-{next(_CALL_COUNTER)}", "type": "tool_call"}
            for name, args in calls
        ],
    )


def _add_alley_args() -> dict[str, Any]:
    return {
        "title": "The alley",
        "relations": [{"kind": "follows", "event_id": "evt_watch"}],
        "signals": [{"character_id": "char_mira", "interpretation": "Trouble follows me."}],
    }


def _tool_messages(result: dict[str, Any]) -> list[ToolMessage]:
    return [message for message in result["messages"] if isinstance(message, ToolMessage)]


# --------------------------------------------- one-write-per-message middleware


def test_batched_writes_execute_first_and_reject_rest(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                _tool_call_message(
                    ("add_draft_event", _add_alley_args()),
                    ("add_draft_event", {"title": "The chase"}),
                    ("read_draft_timeline", {}),
                ),
                AIMessage(content="Understood."),
            ]
        )
    )
    agent = build_plot_agent(toolset, model=fake_model)

    result = agent.invoke({"messages": [HumanMessage(content="Draft the arc.")]})

    titles = [event.title for event in draft.bible.timeline]
    assert "The alley" in titles
    assert "The chase" not in titles
    by_name: dict[str, list[ToolMessage]] = {}
    for message in _tool_messages(result):
        by_name.setdefault(message.name, []).append(message)
    add_messages = by_name["add_draft_event"]
    assert [message.status for message in add_messages] == ["success", "error"]
    assert "only one draft-write tool call is allowed per message" in add_messages[1].content
    assert by_name["read_draft_timeline"][0].status == "success"


async def test_batched_writes_rejected_on_async_path(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                _tool_call_message(
                    ("add_draft_event", _add_alley_args()),
                    ("delete_draft_event", {"event_id": "evt_watch"}),
                ),
                AIMessage(content="Understood."),
            ]
        )
    )
    agent = build_plot_agent(toolset, model=fake_model)

    result = await agent.ainvoke({"messages": [HumanMessage(content="Draft the arc.")]})

    assert draft.bible.get_event("evt_watch") is not None
    assert "The alley" in [event.title for event in draft.bible.timeline]
    statuses = {message.name: message.status for message in _tool_messages(result)}
    assert statuses["add_draft_event"] == "success"
    assert statuses["delete_draft_event"] == "error"


def test_single_write_batched_with_reads_is_allowed(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                _tool_call_message(
                    ("read_draft_timeline", {}),
                    ("add_draft_event", _add_alley_args()),
                    ("read_draft_state", {}),
                ),
                AIMessage(content="Understood."),
            ]
        )
    )
    agent = build_plot_agent(toolset, model=fake_model)

    result = agent.invoke({"messages": [HumanMessage(content="Draft the arc.")]})

    assert "The alley" in [event.title for event in draft.bible.timeline]
    assert all(message.status != "error" for message in _tool_messages(result))


def test_middleware_never_rejects_solo_or_unlocatable_calls() -> None:
    middleware = SingleWritePerMessageMiddleware(DRAFT_WRITE_TOOL_NAMES)
    message = _tool_call_message(
        ("add_draft_event", {}),
        ("finish_plot", {}),
    )
    first_id = message.tool_calls[0]["id"]
    second_id = message.tool_calls[1]["id"]

    def request(call_id: str, name: str, messages: list[BaseMessage]) -> SimpleNamespace:
        return SimpleNamespace(
            tool_call={"name": name, "args": {}, "id": call_id},
            state={"messages": messages},
        )

    # Read tools are never rejected, wherever they sit.
    assert middleware._rejection(request("x", "read_draft_timeline", [message])) is None
    # A write whose emitting message cannot be located is a solo batch.
    assert middleware._rejection(request("orphan", "add_draft_event", [])) is None
    # The first write in a batch runs; later writes are rejected.
    assert middleware._rejection(request(first_id, "add_draft_event", [message])) is None
    rejection = middleware._rejection(request(second_id, "finish_plot", [message]))
    assert isinstance(rejection, ToolMessage)
    assert rejection.status == "error"
    assert rejection.tool_call_id == second_id


# ------------------------------------------------------------- run_plot_agent


def test_run_plot_agent_happy_path_returns_completed_result(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                _tool_call_message(
                    (
                        "plan_rank_targets",
                        {"targets": [], "note": "No rank movement is intended."},
                    )
                ),
                _tool_call_message(("add_draft_event", _add_alley_args())),
                _tool_call_message(("finish_plot", {"summary": "Mira's wariness deepens."})),
                AIMessage(content="Done."),
            ]
        )
    )

    result = run_plot_agent(
        draft,
        PlotBudget(max_new_events=3, max_reinterpretation_runs=3),
        "Deepen Mira's wariness by one event.",
        model=fake_model,
        models=_models(),
    )

    assert result.status == "completed"
    assert result.summary == "Mira's wariness deepens."
    assert len(result.drafted_event_ids) == 1
    drafted = draft.bible.get_event(result.drafted_event_ids[0])
    assert drafted is not None
    assert drafted.title == "The alley"
    assert result.new_events_used == 1
    assert result.new_events_budget == 3


def test_run_plot_agent_bail_out_returns_measured_gap_report(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                _tool_call_message(
                    (
                        "bail_out",
                        {
                            "reason": "overconstrained",
                            "explanation": "The target conflicts with a preservation pin.",
                            "gaps": [
                                {
                                    "character_id": "char_mira",
                                    "intimacy_id": "intim_wary",
                                    "target": "major by the finale",
                                    "conflict": "pin on intim_wary",
                                }
                            ],
                        },
                    )
                ),
                AIMessage(content="Reported."),
            ]
        )
    )

    result = run_plot_agent(
        draft,
        PlotBudget(max_new_events=1, max_reinterpretation_runs=1),
        "Reach major wariness without touching intim_wary.",
        model=fake_model,
        models=_models(),
    )

    assert result.status == "infeasible"
    assert result.reason == "overconstrained"
    assert len(result.gap_report) == 1
    gap = result.gap_report[0]
    assert gap.character_name == "Mira"
    assert gap.intimacy_id == "intim_wary"
    assert gap.conflict == "pin on intim_wary"
    assert gap.current_rank
    assert gap.threshold_distance


def test_run_plot_agent_nudges_once_then_accepts_finish(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                AIMessage(content="I believe the draft already satisfies the briefing."),
                _tool_call_message(
                    (
                        "plan_rank_targets",
                        {"targets": [], "note": "No rank movement is needed."},
                    )
                ),
                _tool_call_message(("finish_plot", {"summary": "Nothing needed changing."})),
                AIMessage(content="Done."),
            ]
        )
    )

    result = run_plot_agent(
        draft,
        PlotBudget(max_new_events=1, max_reinterpretation_runs=1),
        "Verify the arc.",
        model=fake_model,
        models=_models(),
    )

    assert result.status == "completed"
    assert result.summary == "Nothing needed changing."


def test_run_plot_agent_forces_bail_out_without_terminal_call(isolated_world: World) -> None:
    draft = PlotDraft(_bible())
    fake_model = ToolAwareFakeChatModel(
        messages=iter(
            [
                AIMessage(content="All good."),
                AIMessage(content="Still all good."),
            ]
        )
    )

    result = run_plot_agent(
        draft,
        PlotBudget(max_new_events=1, max_reinterpretation_runs=1),
        "Verify the arc.",
        model=fake_model,
        models=_models(),
    )

    assert result.status == "infeasible"
    assert result.reason == "budget"
    assert "without calling finish_plot or bail_out" in result.summary


def test_run_plot_agent_forces_bail_out_on_step_limit(isolated_world: World) -> None:
    draft = PlotDraft(_bible())

    def endless_reads():
        while True:
            yield _tool_call_message(("read_draft_timeline", {}))

    fake_model = ToolAwareFakeChatModel(messages=endless_reads())

    result = run_plot_agent(
        draft,
        PlotBudget(max_new_events=1, max_reinterpretation_runs=1),
        "Verify the arc.",
        model=fake_model,
        models=_models(),
        recursion_limit=6,
    )

    assert result.status == "infeasible"
    assert result.reason == "budget"
    assert "step limit 6" in result.summary


# ------------------------------------------------------- registration and prompt


def test_plan_plot_is_registered_with_per_run_tool_binding(isolated_world: World) -> None:
    assert "plan_plot" in WORKFLOWS

    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    fake_model = ToolAwareFakeChatModel(messages=iter([AIMessage(content="Ready.")]))

    agent = get_workflow("plan_plot", toolset=toolset, model=fake_model)
    result = agent.invoke({"messages": [HumanMessage(content="Hello")]})

    assert result["messages"][-1].content == "Ready."


def test_build_plot_agent_appends_guidance_to_system_prompt(isolated_world: World) -> None:
    RecordingFakeChatModel.recorded_messages = []
    draft = PlotDraft(_bible())
    toolset = _toolset(draft)
    fake_model = RecordingFakeChatModel(messages=iter([AIMessage(content="ok")]))
    agent = build_plot_agent(
        toolset, model=fake_model, guidance="Do not change Mira's relationship to the war."
    )

    agent.invoke({"messages": [HumanMessage(content="Hi")]})

    recorded = RecordingFakeChatModel.recorded_messages
    assert isinstance(recorded[0], SystemMessage)
    assert recorded[0].content.startswith(PLOT_AGENT_SYSTEM_PROMPT)
    assert "Do not change Mira's relationship to the war." in recorded[0].content


def test_plot_agent_prompt_requires_rank_target_planning() -> None:
    assert "Plan rank movement first" in PLOT_AGENT_SYSTEM_PROMPT
    assert "plan_rank_targets" in PLOT_AGENT_SYSTEM_PROMPT
    assert "unmet_targets_note" in PLOT_AGENT_SYSTEM_PROMPT
