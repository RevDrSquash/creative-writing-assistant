"""Scene-reading and scene-editing tools for the writing agent."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from math import ceil, floor
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, ToolException, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from app.world.scene import (
    create_scene as world_create_scene,
)
from app.world.scene import (
    delete_scene as world_delete_scene,
)
from app.world.scene import (
    set_scene_metadata,
    set_scene_text,
)
from app.world.store import get_world


@tool
def read_scene(
    state: Annotated[dict[str, Any], InjectedState],
    scene_id: str = "",
) -> str:
    """Return the full Markdown text of a scene.

    Without `scene_id`, reads the scene currently open in the workspace.
    Call this before edits to anchor on the actual current wording.
    """

    current_id = state.get("current_scene_id", "")
    if scene_id and scene_id != current_id:
        scene = get_world().get_scene(scene_id)
        if scene is None:
            raise ToolException(f"No scene with id {scene_id}; call list_scenes for valid ids.")
        return scene.markdown

    current_scene = state.get("current_scene", "")
    return current_scene if isinstance(current_scene, str) else ""


@tool
def list_scenes(state: Annotated[dict[str, Any], InjectedState]) -> str:
    """List all scenes in order with their ids, titles, and summaries.

    The scene currently open in the workspace is marked with `(open)`.
    """

    current_id = state.get("current_scene_id", "")
    lines = []
    for position, scene in enumerate(get_world().scenes, start=1):
        marker = " (open)" if scene.id == current_id else ""
        summary = f" - {scene.summary}" if scene.summary else ""
        lines.append(f"{position}. {scene.title} [id: {scene.id}]{marker}{summary}")
    return "\n".join(lines)


@tool
def create_scene(
    title: str,
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    summary: str = "",
) -> Command:
    """Create a new empty scene at the end of the scene list and open it.

    After creating, use canvas tags or replace_scene_text to write its prose.
    """

    _persist_open_scene_text(state)
    scene = world_create_scene(title, summary)
    return Command(
        update={
            "current_scene_id": scene.id,
            "current_scene": scene.markdown,
            "messages": [
                ToolMessage(
                    content=f"Created scene '{scene.title}' (id: {scene.id}) and opened it.",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool
def select_scene(
    scene_id: str,
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Open a different scene in the workspace so subsequent edits target it."""

    scene = get_world().get_scene(scene_id)
    if scene is None:
        raise ToolException(f"No scene with id {scene_id}; call list_scenes for valid ids.")

    _persist_open_scene_text(state)
    return Command(
        update={
            "current_scene_id": scene.id,
            "current_scene": scene.markdown,
            "messages": [
                ToolMessage(
                    content=f"Opened scene '{scene.title}' (id: {scene.id}).",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool
def update_scene(
    state: Annotated[dict[str, Any], InjectedState],
    scene_id: str = "",
    title: str | None = None,
    summary: str | None = None,
) -> str:
    """Update an existing scene's title and/or summary.

    Without ``scene_id``, updates the scene currently open in the workspace.
    """

    target_id = scene_id or state.get("current_scene_id", "")
    if not target_id:
        raise ToolException("No scene specified and none is open; call list_scenes.")

    scene = get_world().get_scene(target_id)
    if scene is None:
        raise ToolException(f"No scene with id {target_id}; call list_scenes for valid ids.")

    if title is None and summary is None:
        return "No changes requested (provide title and/or summary)."

    set_scene_metadata(target_id, title=title, summary=summary)

    parts = []
    if title is not None:
        parts.append(f"title to '{title}'")
    if summary is not None:
        parts.append(f"summary to '{summary}'")
    return f"Updated scene '{scene.title}' (id: {scene.id}): set {' and '.join(parts)}."


@tool
def delete_scene(
    scene_id: str,
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Delete a scene permanently. The last remaining scene cannot be deleted.

    If the deleted scene was open, the first remaining scene is opened.
    """

    world = get_world()
    scene = world.get_scene(scene_id)
    if scene is None:
        raise ToolException(f"No scene with id {scene_id}; call list_scenes for valid ids.")

    try:
        world_delete_scene(scene_id)
    except ValueError as exc:
        raise ToolException(str(exc)) from exc

    update: dict[str, Any] = {
        "messages": [
            ToolMessage(
                content=f"Deleted scene '{scene.title}' (id: {scene.id}).",
                tool_call_id=tool_call_id,
            )
        ]
    }
    if state.get("current_scene_id") == scene_id:
        fallback = world.scenes[0]
        update["current_scene_id"] = fallback.id
        update["current_scene"] = fallback.markdown
    return Command(update=update)


def _persist_open_scene_text(state: dict[str, Any]) -> None:
    """Write the open scene's in-run text to the world before switching scenes."""

    current_id = state.get("current_scene_id", "")
    current_text = state.get("current_scene")
    if not isinstance(current_id, str) or not current_id or not isinstance(current_text, str):
        return
    scene = get_world().get_scene(current_id)
    if scene is not None and scene.markdown != current_text:
        set_scene_text(current_id, current_text)


@tool
def replace_scene_text(
    target: str,
    replacement: str,
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Replace a contiguous block of the current scene with new text.

    `target` should be a verbatim quote from the scene. The system tolerates small
    whitespace / punctuation drift via fuzzy matching, but refuses if `target`
    matches zero or more than one block.
    """

    current_scene = state.get("current_scene", "")
    if not isinstance(current_scene, str):
        current_scene = ""
    new_scene = fuzzy_replace_once(current_scene, target, replacement)
    return Command(
        update={
            "current_scene": new_scene,
            "messages": [
                ToolMessage(
                    content=(f"Replaced {len(target)} chars; scene is now {len(new_scene)} chars."),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


def fuzzy_replace_once(
    document: str,
    target: str,
    replacement: str,
    *,
    similarity_threshold: float = 0.85,
) -> str:
    """Replace a single exact or fuzzy match for ``target`` in ``document``."""

    if not target:
        raise ToolException("target must not be empty")

    exact_count = document.count(target)
    if exact_count == 1:
        return document.replace(target, replacement, 1)
    if exact_count > 1:
        raise ToolException(
            f"target matches {exact_count} locations; include more surrounding context to "
            "disambiguate"
        )

    candidate = _find_single_fuzzy_candidate(
        document,
        target,
        similarity_threshold=similarity_threshold,
    )
    return document[: candidate.start] + replacement + document[candidate.end :]


@dataclass(frozen=True)
class _FuzzyCandidate:
    start: int
    end: int
    score: float

    @property
    def length(self) -> int:
        return self.end - self.start


def _find_single_fuzzy_candidate(
    document: str,
    target: str,
    *,
    similarity_threshold: float,
    epsilon: float = 0.02,
) -> _FuzzyCandidate:
    target_length = len(target)
    min_length = max(1, floor(target_length * 0.8))
    max_length = max(min_length, ceil(target_length * 1.2))
    candidates: list[_FuzzyCandidate] = []

    for start in range(len(document)):
        for window_length in range(min_length, max_length + 1):
            end = start + window_length
            if end > len(document):
                break
            score = SequenceMatcher(None, target, document[start:end]).ratio()
            if score >= similarity_threshold:
                candidates.append(_FuzzyCandidate(start, end, score))

    if not candidates:
        raise ToolException("no match for target; call read_scene to confirm exact wording")

    best_score = max(candidate.score for candidate in candidates)
    top_candidates = [
        candidate for candidate in candidates if candidate.score >= best_score - epsilon
    ]
    match_groups = _group_overlapping_candidates(top_candidates)
    if len(match_groups) > 1:
        raise ToolException("multiple fuzzy matches found; quote target more precisely")

    return max(
        match_groups[0],
        key=lambda candidate: (candidate.score, -abs(candidate.length - target_length)),
    )


def _group_overlapping_candidates(
    candidates: list[_FuzzyCandidate],
) -> list[list[_FuzzyCandidate]]:
    groups: list[list[_FuzzyCandidate]] = []
    current_group: list[_FuzzyCandidate] = []
    current_end = -1

    for candidate in sorted(candidates, key=lambda item: (item.start, item.end)):
        if not current_group or candidate.start > current_end:
            current_group = [candidate]
            groups.append(current_group)
        else:
            current_group.append(candidate)
        current_end = max(current_end, candidate.end)

    return groups


@tool
def read_scene_blueprint(
    state: Annotated[dict[str, Any], InjectedState],
    scene_id: str = "",
) -> str:
    """Return a scene's blueprint: premise, purpose, outline beats, and per-character stances.

    Without `scene_id`, reads the scene currently open in the workspace.
    """

    target_id = scene_id or state.get("current_scene_id", "")
    if not target_id:
        raise ToolException("No scene specified and none is open; call list_scenes.")

    world = get_world()
    scene = world.get_scene(target_id)
    if scene is None:
        raise ToolException(f"No scene with id {target_id}; call list_scenes for valid ids.")

    blueprint = scene.blueprint
    bible = world.story_bible
    lines = [
        f"# Blueprint: {scene.title or 'Untitled'} [scene id: {scene.id}]",
        "",
        "## Premise",
        blueprint.premise.strip() or "(not set)",
        "",
        "## Purpose",
        blueprint.purpose.strip() or "(not set)",
        "",
        "## Outline",
    ]
    if not blueprint.outline:
        lines.append("(none)")
    else:
        for position, beat in enumerate(blueprint.outline, start=1):
            text = beat.strip() or "(empty)"
            lines.append(f"{position}. {text}")

    lines.append("")
    lines.append("## Character Stances")
    if not blueprint.stances:
        lines.append("(none)")
    for stance in blueprint.stances:
        character = bible.get_character(stance.character_id)
        name = character.identity.name if character else f"unknown ({stance.character_id})"
        lines.append(f"### {name} [character id: {stance.character_id}]")
        if stance.mood:
            lines.append("Mood:")
            for statement in stance.mood:
                lines.append(f"- {statement}")
        else:
            lines.append("Mood: (none)")
        lines.append(f"Intent: {stance.intent or '-'}")
        lines.append(f"Tactics: {stance.tactics or '-'}")
        lines.append(f"Stakes: {stance.stakes or '-'}")
        lines.append("")

    return "\n".join(lines).rstrip()


@tool
def draft_scene(
    premise: str,
    purpose: str,
    pov: str,
    character_ids: list[str],
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    constraints: str = "",
) -> Command:
    """Run the full scene-writing workflow and open the resulting new scene.

    Always creates a new scene, formalizes the brief into blueprint fields,
    outlines, drafts prose, and sets title and summary.
    """

    _persist_open_scene_text(state)
    scene = world_create_scene()
    from app.graphs.registry import get_workflow

    workflow = get_workflow("draft_scene")
    workflow.invoke(
        {
            "premise": premise,
            "purpose": purpose,
            "pov": pov,
            "character_ids": character_ids,
            "constraints": constraints,
            "scene_id": scene.id,
            "revision_count": 0,
            "max_revisions": 1,
        }
    )
    drafted_scene = get_world().get_scene(scene.id)
    prose = drafted_scene.markdown if drafted_scene is not None else scene.markdown
    title = drafted_scene.title if drafted_scene is not None else scene.title
    return Command(
        update={
            "current_scene_id": scene.id,
            "current_scene": prose,
            "messages": [
                ToolMessage(
                    content=(f"Drafted scene '{title}' (id: {scene.id}) and opened it."),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


SCENE_TOOLS = [
    read_scene,
    read_scene_blueprint,
    replace_scene_text,
    list_scenes,
    create_scene,
    select_scene,
    update_scene,
    delete_scene,
    draft_scene,
]
