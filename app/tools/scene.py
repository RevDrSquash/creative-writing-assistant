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


@tool
def read_scene(state: Annotated[dict[str, Any], InjectedState]) -> str:
    """Return the full Markdown text of the scene currently open in the workspace.

    Call this before edits to anchor on the actual current wording.
    """

    current_scene = state.get("current_scene", "")
    return current_scene if isinstance(current_scene, str) else ""


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


SCENE_TOOLS = [read_scene, replace_scene_text]
