"""Enforced LangGraph workflow for per-character intimacy interpretation.

One character and one event in, a reviewed interpretation out. The graph does
not mutate the world; ``app/graphs/intimacy_interpretation.py`` persists the
result. See ``docs/architecture_agent_workflows.md``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from app.graphs.context import compose_story_bible_system_prompt
from app.graphs.workflow_state import IntimacyWorkflowState
from app.models.client import get_chat_model_for_node
from app.models.config import INTIMACY_ANALYZE_NODE_ID, INTIMACY_REVIEW_NODE_ID
from app.persistence.model_configs import get_model_config_repository
from app.world.evidence import format_threshold_distance
from app.world.models import (
    Character,
    Event,
    Intimacy,
    IntimacyEvidence,
    ReviewDecision,
    Signal,
    SignalReview,
    StoryBible,
    unique_slug,
)
from app.world.relations import chronological_order
from app.world.replay import derive_state_at, explain_intimacies_at
from app.world.store import get_world

PROMPT_VERSION = "intimacy-interpret-v1"
RECENT_SIGNAL_LIMIT = 5


class IntimacyWorkflowError(RuntimeError):
    """Raised when an interpretation step fails in a way that should abort the run."""


class EvidenceProposal(BaseModel):
    """A scored signal-intimacy relationship from analysis or review."""

    intimacy_id: str = ""
    direction: str = "supports"
    strength: int = 3
    rationale: str = ""
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    novelty: str = "novel"


class NewIntimacyProposal(BaseModel):
    text: str = ""
    rationale: str = ""


class RewordingProposal(BaseModel):
    intimacy_id: str = ""
    text: str = ""
    rationale: str = ""


class AnalysisOutput(BaseModel):
    interpretation: str = ""
    evidence: list[EvidenceProposal] = Field(default_factory=list)
    new_intimacies: list[NewIntimacyProposal] = Field(default_factory=list)
    rewordings: list[RewordingProposal] = Field(default_factory=list)


class ReviewOutput(BaseModel):
    decision: ReviewDecision = "approved"
    notes: str = ""
    interpretation: str = ""
    evidence: list[EvidenceProposal] = Field(default_factory=list)
    new_intimacies: list[NewIntimacyProposal] = Field(default_factory=list)
    rewordings: list[RewordingProposal] = Field(default_factory=list)


class ValidatedProposal(BaseModel):
    interpretation: str = ""
    evidence: list[IntimacyEvidence] = Field(default_factory=list)
    new_intimacies: list[Intimacy] = Field(default_factory=list)
    new_intimacy_rationales: dict[str, str] = Field(default_factory=dict)
    rewordings: list[RewordingProposal] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class InterpretationResult(BaseModel):
    """Reviewed interpretation for one character and one event. Not persisted."""

    event_id: str
    character_id: str
    interpretation: str = ""
    evidence: list[IntimacyEvidence] = Field(default_factory=list)
    new_intimacies: list[Intimacy] = Field(default_factory=list)
    new_intimacy_rationales: dict[str, str] = Field(default_factory=dict)
    rewordings: list[RewordingProposal] = Field(default_factory=list)
    review: SignalReview = Field(default_factory=SignalReview)
    validation_notes: list[str] = Field(default_factory=list)
    context: str = ""


_ANALYZE_SYSTEM_PROMPT = compose_story_bible_system_prompt(
    """You interpret one event for one character and return structured evidence.

The signal is this character's durable interpretation of the event: what it appears to
demonstrate, confirm, threaten, or call into question. It is not an event summary, not
the author's intended lesson, and not a momentary emotion.

Match the signal only to intimacies it meaningfully bears upon. Omit unrelated
intimacies. Mixed evidence for one intimacy is two (or more) separate entries, never a
single mixed score. Direction is supports or contradicts; strength is 1-5:
1 incidental, 2 noticeable, 3 meaningful, 4 pivotal, 5 identity-shaking.
Strength is not dramaticness or emotional intensity. Confidence is not strength.

