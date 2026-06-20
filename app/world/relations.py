"""Event relationship validation and derived diagnostics.

Relations are stored separately from the canonical timeline list; this module
validates structural constraints and computes order-conflict and cycle warnings.
See ``docs/story_bible_model.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.world.models import (
    DIRECTED_EVENT_RELATION_KINDS,
    EventRelation,
    EventRelationKind,
    StoryBible,
)

DiagnosticKind = Literal["order_conflict", "cycle"]


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
    ``RelationValidationError`` for unknown ids, self-loops, or duplicates.
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

    return source_id, target_id


def relation_diagnostics(bible: StoryBible) -> list[RelationDiagnostic]:
    """Return order-conflict and cycle warnings for directed relations."""

    diagnostics: list[RelationDiagnostic] = []
    index_by_id = {event.id: index for index, event in enumerate(bible.timeline)}

    directed: list[EventRelation] = [
        relation
        for relation in bible.event_relations
        if relation.kind in DIRECTED_EVENT_RELATION_KINDS
    ]

    for relation in directed:
        source_index = index_by_id.get(relation.source_id)
        target_index = index_by_id.get(relation.target_id)
        if source_index is None or target_index is None:
            continue
        if source_index <= target_index:
            diagnostics.append(
                RelationDiagnostic(
                    kind="order_conflict",
                    relation_id=relation.id,
                    message=(
                        f"Relation '{relation.kind}' from "
                        f"'{relation.source_id}' to '{relation.target_id}' "
                        f"conflicts with timeline list order: the follower should come "
                        f"after the event it follows "
                        f"(positions {source_index + 1} and {target_index + 1})."
                    ),
                )
            )

    adjacency: dict[str, list[str]] = {event.id: [] for event in bible.timeline}
    for relation in directed:
        if relation.source_id in adjacency and relation.target_id in adjacency:
            adjacency[relation.source_id].append(relation.target_id)

    def can_reach(start: str, goal: str) -> bool:
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

    for relation in directed:
        if can_reach(relation.target_id, relation.source_id):
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
