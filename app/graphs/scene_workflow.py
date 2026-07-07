"""Enforced LangGraph workflow for generating scene content from a blueprint."""

from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ToolRetryMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from app.graphs.canvas_middleware import CanvasAppendMiddleware
from app.graphs.state import WritingAgentState
from app.graphs.workflow_state import SceneWorkflowState
from app.models.client import get_chat_model_for_node
from app.models.config import (
    SCENE_DRAFT_NODE_ID,
    SCENE_OUTLINE_NODE_ID,
    SCENE_OUTLINE_REVIEW_NODE_ID,
    SCENE_OUTLINE_REVISE_NODE_ID,
    SCENE_STANCES_NODE_ID,
    SCENE_SUMMARY_NODE_ID,
)
from app.tools import READ_ONLY_WRITING_TOOLS
from app.world.models import SceneCharacterStance
from app.world.scene import (
    get_scene_text,
    set_scene_metadata,
    set_scene_text,
    update_scene_generated,
)
from app.world.store import get_world

_DRAFT_SYSTEM_PROMPT = """You are drafting scene prose for a fiction project.
Use read-only tools to pull story bible and scene blueprint detail when needed.
When the prompt includes related or next scenes by summary only, use read_scene or
list_scenes to read their full prose if you need more detail for continuity.
Write the full scene markdown inside <canvas>...</canvas> tags.
You may use multiple canvas blocks; they append in order.
Always close canvas tags. Everything inside the tags is scene prose, not chat."""


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


class OutlineCritique(BaseModel):
    critique: str = ""


class SceneSummary(BaseModel):
    summary: str


def build_scene_writer_graph(
    models: dict[str, BaseChatModel] | None = None,
    max_revisions: int = 1,
) -> CompiledStateGraph:
    """Build the enforced scene-writing workflow graph."""

    graph = StateGraph(SceneWorkflowState)
    graph.add_node("author_stances", _author_stances_node(models))
    graph.add_node("outline", _outline_node(models))
    graph.add_node("review_outline", _review_outline_node(models))
    graph.add_node("revise_outline", _revise_outline_node(models))
    graph.add_node("draft_prose", _draft_prose_node(models))
    graph.add_node("summarize", _summary_node(models))

    graph.add_edge(START, "author_stances")
    graph.add_edge("author_stances", "outline")
    graph.add_edge("outline", "review_outline")
    graph.add_edge("review_outline", "revise_outline")
    graph.add_conditional_edges(
        "revise_outline",
        _route_after_revise,
        {"review_outline": "review_outline", "draft_prose": "draft_prose"},
    )
    graph.add_edge("draft_prose", "summarize")
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


def _review_outline_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        prompt = (
            "Critique the outline against the premise, purpose, character stances, "
            "and continuity with surrounding scenes.\n\n"
            f"Premise: {state.get('premise', '')}\n"
            f"Purpose: {state.get('purpose', '')}\n"
            f"Stances:\n{_stances_text(state.get('stances', []))}\n"
            f"Outline:\n{_outline_text(state.get('outline', []))}"
        )
        prompt = _append_continuity_context(prompt, state)
        result = _structured_invoke(SCENE_OUTLINE_REVIEW_NODE_ID, models, OutlineCritique, prompt)
        return {"critique": result.critique}

    return node


def _revise_outline_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        prompt = (
            "Revise the outline to address the critique.\n\n"
            f"Premise: {state.get('premise', '')}\n"
            f"Purpose: {state.get('purpose', '')}\n"
            f"Critique: {state.get('critique', '')}\n"
            f"Current outline:\n{_outline_text(state.get('outline', []))}"
        )
        result = _structured_invoke(SCENE_OUTLINE_REVISE_NODE_ID, models, OutlineBeats, prompt)
        beats = list(result.beats)
        update_scene_generated(state["scene_id"], outline=beats)
        revision_count = state.get("revision_count", 0) + 1
        return {"outline": beats, "revision_count": revision_count}

    return node


def _draft_prose_node(models: dict[str, BaseChatModel] | None) -> Any:
    def node(state: SceneWorkflowState) -> dict[str, Any]:
        scene_id = state["scene_id"]
        model = _resolve_model(SCENE_DRAFT_NODE_ID, models)
        agent = create_agent(
            model=model,
            tools=READ_ONLY_WRITING_TOOLS,
            state_schema=WritingAgentState,
            system_prompt=_DRAFT_SYSTEM_PROMPT,
            middleware=[
                CanvasAppendMiddleware(),
                ToolRetryMiddleware(max_retries=0, on_failure="continue"),
            ],
        )
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
        prompt = _append_continuity_context(prompt, state)
        result = agent.invoke(
            {
                "messages": [HumanMessage(content=prompt)],
                "current_scene_id": scene_id,
                "current_scene": get_scene_text(scene_id),
            }
        )
        prose = result.get("current_scene", "")
        if not isinstance(prose, str):
            prose = ""
        set_scene_text(scene_id, prose)
        return {"prose": prose}

    return node


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


def _route_after_revise(state: SceneWorkflowState) -> str:
    revision_count = state.get("revision_count", 0)
    max_revisions = state.get("max_revisions", 1)
    if revision_count < max_revisions:
        return "review_outline"
    return "draft_prose"


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


def _stances_text(stances: list[SceneCharacterStance]) -> str:
    if not stances:
        return "(none)"
    lines: list[str] = []
    bible = get_world().story_bible
    for stance in stances:
        character = bible.get_character(stance.character_id)
        name = character.identity.name if character else stance.character_id
        lines.append(f"- {name}: mood={stance.mood}, intent={stance.intent}")
    return "\n".join(lines)


def _outline_text(outline: list[str]) -> str:
    if not outline:
        return "(none)"
    return "\n".join(f"{index}. {beat}" for index, beat in enumerate(outline, start=1))


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