Propose a new intimacy only when the interpretation is potentially persistent, distinct
from every existing intimacy, likely to affect future choices, and not better expressed
as evidence for or a small rewording of an existing intimacy. New intimacies are created
at minor; do not propose a rank. For evidence that belongs to a newly proposed intimacy,
set intimacy_id to the proposed text.

Rewording changes wording only, not rank. Existing signals on this event are hints, not
canon; derive your own interpretation."""
)

_REVIEW_SYSTEM_PROMPT = compose_story_bible_system_prompt(
    """You review one character's intimacy interpretation of one event.

Check for: event-summary language masquerading as a signal; interpretations that do not
fit the character; omitted existing intimacies; spurious or overly broad matches;
inflated strength ratings; temporary emotions presented as durable state; new intimacies
that duplicate existing ones; a proposed new intimacy that should instead reinforce or
reframe an existing one; rank-changing evidence based on repeated versions of the same
event; conclusions unsupported by the scene.

Approve, revise, or reject the proposal as a whole. When revising, return the corrected
signal, evidence, and proposals. When rejecting, explain why and return empty evidence
and proposals. Tag each evidence entry's novelty as novel or duplicate (near-repeat of
an earlier signal for the same intimacy). Do not invent rank changes; rank is derived
later. Existing signals on this event are hints, not canon."""
)


def build_intimacy_interpreter_graph(
    models: dict[str, BaseChatModel] | None = None,
    *,
    bible: StoryBible | None = None,
) -> CompiledStateGraph:
    """Build the enforced per-character intimacy interpretation graph.

    ``bible`` targets the run at an arbitrary Story Bible (for example a plot
    draft); the default reads the live world.
    """

    source = _bible_source(bible)
    graph = StateGraph(IntimacyWorkflowState)
    graph.add_node("assemble_context", _assemble_context_node(source))
    graph.add_node("analyze", _analyze_node(models))
    graph.add_node("validate", _validate_node(source))
    graph.add_node("review", _review_node(models, source))

    graph.add_edge(START, "assemble_context")
    graph.add_edge("assemble_context", "analyze")
    graph.add_edge("analyze", "validate")
    graph.add_edge("validate", "review")
    graph.add_edge("review", END)
    return graph.compile()


def run_intimacy_interpretation(
    event_id: str,
    character_id: str,
    *,
    models: dict[str, BaseChatModel] | None = None,
    bible: StoryBible | None = None,
) -> InterpretationResult:
    """Run interpretation for one character and one event. Does not mutate any bible.

    ``bible`` targets the run at an arbitrary Story Bible (for example a plot
    draft); the default is the live world.
    """

    target = bible if bible is not None else get_world().story_bible
    _require_event(target, event_id)
    _require_character(target, character_id)
    workflow = build_intimacy_interpreter_graph(models=models, bible=bible)
    final = workflow.invoke({"event_id": event_id, "character_id": character_id})
    payload = final.get("result")
    if not payload:
        msg = "Intimacy interpretation produced no result."
        raise IntimacyWorkflowError(msg)
    return InterpretationResult.model_validate(payload)


def assemble_intimacy_context(bible: StoryBible, event_id: str, character_id: str) -> str:
    """Deterministic context block for one character-event interpretation."""

    event = _require_event(bible, event_id)
    character = _require_character(bible, character_id)
    ordered = chronological_order(bible)
    index = next((i for i, item in enumerate(ordered) if item.id == event_id), 0)
    before = derive_state_at(bible, index).characters.get(character_id)
    ranks = explain_intimacies_at(bible, character_id, index)
    intimacies = (
        before.intimacies if before is not None else list(character.baseline_state.intimacies)
    )

    lines = [
        "# Event",
        f"Title: {event.title or 'Untitled'} [id: {event.id}]",
        f"Description: {event.description or '(none)'}",
        "",
        "# Character",
        f"Name: {character.identity.name or 'Unnamed'} [id: {character.id}]",
        f"Traits: {character.identity.traits or '-'}",
        f"Appearance: {character.identity.appearance or '-'}",
        f"Background: {character.identity.background or '-'}",
        f"Voice: {character.identity.voice or '-'}",
        "",
        "# Current intimacies (entering this event)",
    ]
    if not intimacies:
        lines.append("(none)")
    else:
        for intimacy in intimacies:
            extra = ""
            explanation = ranks.get(intimacy.id)
            if explanation is not None:
                extra = f" -- {format_threshold_distance(explanation)}"
            lines.append(f"- {intimacy.text} ({intimacy.strength}) [id: {intimacy.id}]{extra}")

    lines.extend(["", "# Recent related signals"])
    recent = _recent_signals(ordered[:index], character_id)
    if not recent:
        lines.append("(none)")
    else:
        lines.extend(recent)

    hint = _hint_signal(event, character_id)
    lines.extend(["", "# Existing signal on this event (hint, not canon)", hint])
    return "\n".join(lines)


def validate_analysis(
    bible: StoryBible,
    character_id: str,
    analysis: AnalysisOutput,
) -> ValidatedProposal:
    """Resolve intimacy ids, drop hallucinations, and mint ids for new proposals."""

    notes: list[str] = []
    existing_ids = set(bible.intimacy_ids(character_id))
    new_intimacies: list[Intimacy] = []
    rationales: dict[str, str] = {}
    extra_texts: dict[str, str] = {}

    for proposal in analysis.new_intimacies:
        text = proposal.text.strip()
        if not text:
            notes.append("Dropped empty new-intimacy proposal.")
            continue
        assigned = unique_slug("intim_", text, existing_ids)
        existing_ids.add(assigned)
        intimacy = Intimacy(id=assigned, text=text, strength="minor")
        new_intimacies.append(intimacy)
        rationales[assigned] = proposal.rationale
        extra_texts[assigned] = text

    extra_ids = list(extra_texts)
    evidence: list[IntimacyEvidence] = []
    for entry in analysis.evidence:
        resolved = _resolve_evidence_id(
            bible,
            character_id,
            entry.intimacy_id,
            extra_ids=extra_ids,
            extra_texts=extra_texts,
        )
        if resolved is None:
            notes.append(f"Dropped evidence for unknown intimacy_id '{entry.intimacy_id}'.")
            continue
        direction = entry.direction if entry.direction in ("supports", "contradicts") else ""
        if not direction:
            notes.append(f"Dropped evidence for '{resolved}' with invalid direction.")
            continue
        strength = entry.strength if entry.strength in (1, 2, 3, 4, 5) else 0
        if not strength:
            notes.append(f"Dropped evidence for '{resolved}' with invalid strength.")
            continue
        novelty = entry.novelty if entry.novelty in ("novel", "duplicate") else "novel"
        evidence.append(
            IntimacyEvidence(
                intimacy_id=resolved,
                direction=direction,
                strength=strength,
                rationale=entry.rationale,
                novelty=novelty,
                confidence=entry.confidence,
            )
        )

    rewordings: list[RewordingProposal] = []
    for proposal in analysis.rewordings:
        resolved = bible.resolve_intimacy_id(proposal.intimacy_id, character_id=character_id)
        if resolved is None or not proposal.text.strip():
            notes.append(
                f"Dropped rewording for unknown or blank intimacy '{proposal.intimacy_id}'."
            )
            continue
        rewordings.append(
            RewordingProposal(
                intimacy_id=resolved,
                text=proposal.text.strip(),
                rationale=proposal.rationale,
            )
        )

    return ValidatedProposal(
        interpretation=analysis.interpretation.strip(),
        evidence=evidence,
        new_intimacies=new_intimacies,
        new_intimacy_rationales=rationales,
        rewordings=rewordings,
        notes=notes,
    )


def _bible_source(bible: StoryBible | None) -> Callable[[], StoryBible]:
    """Return a per-node accessor for the target bible (live world by default)."""

    if bible is None:
        return lambda: get_world().story_bible
    return lambda: bible


def _assemble_context_node(source: Callable[[], StoryBible]) -> Any:
    def node(state: IntimacyWorkflowState) -> dict[str, Any]:
        return {
            "context": assemble_intimacy_context(source(), state["event_id"], state["character_id"])
        }

    return node


def _analyze_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: IntimacyWorkflowState) -> dict[str, Any]:
        prompt = (
            "Interpret this event for this character. Return a signal, scored evidence "
            "entries, and any new-intimacy or rewording proposals.\n\n"
            f"{state.get('context', '')}"
        )
        result = _structured_invoke(
            INTIMACY_ANALYZE_NODE_ID,
            models,
            AnalysisOutput,
            prompt,
            system=_ANALYZE_SYSTEM_PROMPT,
        )
        return {"analysis": result.model_dump()}

    return node


def _validate_node(source: Callable[[], StoryBible]) -> Any:
    def node(state: IntimacyWorkflowState) -> dict[str, Any]:
        analysis = AnalysisOutput.model_validate(state.get("analysis") or {})
        validated = validate_analysis(source(), state["character_id"], analysis)
        return {"validated": validated.model_dump()}

    return node


def _review_node(models: dict[str, BaseChatModel] | None, source: Callable[[], StoryBible]) -> Any:
    def node(state: IntimacyWorkflowState) -> dict[str, Any]:
        validated = ValidatedProposal.model_validate(state.get("validated") or {})
        prompt = (
            "Review this character-event interpretation. Approve, revise, or reject. "
            "Tag novelty on every evidence entry you keep.\n\n"
            f"{state.get('context', '')}\n\n"
            "# Proposed interpretation\n"
            f"{validated.interpretation or '(empty)'}\n\n"
            "# Proposed evidence\n"
            f"{_format_evidence(validated.evidence)}\n\n"
            "# Proposed new intimacies\n"
            f"{_format_new_intimacies(validated)}\n\n"
            "# Proposed rewordings\n"
            f"{_format_rewordings(validated.rewordings)}"
        )
        review = _structured_invoke(
            INTIMACY_REVIEW_NODE_ID,
            models,
            ReviewOutput,
            prompt,
            system=_REVIEW_SYSTEM_PROMPT,
        )
        result = _result_from_review(
            source(),
            state["event_id"],
            state["character_id"],
            state.get("context", ""),
            validated,
            review,
        )
        return {"review": review.model_dump(), "result": result.model_dump()}

    return node


def _result_from_review(
    bible: StoryBible,
    event_id: str,
    character_id: str,
    context: str,
    validated: ValidatedProposal,
    review: ReviewOutput,
) -> InterpretationResult:
    analysis_model = _resolved_model_name(INTIMACY_ANALYZE_NODE_ID)
    review_model = _resolved_model_name(INTIMACY_REVIEW_NODE_ID)
    meta = SignalReview(
        decision=review.decision,
        notes=review.notes,
        analysis_model=analysis_model,
        review_model=review_model,
        prompt_version=PROMPT_VERSION,
    )
    if review.decision == "rejected":
        return InterpretationResult(
            event_id=event_id,
            character_id=character_id,
            interpretation=review.interpretation.strip() or validated.interpretation,
            review=meta,
            validation_notes=list(validated.notes),
            context=context,
        )

    if review.decision == "revised":
        source = AnalysisOutput(
            interpretation=review.interpretation or validated.interpretation,
            evidence=review.evidence,
            new_intimacies=review.new_intimacies,
            rewordings=review.rewordings,
        )
    else:
        source = AnalysisOutput(
            interpretation=review.interpretation or validated.interpretation,
            evidence=review.evidence
            or [
                EvidenceProposal(
                    intimacy_id=entry.intimacy_id,
                    direction=entry.direction,
                    strength=entry.strength,
                    rationale=entry.rationale,
                    confidence=entry.confidence,
                    novelty=entry.novelty,
                )
                for entry in validated.evidence
            ],
            new_intimacies=review.new_intimacies
            or [
                NewIntimacyProposal(
                    text=item.text,
                    rationale=validated.new_intimacy_rationales.get(item.id, ""),
                )
                for item in validated.new_intimacies
            ],
            rewordings=review.rewordings or validated.rewordings,
        )
    rerun = validate_analysis(bible, character_id, source)
    notes = list(validated.notes) + list(rerun.notes)
    return InterpretationResult(
        event_id=event_id,
        character_id=character_id,
        interpretation=rerun.interpretation,
        evidence=rerun.evidence,
        new_intimacies=rerun.new_intimacies,
        new_intimacy_rationales=rerun.new_intimacy_rationales,
        rewordings=rerun.rewordings,
        review=meta,
        validation_notes=notes,
        context=context,
    )


def _structured_invoke(
    node_id: str,
    models: dict[str, BaseChatModel] | None,
    schema: type[BaseModel],
    prompt: str,
    *,
    system: str,
) -> BaseModel:
    model = _resolve_model(node_id, models).with_structured_output(schema)
    return model.invoke([SystemMessage(content=system), HumanMessage(content=prompt)])


def _resolve_model(
    node_id: str,
    models: dict[str, BaseChatModel] | None,
) -> BaseChatModel:
    if models is not None and node_id in models:
        return models[node_id]
    return get_chat_model_for_node(node_id, streaming=False)


def _resolved_model_name(node_id: str) -> str:
    return get_model_config_repository().resolve_model_config(node_id).model


def _require_event(bible: StoryBible, event_id: str) -> Event:
    event = bible.get_event(event_id)
    if event is None:
        msg = f"Event not found: {event_id}"
        raise ValueError(msg)
    return event


def _require_character(bible: StoryBible, character_id: str) -> Character:
    character = bible.get_character(character_id)
    if character is None:
        msg = f"Character not found: {character_id}"
        raise ValueError(msg)
    return character


def _recent_signals(prior_events: list[Event], character_id: str) -> list[str]:
    blocks: list[str] = []
    for event in reversed(prior_events):
        signals = [item for item in event.signals if item.character_id == character_id]
        if not signals:
            continue
        for signal in signals:
            blocks.append(_format_signal_block(event, signal))
        if len(blocks) >= RECENT_SIGNAL_LIMIT:
            break
    blocks.reverse()
    return blocks[:RECENT_SIGNAL_LIMIT]


def _hint_signal(event: Event, character_id: str) -> str:
    signals = [item for item in event.signals if item.character_id == character_id]
    if not signals:
        return "(none)"
    return "\n".join(_format_signal_block(event, signal, hint=True) for signal in signals)


def _format_signal_block(event: Event, signal: Signal, *, hint: bool = False) -> str:
    prefix = "Hint signal" if hint else "Signal"
    lines = [
        f"## {event.title or 'Untitled'} [{event.id}]",
        f"{prefix}: {signal.interpretation or '-'}",
    ]
    if signal.evidence:
        lines.append("Evidence:")
        lines.extend(
            f"- {entry.direction} {entry.intimacy_id} "
            f"(strength {entry.strength}, {entry.novelty}): {entry.rationale or '-'}"
            for entry in signal.evidence
        )
    return "\n".join(lines)


def _format_evidence(entries: list[IntimacyEvidence]) -> str:
    if not entries:
        return "(none)"
    return "\n".join(
        f"- {entry.direction} {entry.intimacy_id} "
        f"(strength {entry.strength}, {entry.novelty}): {entry.rationale or '-'}"
        for entry in entries
    )


def _format_new_intimacies(validated: ValidatedProposal) -> str:
    if not validated.new_intimacies:
        return "(none)"
    return "\n".join(
        f"- {item.text} [id: {item.id}] "
        f"({validated.new_intimacy_rationales.get(item.id, '') or 'no rationale'})"
        for item in validated.new_intimacies
    )


def _format_rewordings(rewordings: list[RewordingProposal]) -> str:
    if not rewordings:
        return "(none)"
    return "\n".join(
        f"- {item.intimacy_id} -> {item.text} ({item.rationale or 'no rationale'})"
        for item in rewordings
    )


def _resolve_evidence_id(
    bible: StoryBible,
    character_id: str,
    raw_id: str,
    *,
    extra_ids: list[str],
    extra_texts: dict[str, str],
) -> str | None:
    if not raw_id.strip():
        return None
    match = bible.resolve_intimacy_id(raw_id, character_id=character_id, extra_ids=extra_ids)
    if match is not None:
        return match
    normalized = raw_id.strip().lower()
    for proposed_id, text in extra_texts.items():
        if text.strip().lower() == normalized:
            return proposed_id
    return None
