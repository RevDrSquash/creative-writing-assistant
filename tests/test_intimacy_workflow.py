"""Unit tests for the per-character intimacy interpretation workflow."""

from __future__ import annotations

from typing import Any

import pytest

from app.graphs.context import STORY_BIBLE_PRIMER
from app.graphs.intimacy_workflow import (
    RECENT_SIGNAL_LIMIT,
    AnalysisOutput,
    EvidenceProposal,
    InterpretationResult,
    NewIntimacyProposal,
    ReviewOutput,
    RewordingProposal,
    assemble_intimacy_context,
    build_intimacy_interpreter_graph,
    run_intimacy_interpretation,
    validate_analysis,
)
from app.graphs.registry import WORKFLOWS, get_workflow
from app.graphs.scene_workflow import structured_fake_model
from app.models.config import (
    GRAPH_NODES,
    INTIMACY_ANALYZE_NODE_ID,
    INTIMACY_REVIEW_NODE_ID,
    JUDGMENT_CONFIG_ID,
)
from app.tools.story_bible import add_event, upsert_character
from app.world.models import (
    Event,
    EventRelation,
    Intimacy,
    IntimacyEvidence,
    Signal,
    World,
)


def _seed_character_and_event(world: World) -> tuple[str, str, str]:
    upsert_character.func(
        name="Mira",
        intimacies=[Intimacy(id="intim_wary", text="Wary of outsiders", strength="minor")],
    )
    character = world.story_bible.characters[0]
    add_event.func(
        "The gate",
        description="A stranger asks to be let in.",
        signals=[
            Signal(
                character_id=character.id,
                interpretation="Maybe this one is different.",
            )
        ],
    )
    event = world.story_bible.timeline[0]
    return character.id, event.id, "intim_wary"


def _analysis(
    intimacy_id: str = "intim_wary",
    *,
    strength: int = 3,
    new_intimacies: list[NewIntimacyProposal] | None = None,
    rewordings: list[RewordingProposal] | None = None,
) -> AnalysisOutput:
    return AnalysisOutput(
        interpretation="This stranger may be useful, but I should keep my distance.",
        evidence=[
            EvidenceProposal(
                intimacy_id=intimacy_id,
                direction="supports",
                strength=strength,
                rationale="Letting an unknown person close still feels like a risk.",
            )
        ],
        new_intimacies=new_intimacies or [],
        rewordings=rewordings or [],
    )


def _review(
    decision: str = "approved",
    *,
    intimacy_id: str = "intim_wary",
    strength: int = 3,
    novelty: str = "novel",
    interpretation: str = "",
    notes: str = "Looks sound.",
    evidence: list[EvidenceProposal] | None = None,
    new_intimacies: list[NewIntimacyProposal] | None = None,
    rewordings: list[RewordingProposal] | None = None,
) -> ReviewOutput:
    if evidence is None and decision != "rejected":
        evidence = [
            EvidenceProposal(
                intimacy_id=intimacy_id,
                direction="supports",
                strength=strength,
                rationale="Letting an unknown person close still feels like a risk.",
                novelty=novelty,
            )
        ]
    return ReviewOutput(
        decision=decision,  # type: ignore[arg-type]
        notes=notes,
        interpretation=interpretation,
        evidence=evidence or [],
        new_intimacies=new_intimacies or [],
        rewordings=rewordings or [],
    )


def _models(analysis: AnalysisOutput, review: ReviewOutput) -> dict[str, Any]:
    return {
        INTIMACY_ANALYZE_NODE_ID: structured_fake_model(analysis),
        INTIMACY_REVIEW_NODE_ID: structured_fake_model(review),
    }


def test_graph_enforces_analyze_then_validate_then_review() -> None:
    graph = build_intimacy_interpreter_graph(models=_models(_analysis(), _review()))
    pairs = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert ("__start__", "assemble_context") in pairs
    assert ("assemble_context", "analyze") in pairs
    assert ("analyze", "validate") in pairs
    assert ("validate", "review") in pairs
    assert ("review", "__end__") in pairs


def test_workflow_is_registered() -> None:
    assert "interpret_intimacy" in WORKFLOWS
    built = get_workflow("interpret_intimacy", models=_models(_analysis(), _review()))
    assert built is not None


