"""Enforced LangGraph workflow for generating scene content from a blueprint."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from app.graphs.state import PlanReviseAgentState, WritingAgentState
from app.graphs.workflow_state import SceneWorkflowState
from app.models.client import get_chat_model_for_node
from app.models.config import (
    SCENE_DRAFT_NODE_ID,
    SCENE_GATHER_NODE_ID,
    SCENE_OUTLINE_NODE_ID,
    SCENE_OUTLINE_REVIEW_NODE_ID,
    SCENE_OUTLINE_REVISE_NODE_ID,
    SCENE_PROSE_REVIEW_NODE_ID,
    SCENE_PROSE_REVISE_NODE_ID,
    SCENE_STANCES_NODE_ID,
    SCENE_SUMMARY_NODE_ID,
)
from app.tools import READ_ONLY_WRITING_TOOLS
from app.tools.scene_generated import edit_outline, edit_prose, update_stance
from app.tools.story_bible import read_character, read_event, read_world_fact
from app.world.models import SceneCharacterStance
from app.world.scene import (
    get_scene_text,
    set_scene_metadata,
    set_scene_text,
    update_scene_generated,
)
from app.world.scene_context import PREVIOUS_SCENE_PROSE_CAP
from app.world.store import get_world

MAX_DOSSIER_SCENES = 3


class SceneWorkflowError(RuntimeError):
    """Raised when a scene-writing workflow step fails in a way that should abort the job."""


_GATHER_SYSTEM_PROMPT = """You gather Story Bible and scene context for a prose drafter.
Use read-only tools to explore characters, events, world facts, and related/next scenes
(the continuity block may give only summaries — call read_scene when full prose is needed).
Then select what the drafter needs by returning ids only — do not restate or paraphrase
entry content. Use notes only for short observations, warnings, or emphasis that no
entry captures. Read-tool output already labels entities with [id: ...]; prefer those ids."""

_DRAFT_SYSTEM_PROMPT = """You are drafting scene prose for a fiction project.
Output only the scene body prose — no preamble, commentary, or title.
The scene title is stored and displayed outside the prose; do not open with a
heading for the scene name.
Keep formatting minimal. You may separate sections with "---" divider lines,
and if the scene genuinely moves between locations you may mark a section with
a short level-3 or level-4 heading as a location tag. Otherwise write plain
paragraphs of prose with no surrounding structure."""

_PLAN_REVISE_SYSTEM_PROMPT = """You revise scene stances and outline beats to address a critique.
Use edit_outline for batched text-anchored outline edits and update_stance for
field-level stance changes. Prefer targeted edits over rewriting everything.
Match outline beats with a short unique fragment of the existing beat text.
If the critique needs no changes, make no tool calls and say so briefly.
Read-only tools are available when you need story bible or scene context."""

_PROSE_REVISE_SYSTEM_PROMPT = """You revise drafted scene prose to address a critique.
Use edit_prose for batched search/replace edits. Prefer targeted edits that
preserve wording the critique did not call out. Match with a short unique
fragment of existing prose. Empty replacement deletes a fragment; insert by
replacing an anchor with the anchor plus new text.
If the critique needs no changes, make no tool calls and say so briefly.
Read-only tools are available when you need story bible or scene context."""


class StanceOutput(BaseModel):
    character_id: str
    mood: list[str] = Field(default_factory=list)
    intent: str = ""
    tactics: str = ""
    stakes: str = ""


class StanceList(BaseModel):
    stances: list[StanceOutput] = Field(default_factory=list)


class OutlineBeats(BaseModel):
    beats: list[str] = Field(default_factory=list)


class PlanCritique(BaseModel):
    critique: str = ""


class ProseCritique(BaseModel):
    critique: str = ""
    prose_unusable: bool = False


class SceneSummary(BaseModel):
    summary: str


class ContextSelection(BaseModel):
    """Ids of Story Bible entries and scenes to include verbatim in the draft dossier."""

    character_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    scene_ids: list[str] = Field(default_factory=list)
    world_fact_ids: list[str] = Field(default_factory=list)
    notes: str = ""


# Backward-compatible alias used by older tests/imports.
OutlineCritique = PlanCritique


def build_scene_writer_graph(
    models: dict[str, BaseChatModel] | None = None,
    max_revisions: int = 1,
) -> CompiledStateGraph:
    """Build the enforced scene-writing workflow graph."""

    graph = StateGraph(SceneWorkflowState)
    graph.add_node("author_stances", _author_stances_node(models))
    graph.add_node("outline", _outline_node(models))
    graph.add_node("review_plan", _review_plan_node(models))
    graph.add_node("revise_plan", _revise_plan_node(models))
    graph.add_node("gather_context", _gather_context_node(models))
    graph.add_node("draft_prose", _draft_prose_node(models))
    graph.add_node("review_prose", _review_prose_node(models))
    graph.add_node("revise_prose", _revise_prose_node(models))
    graph.add_node("summarize", _summary_node(models))

    graph.add_edge(START, "author_stances")
    graph.add_edge("author_stances", "outline")
    graph.add_edge("outline", "review_plan")
    graph.add_edge("review_plan", "revise_plan")
    graph.add_conditional_edges(
        "revise_plan",
        _route_after_plan_revise,
        {"review_plan": "review_plan", "gather_context": "gather_context"},
    )
    graph.add_edge("gather_context", "draft_prose")
    graph.add_edge("draft_prose", "review_prose")
    graph.add_edge("review_prose", "revise_prose")
    graph.add_conditional_edges(
        "revise_prose",
        _route_after_prose_revise,
        {"review_prose": "review_prose", "summarize": "summarize"},
    )
    graph.add_edge("summarize", END)

    return graph.compile()


def _resolve_model(
    node_id: str,
    models: dict[str, BaseChatModel] | None,
    *,
    streaming: bool = True,
) -> BaseChatModel:
    if models is not None and node_id in models:
        return models[node_id]
    return get_chat_model_for_node(node_id, streaming=streaming)


def _structured_invoke(
    node_id: str,
    models: dict[str, BaseChatModel] | None,
    schema: type[BaseModel],
    prompt: str,
) -> BaseModel:
    model = _resolve_model(node_id, models, streaming=False).with_structured_output(schema)
    return model.invoke([HumanMessage(content=prompt)])


def _author_stances_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        character_lines = _character_context(state["character_ids"])
        prompt = (
            "Author initial character stances for this scene.\n\n"
            f"Premise: {state.get('premise', '')}\n"
            f"Purpose: {state.get('purpose', '')}\n"
            f"POV: {state.get('pov', '')}\n"
            f"Arc beats:\n{_arc_text(state.get('arc', []))}\n"
            f"Participating characters:\n{character_lines}\n"
            f"Constraints: {state.get('constraints', '') or '(none)'}\n"
            f"Notes: {state.get('notes', '') or '(none)'}"
        )
        prompt = _append_continuity_context(prompt, state)
        result = _structured_invoke(SCENE_STANCES_NODE_ID, models, StanceList, prompt)
        bible = get_world().story_bible
        character_ids = state.get("character_ids", [])
        stances: list[SceneCharacterStance] = []
        seen: set[str] = set()
        for item in result.stances:
            resolved_id = bible.resolve_character_id(item.character_id, allowed=character_ids)
            if resolved_id is None or resolved_id in seen:
                continue
            seen.add(resolved_id)
            stances.append(
                SceneCharacterStance(
                    character_id=resolved_id,
                    mood=list(item.mood),
                    intent=item.intent,
                    tactics=item.tactics,
                    stakes=item.stakes,
                )
            )
        update_scene_generated(state["scene_id"], stances=stances)
        return {"stances": stances}

    return node


def _outline_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        prompt = (
            "Outline the scene as a short list of concise beat statements.\n"
            "The scene must enact the events listed below.\n\n"
            f"Premise: {state.get('premise', '')}\n"
            f"Purpose: {state.get('purpose', '')}\n"
            f"POV: {state.get('pov', '')}\n"
            f"Arc beats:\n{_arc_text(state.get('arc', []))}\n"
            f"Events this scene enacts:\n{_event_context(state.get('event_ids', []))}\n"
            f"Related events (context only):\n{_event_context(state.get('related_event_ids', []))}\n"
            f"Stances:\n{_stances_text(state.get('stances', []))}\n"
            f"Notes: {state.get('notes', '') or '(none)'}"
        )
        prompt = _append_continuity_context(prompt, state)
        result = _structured_invoke(SCENE_OUTLINE_NODE_ID, models, OutlineBeats, prompt)
        beats = list(result.beats)
        update_scene_generated(state["scene_id"], outline=beats)
        return {"outline": beats}

    return node


def _review_plan_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        prompt = (
            "Critique the character stances and outline against the premise, purpose, "
            "and continuity with surrounding scenes. Call out problems in either "
            "artifact; say if no changes are needed.\n\n"
            f"Premise: {state.get('premise', '')}\n"
            f"Purpose: {state.get('purpose', '')}\n"
            f"Stances:\n{_stances_text(state.get('stances', []))}\n"
            f"Outline:\n{_outline_text(state.get('outline', []))}"
        )
        prompt = _append_continuity_context(prompt, state)
        result = _structured_invoke(SCENE_OUTLINE_REVIEW_NODE_ID, models, PlanCritique, prompt)
        return {"critique": result.critique}

    return node


def _revise_plan_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        scene_id = state["scene_id"]
        model = _resolve_model(SCENE_OUTLINE_REVISE_NODE_ID, models)
        agent = create_agent(
            model=model,
            tools=[edit_outline, update_stance, *READ_ONLY_WRITING_TOOLS],
            state_schema=PlanReviseAgentState,
            system_prompt=_PLAN_REVISE_SYSTEM_PROMPT,
            middleware=[ToolRetryMiddleware(max_retries=0, on_failure="continue")],
        )
        outline = list(state.get("outline", []))
        stances = _normalize_stances(state.get("stances", []))
        character_ids = list(state.get("character_ids", []))
        prompt = (
            "Revise stances and/or outline to address the critique.\n\n"
            f"Premise: {state.get('premise', '')}\n"
            f"Purpose: {state.get('purpose', '')}\n"
            f"Critique: {state.get('critique', '')}\n"
            f"Current stances:\n{_stances_text(stances)}\n"
            f"Current outline:\n{_outline_text(outline)}"
        )
        prompt = _append_continuity_context(prompt, state)
        result = agent.invoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "current_scene_id": scene_id,
                "current_scene": get_scene_text(scene_id),
                "outline": outline,
                "stances": [stance.model_dump(mode="json") for stance in stances],
                "character_ids": character_ids,
            }
        )
        revised_outline = _outline_from_agent_result(result, outline)
        revised_stances = _stances_from_agent_result(result, stances)
        update_scene_generated(scene_id, outline=revised_outline, stances=revised_stances)
        revision_count = state.get("revision_count", 0) + 1
        return {
            "outline": revised_outline,
            "stances": revised_stances,
            "revision_count": revision_count,
        }

    return node


def _gather_context_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        scene_id = state["scene_id"]
        model = _resolve_model(SCENE_GATHER_NODE_ID, models)
        agent = create_agent(
            model=model,
            tools=READ_ONLY_WRITING_TOOLS,
            state_schema=WritingAgentState,
            system_prompt=_GATHER_SYSTEM_PROMPT,
            response_format=ContextSelection,
            middleware=[ToolRetryMiddleware(max_retries=0, on_failure="continue")],
        )
        prompt = (
            "Select Story Bible and scene context the prose drafter needs.\n"
            "Return ids only; do not rewrite entry content.\n\n"
            f"Premise: {state.get('premise', '')}\n"
            f"Purpose: {state.get('purpose', '')}\n"
            f"POV: {state.get('pov', '')}\n"
            f"Arc beats:\n{_arc_text(state.get('arc', []))}\n"
            f"Events this scene enacts:\n{_event_context(state.get('event_ids', []))}\n"
            f"Related events (context only):\n{_event_context(state.get('related_event_ids', []))}\n"
            f"Stances:\n{_stances_text(state.get('stances', []))}\n"
            f"Outline:\n{_outline_text(state.get('outline', []))}\n"
            f"Constraints: {state.get('constraints', '') or '(none)'}\n"
            f"Notes: {state.get('notes', '') or '(none)'}"
        )
        prompt = _append_continuity_context(prompt, state)
        result = agent.invoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "current_scene_id": scene_id,
                "current_scene": get_scene_text(scene_id),
            }
        )
        selection = result.get("structured_response")
        if not isinstance(selection, ContextSelection):
            selection = ContextSelection()
        return {"context_dossier": _render_dossier(selection)}

    return node


def _render_dossier(selection: ContextSelection) -> str:
    """Resolve selected ids and assemble a verbatim markdown dossier for drafting."""

    world = get_world()
    bible = world.story_bible
    sections: list[str] = []
    dropped: list[str] = []

    character_blocks: list[str] = []
    for raw_id in selection.character_ids:
        resolved = bible.resolve_character_id(raw_id)
        if resolved is None:
            dropped.append(raw_id)
            continue
        character_blocks.append(read_character.invoke({"character_id": resolved}))
    if character_blocks:
        sections.append("## Characters\n\n" + "\n\n".join(character_blocks))

    event_blocks: list[str] = []
    for raw_id in selection.event_ids:
        resolved = bible.resolve_event_id(raw_id)
        if resolved is None:
            dropped.append(raw_id)
            continue
        event_blocks.append(read_event.invoke({"event_id": resolved}))
    if event_blocks:
        sections.append("## Events\n\n" + "\n\n".join(event_blocks))

    fact_blocks: list[str] = []
    for raw_id in selection.world_fact_ids:
        resolved = bible.resolve_world_fact_id(raw_id)
        if resolved is None:
            dropped.append(raw_id)
            continue
        fact_blocks.append(read_world_fact.invoke({"fact_id": resolved}))
    if fact_blocks:
        sections.append("## World facts\n\n" + "\n\n".join(fact_blocks))

    scene_blocks: list[str] = []
    for index, raw_id in enumerate(selection.scene_ids):
        if index >= MAX_DOSSIER_SCENES:
            dropped.append(f"{raw_id} (scene cap)")
            continue
        resolved = world.resolve_scene_id(raw_id)
        if resolved is None:
            dropped.append(raw_id)
            continue
        # Exact lookup only — never get_scene_text(), which falls back to the first scene.
        scene = world.get_scene(resolved)
        if scene is None:
            dropped.append(raw_id)
            continue
        markdown = scene.markdown
        if len(markdown) > PREVIOUS_SCENE_PROSE_CAP:
            markdown = markdown[:PREVIOUS_SCENE_PROSE_CAP] + "\n\n[... truncated ...]"
        scene_blocks.append(f"### {scene.title} [id: {scene.id}]\n\n{markdown}")
    if scene_blocks:
        sections.append("## Scenes\n\n" + "\n\n".join(scene_blocks))

    notes = selection.notes.strip()
    if notes:
        sections.append(f"## Gatherer notes\n\n{notes}")

    if dropped:
        sections.append("Dropped references: " + ", ".join(dropped))

    return "\n\n".join(sections)


def _draft_prose_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        scene_id = state["scene_id"]
        model = _resolve_model(SCENE_DRAFT_NODE_ID, models)
        prompt = (
            "Draft the full scene prose in markdown.\n"
            "The scene must enact the events listed below; use the related events only as "
            "background context.\n\n"
            f"Premise: {state.get('premise', '')}\n"
            f"Purpose: {state.get('purpose', '')}\n"
            f"POV: {state.get('pov', '')}\n"
            f"Arc beats:\n{_arc_text(state.get('arc', []))}\n"
            f"Events this scene enacts:\n{_event_context(state.get('event_ids', []))}\n"
            f"Related events (context only):\n{_event_context(state.get('related_event_ids', []))}\n"
            f"Stances:\n{_stances_text(state.get('stances', []))}\n"
            f"Outline:\n{_outline_text(state.get('outline', []))}\n"
            f"Constraints: {state.get('constraints', '') or '(none)'}\n"
            f"Notes: {state.get('notes', '') or '(none)'}"
        )
        dossier = state.get("context_dossier", "")
        if dossier:
            prompt = f"{prompt}\n\nContext dossier:\n{dossier}"
        prompt = _append_continuity_context(prompt, state)
        response = model.invoke(
            [
                SystemMessage(content=_DRAFT_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ]
        )
        prose = response.content if isinstance(response.content, str) else ""
        prose = _strip_leading_title(prose)
        _require_nonempty_prose(
            prose,
            "Draft step produced no prose",
        )
        set_scene_text(scene_id, prose)
        return {"prose": prose}

    return node


def _review_prose_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        prose = state.get("prose", "")
        prompt = (
            "Critique the drafted scene prose against the premise, purpose, stances, "
            "outline, and continuity with surrounding scenes. Suggest concrete edits; "
            "say if no changes are needed.\n"
            "If the prose is missing, obviously truncated, gibberish, or otherwise not "
            "an actual scene worth revising, set prose_unusable to true and explain why "
            "in critique. Otherwise leave prose_unusable false and critique normally.\n\n"
            f"Premise: {state.get('premise', '')}\n"
            f"Purpose: {state.get('purpose', '')}\n"
            f"Stances:\n{_stances_text(state.get('stances', []))}\n"
            f"Outline:\n{_outline_text(state.get('outline', []))}\n"
            f"Prose:\n{prose}"
        )
        prompt = _append_continuity_context(prompt, state)
        result = _structured_invoke(SCENE_PROSE_REVIEW_NODE_ID, models, ProseCritique, prompt)
        if result.prose_unusable:
            reason = result.critique.strip() or "no reason given"
            msg = f"Prose review marked the draft unusable: {reason}"
            raise SceneWorkflowError(msg)
        return {"prose_critique": result.critique}

    return node


def _revise_prose_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        scene_id = state["scene_id"]
        model = _resolve_model(SCENE_PROSE_REVISE_NODE_ID, models)
        agent = create_agent(
            model=model,
            tools=[edit_prose, *READ_ONLY_WRITING_TOOLS],
            state_schema=WritingAgentState,
            system_prompt=_PROSE_REVISE_SYSTEM_PROMPT,
            middleware=[ToolRetryMiddleware(max_retries=0, on_failure="continue")],
        )
        prose = state.get("prose", "")
        if not isinstance(prose, str):
            prose = get_scene_text(scene_id)
        prompt = (
            "Revise the scene prose to address the critique.\n\n"
            f"Premise: {state.get('premise', '')}\n"
            f"Purpose: {state.get('purpose', '')}\n"
            f"Critique: {state.get('prose_critique', '')}\n"
            f"Stances:\n{_stances_text(state.get('stances', []))}\n"
            f"Outline:\n{_outline_text(state.get('outline', []))}\n"
            f"Current prose:\n{prose}"
        )
        prompt = _append_continuity_context(prompt, state)
        result = agent.invoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "current_scene_id": scene_id,
                "current_scene": prose,
            }
        )
        revised = result.get("current_scene", prose)
        if not isinstance(revised, str):
            revised = prose
        _require_nonempty_prose(
            revised,
            "Revise prose step left the scene empty",
        )
        set_scene_text(scene_id, revised)
        prose_revision_count = state.get("prose_revision_count", 0) + 1
        return {"prose": revised, "prose_revision_count": prose_revision_count}

    return node


def _require_nonempty_prose(prose: str, message: str) -> None:
    if not prose.strip():
        raise SceneWorkflowError(message)


# Leading level-1/2 headings are titles; level 3+ headings are allowed as location tags.
_LEADING_TITLE_PATTERN = re.compile(r"\s*#{1,2} [^\n]*\n*")


def _strip_leading_title(prose: str) -> str:
    """Remove leading markdown titles from drafted prose.

    The scene title is stored and displayed outside the prose, but models
    reliably open drafts with a `# Title` heading anyway. Strip level-1/2
    headings (and surrounding blank lines) from the start of the text.
    """
    text = prose
    while True:
        match = _LEADING_TITLE_PATTERN.match(text)
        if match is None:
            return text
        text = text[match.end() :]


def _summary_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        prose = state.get("prose", "")
        prompt = (
            "Generate a concise one-line summary of the drafted scene prose.\n\n"
            f"Premise: {state.get('premise', '')}\n"
            f"Purpose: {state.get('purpose', '')}\n"
            f"Prose preview:\n{prose[:2000]}"
        )
        result = _structured_invoke(
            SCENE_SUMMARY_NODE_ID,
            models,
            SceneSummary,
            prompt,
        )
        set_scene_metadata(state["scene_id"], summary=result.summary)
        return {"summary": result.summary}

    return node


def _route_after_plan_revise(state: SceneWorkflowState) -> str:
    revision_count = state.get("revision_count", 0)
    max_revisions = state.get("max_revisions", 1)
    if revision_count < max_revisions:
        return "review_plan"
    return "gather_context"


def _route_after_prose_revise(state: SceneWorkflowState) -> str:
    revision_count = state.get("prose_revision_count", 0)
    max_revisions = state.get("max_revisions", 1)
    if revision_count < max_revisions:
        return "review_prose"
    return "summarize"


def _arc_text(arc: list[str]) -> str:
    if not arc:
        return "(none)"
    return "\n".join(f"{index}. {beat}" for index, beat in enumerate(arc, start=1))


def _append_continuity_context(prompt: str, state: SceneWorkflowState) -> str:
    continuity_context = state.get("continuity_context", "")
    if not continuity_context:
        return prompt
    return f"{prompt}\n\n{continuity_context}"


def _character_context(character_ids: list[str]) -> str:
    bible = get_world().story_bible
    if not character_ids:
        return "(none specified)"
    lines: list[str] = []
    for character_id in character_ids:
        character = bible.get_character(character_id)
        if character is None:
            lines.append(f"- unknown id: {character_id}")
        else:
            name = character.identity.name or "Unnamed"
            lines.append(f"- {name} [id: {character_id}]")
    return "\n".join(lines)


def _event_context(event_ids: list[str]) -> str:
    bible = get_world().story_bible
    if not event_ids:
        return "(none)"
    lines: list[str] = []
    for event_id in event_ids:
        event = bible.get_event(event_id)
        if event is None:
            lines.append(f"- unknown id: {event_id}")
            continue
        title = event.title or "Untitled"
        description = f": {event.description}" if event.description else ""
        lines.append(f"- {title} [id: {event_id}]{description}")
    return "\n".join(lines)


def _stances_text(stances: list[SceneCharacterStance] | list[Any]) -> str:
    normalized = _normalize_stances(stances)
    if not normalized:
        return "(none)"
    lines: list[str] = []
    bible = get_world().story_bible
    for stance in normalized:
        character = bible.get_character(stance.character_id)
        name = character.identity.name if character else stance.character_id
        lines.append(
            f"- {name} [{stance.character_id}]: mood={stance.mood}, "
            f"intent={stance.intent}, tactics={stance.tactics}, stakes={stance.stakes}"
        )
    return "\n".join(lines)


def _outline_text(outline: list[str]) -> str:
    if not outline:
        return "(none)"
    return "\n".join(f"{index}. {beat}" for index, beat in enumerate(outline, start=1))


def _normalize_stances(stances: list[Any] | None) -> list[SceneCharacterStance]:
    if not stances:
        return []
    normalized: list[SceneCharacterStance] = []
    for item in stances:
        if isinstance(item, SceneCharacterStance):
            normalized.append(item)
        elif isinstance(item, dict):
            normalized.append(SceneCharacterStance.model_validate(item))
    return normalized


def _outline_from_agent_result(result: dict[str, Any], fallback: list[str]) -> list[str]:
    raw = result.get("outline", fallback)
    if not isinstance(raw, list):
        return list(fallback)
    return [str(item) for item in raw]


def _stances_from_agent_result(
    result: dict[str, Any],
    fallback: list[SceneCharacterStance],
) -> list[SceneCharacterStance]:
    raw = result.get("stances", fallback)
    normalized = _normalize_stances(raw if isinstance(raw, list) else fallback)
    return normalized or list(fallback)


def structured_fake_model(response: BaseModel) -> BaseChatModel:
    """Return a chat model stub that always emits one structured output."""

    payload = json.dumps(response.model_dump())

    class _StructuredFake(BaseChatModel):
        def with_structured_output(self, schema: type[BaseModel], **kwargs: Any) -> Any:
            class _Runnable:
                def invoke(self, input: Any, config: Any = None, **kwargs: Any) -> BaseModel:
                    return response

            return _Runnable()

        def bind_tools(self, tools: Any, **kwargs: Any) -> _StructuredFake:
            return self

        def _generate(
            self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
        ):
            from langchain_core.messages import AIMessage
            from langchain_core.outputs import ChatGeneration, ChatResult

            message = AIMessage(content=payload)
            return ChatResult(generations=[ChatGeneration(message=message)])

        @property
        def _llm_type(self) -> str:
            return "structured-fake"

    return _StructuredFake()


# Compatibility aliases for renamed nodes (used by older test imports).
_review_outline_node = _review_plan_node
_revise_outline_node = _revise_plan_node
