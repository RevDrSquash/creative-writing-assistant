"""Custom LangGraph state for the writing agent."""

from __future__ import annotations

from typing import Annotated, Any

from langchain.agents import AgentState


def keep_last(current: Any, update: Any) -> Any:
    """Reducer with overwrite semantics that tolerates parallel writes.

    Behaves like an un-annotated key (last write wins), but because it is an
    explicit reducer, LangGraph accepts multiple writes in one step (e.g. a
    model emitting two edit tool calls in one turn) instead of raising
    INVALID_CONCURRENT_GRAPH_UPDATE.
    """

    return update


CHARACTER_CRITIQUES_RESET = object()


def merge_character_critiques(
    current: list[dict[str, Any]] | None,
    update: list[dict[str, Any]] | object | None,
) -> list[dict[str, Any]]:
    """Append character critiques, or replace the list when ``update`` is the reset sentinel.

    Parallel ``review_character`` nodes each return one critique. Draft and revise-prose
    emit ``CHARACTER_CRITIQUES_RESET`` before a review round so leftover entries from the
    previous round are dropped.
    """

    if update is CHARACTER_CRITIQUES_RESET:
        return []
    merged = list(current or [])
    if not update:
        return merged
    return merged + list(update)


def merge_stances(current: list[Any] | None, update: list[Any] | None) -> list[Any]:
    """Merge stance updates by ``character_id``.

    ``update_stance`` returns only the stance it changed, so parallel tool
    calls updating different characters in the same step combine losslessly.
    Later writes to the same character replace earlier ones.
    """

    def character_id(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("character_id", ""))
        return str(getattr(item, "character_id", ""))

    merged: list[Any] = list(current or [])
    for item in update or []:
        item_id = character_id(item)
        for index, existing in enumerate(merged):
            if character_id(existing) == item_id:
                merged[index] = item
                break
        else:
            merged.append(item)
    return merged


class WritingAgentState(AgentState):
    """Agent state extended with the scene currently open in the workspace.

    ``current_scene`` holds the markdown text of the open scene and stays
    authoritative for scene text during a run; the UI writes state updates
    through to the ``World`` object. ``current_scene_id`` identifies which
    world scene that text belongs to.
    """

    current_scene: Annotated[str, keep_last]
    current_scene_id: Annotated[str, keep_last]


class PlanReviseAgentState(WritingAgentState):
    """Revise-agent state for editing outline beats and character stances."""

    outline: Annotated[list[str], keep_last]
    stances: Annotated[list[Any], merge_stances]
    character_ids: list[str]