def test_run_does_not_mutate_world(isolated_world: World) -> None:
    character_id, event_id, intimacy_id = _seed_character_and_event(isolated_world)
    before = isolated_world.model_dump(mode="json")

    result = run_intimacy_interpretation(
        event_id,
        character_id,
        models=_models(_analysis(intimacy_id), _review(intimacy_id=intimacy_id)),
    )

    assert isinstance(result, InterpretationResult)
    assert result.review.decision == "approved"
    assert result.evidence[0].intimacy_id == intimacy_id
    assert isolated_world.model_dump(mode="json") == before


def test_context_treats_existing_signal_as_hint(isolated_world: World) -> None:
    character_id, event_id, _intimacy_id = _seed_character_and_event(isolated_world)
    context = assemble_intimacy_context(isolated_world.story_bible, event_id, character_id)

    assert "hint, not canon" in context.lower()
    assert "Maybe this one is different." in context
    assert "Wary of outsiders" in context
    assert STORY_BIBLE_PRIMER not in context


def test_context_includes_recent_prior_signals(isolated_world: World) -> None:
    character_id, first_id, intimacy_id = _seed_character_and_event(isolated_world)
    later = Event(
        id="event_later",
        title="Later",
        description="The stranger stays.",
    )
    isolated_world.story_bible.timeline.append(later)
    isolated_world.story_bible.event_relations.append(
        EventRelation(kind="follows", source_id=later.id, target_id=first_id)
    )
    isolated_world.story_bible.timeline[0].signals[0].evidence.append(
        IntimacyEvidence(intimacy_id=intimacy_id, direction="supports", strength=2)
    )

    context = assemble_intimacy_context(isolated_world.story_bible, later.id, character_id)
    assert "Recent related signals" in context
    assert "The gate" in context
    assert f"[id: {first_id}]" in context or first_id in context


def test_validate_drops_hallucinated_intimacy_id(isolated_world: World) -> None:
    character_id, _event_id, _intimacy_id = _seed_character_and_event(isolated_world)
    validated = validate_analysis(
        isolated_world.story_bible,
        character_id,
        _analysis("intim_does_not_exist"),
    )

    assert validated.evidence == []
    assert any("intim_does_not_exist" in note for note in validated.notes)


def test_validate_resolves_drifted_intimacy_id(isolated_world: World) -> None:
    upsert_character.func(
        name="Mira",
        intimacies=[
            Intimacy(id="intim_wary_of_outsiders", text="Wary of outsiders", strength="minor")
        ],
    )
    character_id = isolated_world.story_bible.characters[0].id
    validated = validate_analysis(
        isolated_world.story_bible,
        character_id,
        _analysis("intim_wary"),
    )

    assert [entry.intimacy_id for entry in validated.evidence] == ["intim_wary_of_outsiders"]


def test_validate_assigns_slug_and_accepts_text_keyed_new_evidence(
    isolated_world: World,
) -> None:
    character_id, _event_id, _intimacy_id = _seed_character_and_event(isolated_world)
    analysis = AnalysisOutput(
        interpretation="I owe this stranger something.",
        evidence=[
            EvidenceProposal(
                intimacy_id="Owes Kael a debt",
                direction="supports",
                strength=3,
                rationale="He opened the gate for us.",
            )
        ],
        new_intimacies=[
            NewIntimacyProposal(text="Owes Kael a debt", rationale="A favor was accepted.")
        ],
    )

    validated = validate_analysis(isolated_world.story_bible, character_id, analysis)

    assert len(validated.new_intimacies) == 1
    assert validated.new_intimacies[0].id.startswith("intim_")
    assert validated.new_intimacies[0].strength == "minor"
    assert validated.evidence[0].intimacy_id == validated.new_intimacies[0].id


def test_review_approve_keeps_evidence(isolated_world: World) -> None:
    character_id, event_id, intimacy_id = _seed_character_and_event(isolated_world)
    result = run_intimacy_interpretation(
        event_id,
        character_id,
        models=_models(_analysis(intimacy_id), _review(intimacy_id=intimacy_id, novelty="novel")),
    )

    assert result.review.decision == "approved"
    assert result.evidence[0].novelty == "novel"
    assert result.interpretation


