"""Event relationship validation and derived diagnostics.

Relations define chronology (with the timeline list as tie-breaker); this module
validates structural constraints, computes canonical order, and cycle warnings.
See ``docs/story_bible_model.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.world.models import (
    DIRECTED_EVENT_RELATION_KINDS,
    Event,
    EventRelation,
    EventRelationKind,
    StoryBible,
)

DiagnosticKind = Literal["cycle"]


@dataclass(frozen=True)
class RelationDiagnostic:
    """A derived warning about an event relationship."""

    kind: DiagnosticKind
    relation_id: str
    message: str


class RelationValidationError(ValueError):
    """Raised when a relation fails structural validation."""


def _event_listing(bible: StoryBible) -> str:
    if not bible.timeline:
        return "No events exist yet; create events first."
    listing = ", ".join(f"{event.title or 'Untitled'} [{event.id}]" for event in bible.timeline)
    return f"Valid events: {listing}"


def _relation_key(kind: EventRelationKind, source_id: str, target_id: str) -> tuple:
    if kind == "during":
        return (kind, tuple(sorted((source_id, target_id))))
    return (kind, source_id, target_id)


def _directed_adjacency(bible: StoryBible) -> dict[str, list[str]]:
    """Map each follower (later) event to the earlier events it follows."""

    adjacency: dict[str, list[str]] = {event.id: [] for event in bible.timeline}
    for relation in bible.event_relations:
        if relation.kind not in DIRECTED_EVENT_RELATION_KINDS:
            continue
        if relation.source_id in adjacency and relation.target_id in adjacency:
            adjacency[relation.source_id].append(relation.target_id)
    return adjacency


def _can_reach(adjacency: dict[str, list[str]], start: str, goal: str) -> bool:
    if start == goal:
        return True
    seen: set[str] = set()
    queue = [start]
    while queue:
        node = queue.pop()
        if node == goal:
            return True
        if node in seen:
            continue
        seen.add(node)
        queue.extend(adjacency.get(node, []))
    return False


def chronological_order(bible: StoryBible) -> list[Event]:
    """Return events in canonical chronological order.

    Directed edges force ``target`` (earlier) before ``source`` (later). Among
    events with no ordering constraint, list position is the tie-breaker.
    Residual cycles (legacy data) are appended in list order.
    """

    if not bible.timeline:
        return []

    index_by_id = {event.id: index for index, event in enumerate(bible.timeline)}
    adjacency = _directed_adjacency(bible)

    # For topological sort: earlier must come before later, so later depends on earlier.
    in_degree: dict[str, int] = {event.id: 0 for event in bible.timeline}
    reverse_adjacency: dict[str, list[str]] = {event.id: [] for event in bible.timeline}
    for later_id, earlier_ids in adjacency.items():
        for earlier_id in earlier_ids:
            in_degree[later_id] += 1
            reverse_adjacency[earlier_id].append(later_id)

    ready = sorted(
        [event_id for event_id, degree in in_degree.items() if degree == 0],
        key=lambda event_id: index_by_id[event_id],
    )
    ordered_ids: list[str] = []

    while ready:
        event_id = ready.pop(0)
        ordered_ids.append(event_id)
        for later_id in reverse_adjacency[event_id]:
            in_degree[later_id] -= 1
            if in_degree[later_id] == 0:
                ready.append(later_id)
        ready.sort(key=lambda event_id: index_by_id[event_id])

    if len(ordered_ids) < len(bible.timeline):
        for event in bible.timeline:
            if event.id not in ordered_ids:
                ordered_ids.append(event.id)

    event_by_id = {event.id: event for event in bible.timeline}
    return [event_by_id[event_id] for event_id in ordered_ids]


def normalize_relation(
    bible: StoryBible,
    kind: EventRelationKind,
    source_id: str,
    target_id: str,
    *,
    exclude_relation_id: str | None = None,
) -> tuple[str, str]:
    """Validate and normalize a relation's endpoints.

    Returns ``(source_id, target_id)`` ready for storage. Raises
    ``RelationValidationError`` for unknown ids, self-loops, duplicates, or cycles.
    """

    if kind not in ("follows", "directly_follows", "during"):
        msg = f"Unknown relation kind '{kind}'. Valid kinds: follows, directly_follows, during."
        raise RelationValidationError(msg)

    if bible.get_event(source_id) is None:
        msg = f"Unknown source event id '{source_id}'. {_event_listing(bible)}"
        raise RelationValidationError(msg)
    if bible.get_event(target_id) is None:
        msg = f"Unknown target event id '{target_id}'. {_event_listing(bible)}"
        raise RelationValidationError(msg)

    if source_id == target_id:
        msg = "An event cannot relate to itself."
        raise RelationValidationError(msg)

    key = _relation_key(kind, source_id, target_id)
    for relation in bible.event_relations:
        if relation.id == exclude_relation_id:
            continue
        existing_key = _relation_key(relation.kind, relation.source_id, relation.target_id)
        if existing_key == key:
            msg = (
                f"Duplicate relation: {kind} between "
                f"'{source_id}' and '{target_id}' already exists."
            )
            raise RelationValidationError(msg)

    if kind in DIRECTED_EVENT_RELATION_KINDS:
        adjacency = _directed_adjacency(bible)
        if _can_reach(adjacency, target_id, source_id):
            msg = (
                f"Adding directed relation '{kind}' from '{source_id}' to '{target_id}' "
                f"would create a cycle: '{target_id}' already reaches '{source_id}' "
                "through existing relations."
            )
            raise RelationValidationError(msg)

    return source_id, target_id


def relation_diagnostics(bible: StoryBible) -> list[RelationDiagnostic]:
    """Return cycle warnings for directed relations (safety net for legacy data)."""

    diagnostics: list[RelationDiagnostic] = []
    adjacency = _directed_adjacency(bible)

    directed: list[EventRelation] = [
        relation
        for relation in bible.event_relations
        if relation.kind in DIRECTED_EVENT_RELATION_KINDS
    ]

    for relation in directed:
        if _can_reach(adjacency, relation.target_id, relation.source_id):
            diagnostics.append(
                RelationDiagnostic(
                    kind="cycle",
                    relation_id=relation.id,
                    message=(
                        f"Directed relation '{relation.kind}' from "
                        f"'{relation.source_id}' to '{relation.target_id}' "
                        "participates in a directed cycle."
                    ),
                )
            )

    return diagnostics


def diagnostics_for_relation(
    bible: StoryBible,
    relation_id: str,
) -> list[RelationDiagnostic]:
    """Return diagnostics that reference a specific relation id."""

    return [item for item in relation_diagnostics(bible) if item.relation_id == relation_id]


def format_diagnostics(diagnostics: list[RelationDiagnostic]) -> str:
    if not diagnostics:
        return ""
    return "Warnings: " + "; ".join(item.message for item in diagnostics)
