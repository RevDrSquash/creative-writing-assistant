"""Event relationship validation and derived diagnostics.

Relations define chronology (with creation order in the timeline list as a
tie-breaker); this module validates structural constraints, computes canonical
order, and surfaces cycle and unanchored-event warnings. See
``docs/story_bible_model.md``.
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

DiagnosticKind = Literal["cycle", "unanchored"]


@dataclass(frozen=True)
class RelationDiagnostic:
    """A derived warning about an event relationship or anchoring."""

    kind: DiagnosticKind
    message: str
    relation_id: str = ""
    event_id: str = ""


class RelationValidationError(ValueError):
    """Raised when a relation fails structural validation."""


def _event_listing(bible: StoryBible) -> str:
    if not bible.timeline:
        return "No events exist yet; create events first."
    listing = ", ".join(f"{event.title or 'Untitled'} [{event.id}]" for event in bible.timeline)
    return f"Valid events: {listing}"


def _unordered_pair(source_id: str, target_id: str) -> tuple[str, str]:
    return tuple(sorted((source_id, target_id)))


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


def _relation_conflicts(
    bible: StoryBible,
    kind: EventRelationKind,
    source_id: str,
    target_id: str,
    *,
    exclude_relation_id: str | None = None,
) -> str | None:
    """Return an error message when ``kind`` conflicts with an existing relation."""

    new_pair = _unordered_pair(source_id, target_id)
    for relation in bible.event_relations:
        if relation.id == exclude_relation_id:
            continue
        existing_pair = _unordered_pair(relation.source_id, relation.target_id)
        if existing_pair != new_pair:
            continue

        if kind == "during" and relation.kind == "during":
            return (
                f"Duplicate relation: during between '{source_id}' and '{target_id}' "
                "already exists."
            )
        if kind in DIRECTED_EVENT_RELATION_KINDS and relation.kind in DIRECTED_EVENT_RELATION_KINDS:
            if relation.source_id == source_id and relation.target_id == target_id:
                return (
                    f"Conflicting relation: a directed edge from '{source_id}' to "
                    f"'{target_id}' already exists ({relation.kind}). "
                    "Use one directed kind per ordered pair."
                )
        if kind == "during" and relation.kind in DIRECTED_EVENT_RELATION_KINDS:
            return (
                f"Conflicting relation: '{source_id}' and '{target_id}' already have a "
                f"directed edge ({relation.kind}); cannot also mark them concurrent."
            )
        if kind in DIRECTED_EVENT_RELATION_KINDS and relation.kind == "during":
            return (
                f"Conflicting relation: '{source_id}' and '{target_id}' are already "
                "marked concurrent (during); cannot also add a directed edge."
            )
    return None


def scenario_ids(bible: StoryBible) -> dict[str, str]:
    """Map each event to a scenario id.

    A scenario is a connected component of ``directly_follows`` edges treated as
    undirected. Events with no such edge are their own scenario. The scenario id
    is the lexicographically smallest event id in the component.
    """

    parent = {event.id: event.id for event in bible.timeline}

    def find(event_id: str) -> str:
        while parent[event_id] != event_id:
            parent[event_id] = parent[parent[event_id]]
            event_id = parent[event_id]
        return event_id

    def union(left: str, right: str) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    for relation in bible.event_relations:
        if relation.kind != "directly_follows":
            continue
        if relation.source_id in parent and relation.target_id in parent:
            union(relation.source_id, relation.target_id)

    members: dict[str, list[str]] = {}
    for event_id in parent:
        members.setdefault(find(event_id), []).append(event_id)
    return {event_id: min(group) for group in members.values() for event_id in group}


def chronological_order(bible: StoryBible) -> list[Event]:
    """Return events in canonical chronological order.

    Directed edges force ``target`` (earlier) before ``source`` (later). Among
    events with no ordering constraint, timeline creation order is the tie-breaker.
    Residual cycles (legacy data) are appended in creation order.
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

    if kind not in ("follows", "directly_follows", "depends_on", "during"):
        msg = (
            f"Unknown relation kind '{kind}'. Valid kinds: follows, directly_follows, "
            "depends_on, during."
        )
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

    conflict = _relation_conflicts(
        bible,
        kind,
        source_id,
        target_id,
        exclude_relation_id=exclude_relation_id,
    )
    if conflict:
        raise RelationValidationError(conflict)

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


def _unanchored_event_diagnostics(bible: StoryBible) -> list[RelationDiagnostic]:
    if len(bible.timeline) <= 1:
        return []

    connected: set[str] = set()
    for relation in bible.event_relations:
        connected.add(relation.source_id)
        connected.add(relation.target_id)

    diagnostics: list[RelationDiagnostic] = []
    for event in bible.timeline:
        if event.id in connected:
            continue
        diagnostics.append(
            RelationDiagnostic(
                kind="unanchored",
                event_id=event.id,
                message=(
                    f"Event '{event.title or 'Untitled'}' [{event.id}] has no "
                    "relationships to other events."
                ),
            )
        )
    return diagnostics


def relation_diagnostics(bible: StoryBible) -> list[RelationDiagnostic]:
    """Return cycle warnings and unanchored-event warnings."""

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

    diagnostics.extend(_unanchored_event_diagnostics(bible))
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