def test_review_revise_replaces_strength(isolated_world: World) -> None:
    character_id, event_id, intimacy_id = _seed_character_and_event(isolated_world)
    result = run_intimacy_interpretation(
        event_id,
        character_id,
        models=_models(
            _analysis(intimacy_id, strength=5),
            _review(
                "revised",
                intimacy_id=intimacy_id,
                strength=2,
                notes="Strength was inflated.",
                interpretation="Useful, not identity-shaking.",
            ),
        ),
    )

    assert result.review.decision == "revised"
    assert result.evidence[0].strength == 2
    assert result.interpretation == "Useful, not identity-shaking."


def test_review_reject_clears_evidence(isolated_world: World) -> None:
    character_id, event_id, intimacy_id = _seed_character_and_event(isolated_world)
    result = run_intimacy_interpretation(
        event_id,
        character_id,
        models=_models(
            _analysis(intimacy_id),
            _review("rejected", notes="Momentary fear, not a durable belief."),
        ),
    )

    assert result.review.decision == "rejected"
    assert result.evidence == []
    assert result.new_intimacies == []
    assert result.rewordings == []


def test_analyze_prompt_includes_hint_and_primer(isolated_world: World) -> None:
    character_id, event_id, intimacy_id = _seed_character_and_event(isolated_world)
    captured: dict[str, Any] = {}

    class _Capture:
        def with_structured_output(self, schema: type, **kwargs: Any) -> Any:
            class _Runnable:
                def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> AnalysisOutput:
                    captured["messages"] = input
                    return _analysis(intimacy_id)

            return _Runnable()

    result = run_intimacy_interpretation(
        event_id,
        character_id,
        models={
            INTIMACY_ANALYZE_NODE_ID: _Capture(),  # type: ignore[dict-item]
            INTIMACY_REVIEW_NODE_ID: structured_fake_model(_review(intimacy_id=intimacy_id)),
        },
    )

    system = captured["messages"][0].content
    human = captured["messages"][1].content
    assert STORY_BIBLE_PRIMER in system
    assert "mixed evidence" in system.lower() or "separate entries" in system.lower()
    assert "hint, not canon" in human.lower()
    assert result.evidence


def test_run_targets_passed_bible_and_leaves_world_untouched(isolated_world: World) -> None:
    character_id, event_id, intimacy_id = _seed_character_and_event(isolated_world)
    draft = isolated_world.story_bible.model_copy(deep=True)
    draft.timeline.append(
        Event(
            id="event_draft_only",
            title="Draft-only event",
            description="Exists only in the draft copy.",
            signals=[Signal(character_id=character_id, interpretation="A new hint.")],
        )
    )
    draft.event_relations.append(
        EventRelation(kind="follows", source_id="event_draft_only", target_id=event_id)
    )
    before = isolated_world.model_dump(mode="json")
    models = _models(_analysis(intimacy_id), _review(intimacy_id=intimacy_id))

    result = run_intimacy_interpretation(
        "event_draft_only",
        character_id,
        models=models,
        bible=draft,
    )

    assert result.event_id == "event_draft_only"
    assert result.evidence[0].intimacy_id == intimacy_id
    assert "Draft-only event" in result.context
    assert isolated_world.model_dump(mode="json") == before

    # The live-world default still rejects the draft-only event.
    with pytest.raises(ValueError, match="event_draft_only"):
        run_intimacy_interpretation("event_draft_only", character_id, models=models)


def test_unknown_ids_raise(isolated_world: World) -> None:
    character_id, event_id, intimacy_id = _seed_character_and_event(isolated_world)
    models = _models(_analysis(intimacy_id), _review(intimacy_id=intimacy_id))

    with pytest.raises(ValueError, match="event_missing"):
        run_intimacy_interpretation("event_missing", character_id, models=models)
    with pytest.raises(ValueError, match="char_missing"):
        run_intimacy_interpretation(event_id, "char_missing", models=models)


def test_recent_signal_limit_constant() -> None:
    assert RECENT_SIGNAL_LIMIT == 5


def test_graph_nodes_register_intimacy_workflow_nodes() -> None:
    node_map = {node.node_id: node for node in GRAPH_NODES}
    assert node_map[INTIMACY_ANALYZE_NODE_ID].default_config_id == JUDGMENT_CONFIG_ID
    assert node_map[INTIMACY_ANALYZE_NODE_ID].label == "Intimacy: Analyze"
    assert node_map[INTIMACY_REVIEW_NODE_ID].default_config_id == JUDGMENT_CONFIG_ID
    assert node_map[INTIMACY_REVIEW_NODE_ID].label == "Intimacy: Review"
