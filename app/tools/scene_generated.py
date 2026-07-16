"""Workflow-scoped tools for editing generated scene artifacts (outline, stances, prose).

These tools mutate the revise agent's injected state (not the world). Workflow nodes
persist the final state after the agent finishes.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, ToolException, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from pydantic import BaseModel

from app.world.models import SceneCharacterStance
from app.world.store import get_world

OutlineOp = Literal["replace", "add_after", "add_first", "delete"]


class OutlineEdit(BaseModel):
    """One text-anchored edit against the current outline beats."""

    op: OutlineOp
    match: str = ""
    text: str = ""


class ProseEdit(BaseModel):
    """One search/replace edit against scene prose.

    Empty ``replacement`` deletes the matched fragment. To insert, replace an
    anchor fragment with that anchor plus the new text.
    """

    match: str
    replacement: str = ""


def apply_outline_operations(
    outline: list[str],
    operations: list[OutlineEdit],
) -> tuple[list[str], list[str]]:
    """Apply outline ops in order; return the new beats and a per-op report."""

    current = list(outline)
    reports: list[str] = []
    for index, operation in enumerate(operations, start=1):
        ok, message, current = _apply_one_outline_op(current, operation)
        status = "ok" if ok else "error"
        reports.append(f"{index}. [{status}] {message}")
    return current, reports


def apply_prose_operations(
    prose: str,
    operations: list[ProseEdit],
) -> tuple[str, list[str]]:
    """Apply prose search/replace ops in order; return new text and a per-op report."""

    current = prose
    reports: list[str] = []
    for index, operation in enumerate(operations, start=1):
        ok, message, current = _apply_one_prose_op(current, operation)
        status = "ok" if ok else "error"
        reports.append(f"{index}. [{status}] {message}")
    return current, reports


def _apply_one_outline_op(
    outline: list[str],
    operation: OutlineEdit,
) -> tuple[bool, str, list[str]]:
    op = operation.op
    if op == "add_first":
        text = operation.text.strip()
        if not text:
            return False, "add_first requires non-empty text", outline
        return True, f"Inserted at start: {text}", [text, *outline]

    match = operation.match.strip()
    if not match:
        return False, f"{op} requires a non-empty match fragment", outline

    hit = _find_unique_beat_index(outline, match)
    if isinstance(hit, str):
        return False, hit, outline

    if op == "replace":
        text = operation.text.strip()
        if not text:
            return False, "replace requires non-empty text", outline
        updated = list(outline)
        old = updated[hit]
        updated[hit] = text
        return True, f"Replaced beat {hit + 1} ({old!r} -> {text!r})", updated

    if op == "add_after":
        text = operation.text.strip()
        if not text:
            return False, "add_after requires non-empty text", outline
        updated = list(outline)
        updated.insert(hit + 1, text)
        return True, f"Inserted after beat {hit + 1}: {text}", updated

    if op == "delete":
        updated = list(outline)
        removed = updated.pop(hit)
        return True, f"Deleted beat {hit + 1}: {removed!r}", updated

    return False, f"Unknown op: {op}", outline


def _apply_one_prose_op(
    prose: str,
    operation: ProseEdit,
) -> tuple[bool, str, str]:
    match = operation.match
    if not match.strip():
        return False, "match must be a non-empty fragment", prose

    spans = list(re.finditer(re.escape(match), prose, flags=re.IGNORECASE))
    if not spans:
        return False, f"No prose matched {match!r}", prose
    if len(spans) > 1:
        return (
            False,
            f"Ambiguous match {match!r}: matched {len(spans)} occurrences",
            prose,
        )

    span = spans[0]
    updated = prose[: span.start()] + operation.replacement + prose[span.end() :]
    if operation.replacement == "":
        message = f"Deleted matched fragment {match!r}"
    else:
        message = f"Replaced {match!r} with {operation.replacement!r}"
    return True, message, updated


def _find_unique_beat_index(outline: list[str], match: str) -> int | str:
    needle = match.lower()
    hits = [index for index, beat in enumerate(outline) if needle in beat.lower()]
    if not hits:
        return f"No beat matched {match!r}"
    if len(hits) > 1:
        return f"Ambiguous match {match!r}: matched {len(hits)} beats"
    return hits[0]


def _normalize_outline_ops(
    operations: list[OutlineEdit] | list[dict[str, Any]],
) -> list[OutlineEdit]:
    normalized: list[OutlineEdit] = []
    for item in operations:
        if isinstance(item, OutlineEdit):
            normalized.append(item)
        else:
            normalized.append(OutlineEdit.model_validate(item))
    return normalized


def _normalize_prose_ops(operations: list[ProseEdit] | list[dict[str, Any]]) -> list[ProseEdit]:
    normalized: list[ProseEdit] = []
    for item in operations:
        if isinstance(item, ProseEdit):
            normalized.append(item)
        else:
            normalized.append(ProseEdit.model_validate(item))
    return normalized


def _stances_from_state(state: dict[str, Any]) -> list[SceneCharacterStance]:
    raw = state.get("stances", [])
    if not isinstance(raw, list):
        return []
    stances: list[SceneCharacterStance] = []
    for item in raw:
        if isinstance(item, SceneCharacterStance):
            stances.append(item)
        elif isinstance(item, dict):
            stances.append(SceneCharacterStance.model_validate(item))
    return stances


def _outline_from_state(state: dict[str, Any]) -> list[str]:
    raw = state.get("outline", [])
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _format_outline(outline: list[str]) -> str:
    if not outline:
        return "(empty outline)"
    return "\n".join(f"{index}. {beat}" for index, beat in enumerate(outline, start=1))


@tool
def edit_outline(
    operations: list[OutlineEdit],
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Apply a batch of text-anchored edits to the current scene outline.

    Match fragments are case-insensitive unique substrings of existing beats.
    Ops apply in order; later ops see earlier results. Failed ops are skipped
    and reported so you can fix them in a follow-up call.
    """

    if not operations:
        raise ToolException("Provide at least one outline operation.")

    ops = _normalize_outline_ops(operations)
    outline = _outline_from_state(state)
    updated, reports = apply_outline_operations(outline, ops)
    succeeded = sum(1 for line in reports if "[ok]" in line)
    failed = len(reports) - succeeded
    content = (
        f"Applied {succeeded}/{len(reports)} outline operation(s)"
        f"{f', {failed} failed' if failed else ''}.\n"
        + "\n".join(reports)
        + "\n\nCurrent outline:\n"
        + _format_outline(updated)
    )
    return Command(
        update={
            "outline": updated,
            "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)],
        }
    )


@tool
def update_stance(
    character_id: str,
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    mood: list[str] | None = None,
    intent: str | None = None,
    tactics: str | None = None,
    stakes: str | None = None,
) -> Command:
    """Update fields on one character's stance for the current scene.

    Only provided fields are changed. ``character_id`` must resolve to a
    participating character that already has a stance.
    """

    if mood is None and intent is None and tactics is None and stakes is None:
        raise ToolException("Provide at least one of mood, intent, tactics, or stakes.")

    allowed_raw = state.get("character_ids", [])
    allowed = [str(item) for item in allowed_raw] if isinstance(allowed_raw, list) else []
    bible = get_world().story_bible
    resolved_id = bible.resolve_character_id(character_id, allowed=allowed or None)
    if resolved_id is None:
        options = ", ".join(allowed) if allowed else "(none)"
        raise ToolException(
            f"Unknown character_id {character_id!r} for this scene; valid ids: {options}."
        )

    stances = _stances_from_state(state)
    target: SceneCharacterStance | None = None
    for stance in stances:
        if stance.character_id == resolved_id:
            target = stance
            break
    if target is None:
        known = ", ".join(stance.character_id for stance in stances) or "(none)"
        raise ToolException(
            f"No stance for character_id {resolved_id!r}; existing stance ids: {known}."
        )

    if mood is not None:
        target.mood = list(mood)
    if intent is not None:
        target.intent = intent
    if tactics is not None:
        target.tactics = tactics
    if stakes is not None:
        target.stakes = stakes

    character = bible.get_character(resolved_id)
    name = character.identity.name if character else resolved_id
    changed: list[str] = []
    if mood is not None:
        changed.append(f"mood={target.mood}")
    if intent is not None:
        changed.append(f"intent={target.intent!r}")
    if tactics is not None:
        changed.append(f"tactics={target.tactics!r}")
    if stakes is not None:
        changed.append(f"stakes={target.stakes!r}")

    # Return only the changed stance: the state key merges by character_id, so
    # parallel update_stance calls in one turn combine instead of clobbering
    # each other with stale copies of the full list.
    return Command(
        update={
            "stances": [target.model_dump(mode="json")],
            "messages": [
                ToolMessage(
                    content=f"Updated stance for {name} [{resolved_id}]: {', '.join(changed)}.",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


@tool
def edit_prose(
    operations: list[ProseEdit],
    state: Annotated[dict[str, Any], InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Apply a batch of search/replace edits to the current scene prose.

    Match fragments must uniquely identify one occurrence (case-insensitive).
    Ops apply in order; failed ops are skipped and reported.
    """

    if not operations:
        raise ToolException("Provide at least one prose operation.")

    ops = _normalize_prose_ops(operations)
    current = state.get("current_scene", "")
    if not isinstance(current, str):
        current = ""
    updated, reports = apply_prose_operations(current, ops)
    succeeded = sum(1 for line in reports if "[ok]" in line)
    failed = len(reports) - succeeded
    content = (
        f"Applied {succeeded}/{len(reports)} prose operation(s)"
        f"{f', {failed} failed' if failed else ''}.\n" + "\n".join(reports)
    )
    return Command(
        update={
            "current_scene": updated,
            "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)],
        }
    )


SCENE_GENERATED_EDIT_TOOLS = [edit_outline, update_stance, edit_prose]

__all__ = [
    "SCENE_GENERATED_EDIT_TOOLS",
    "OutlineEdit",
    "ProseEdit",
    "apply_outline_operations",
    "apply_prose_operations",
    "edit_outline",
    "edit_prose",
    "update_stance",
]
