"""Tests for event relationship validation and diagnostics."""

from __future__ import annotations

import pytest

from app.world.models import Event, EventRelation, StoryBible
from app.world.relations import (
    RelationValidationError,
    chronological_order,
    normalize_relation,
    relation_diagnostics,
)


def _timeline_with_three_events() -> StoryBible:
    return StoryBible(
        timeline=[
            Event(id="event_a", title="Alpha"),
            Event(id="event_b", title="Beta"),
            Event(id="event_c", title="Gamma"),
        ]
    )


def test_normalize_relation_rejects_unknown_event_id() -> None:
    bible = _timeline_with_three_events()

    with pytest.raises(RelationValidationError, match="Unknown source event id"):
        normalize_relation(bible, "follows", "event_missing", "event_b")

    with pytest.raises(RelationValidationError, match="Unknown target event id"):
        normalize_relation(bible, "follows", "event_a", "event_missing")


def test_normalize_relation_rejects_self_loop() -> None:
    bible = _timeline_with_three_events()

    with pytest.raises(RelationValidationError, match="cannot relate to itself"):
        normalize_relation(bible, "follows", "event_a", "event_a")


def test_normalize_relation_rejects_duplicate_directed_edge() -> None:
    bible = _timeline_with_three_events()
    bible.event_relations.append(
        EventRelation(kind="follows", source_id="event_b", target_id="event_a")
    )

    with pytest.raises(RelationValidationError, match="Conflicting relation"):
        normalize_relation(bible, "depends_on", "event_b", "event_a")


def test_normalize_relation_rejects_directed_when_during_exists() -> None:
    bible = _timeline_with_three_events()
    bible.event_relations.append(
        EventRelation(kind="during", source_id="event_a", target_id="event_b")
    )

    with pytest.raises(RelationValidationError, match="already marked concurrent"):
        normalize_relation(bible, "follows", "event_b", "event_a")


def test_normalize_relation_rejects_during_when_directed_exists() -> None:
    bible = _timeline_with_three_events()
    bible.event_relations.append(
        EventRelation(kind="depends_on", source_id="event_b", target_id="event_a")
    )

    with pytest.raises(RelationValidationError, match="already have a directed edge"):
        normalize_relation(bible, "during", "event_a", "event_b")


def test_normalize_relation_treats_during_as_unordered_for_dedup() -> None:
    bible = _timeline_with_three_events()
    bible.event_relations.append(
        EventRelation(kind="during", source_id="event_a", target_id="event_b")
    )

    with pytest.raises(RelationValidationError, match="Duplicate relation"):
        normalize_relation(bible, "during", "event_b", "event_a")


def test_chronological_order_follows_directed_edges_over_creation_order() -> None:
    bible = _timeline_with_three_events()
    bible.event_relations.append(
        EventRelation(kind="follows", source_id="event_a", target_id="event_b")
    )

    ordered_ids = [event.id for event in chronological_order(bible)]

    assert ordered_ids == ["event_b", "event_a", "event_c"]


def test_chronological_order_uses_creation_order_as_tie_breaker() -> None:
    bible = _timeline_with_three_events()

    ordered_ids = [event.id for event in chronological_order(bible)]

    assert ordered_ids == ["event_a", "event_b", "event_c"]


def test_chronological_order_treats_depends_on_as_directed() -> None:
    bible = _timeline_with_three_events()
    bible.event_relations.append(
        EventRelation(kind="depends_on", source_id="event_c", target_id="event_a")
    )

    ordered_ids = [event.id for event in chronological_order(bible)]

    assert ordered_ids.index("event_a") < ordered_ids.index("event_c")


def test_normalize_relation_rejects_cycle() -> None:
    bible = StoryBible(
        timeline=[
            Event(id="event_a", title="Alpha"),
            Event(id="event_b", title="Beta"),
        ]
    )
    bible.event_relations.append(
        EventRelation(kind="follows", source_id="event_a", target_id="event_b")
    )

    with pytest.raises(RelationValidationError, match="would create a cycle"):
        normalize_relation(bible, "depends_on", "event_b", "event_a")


def test_relation_diagnostics_detects_cycle() -> None:
    bible = StoryBible(
        timeline=[
            Event(id="event_a", title="Alpha"),
            Event(id="event_b", title="Beta"),
        ]
    )
    bible.event_relations.append(
        EventRelation(id="rel_ab", kind="follows", source_id="event_a", target_id="event_b")
    )
    bible.event_relations.append(
        EventRelation(id="rel_ba", kind="follows", source_id="event_b", target_id="event_a")
    )

    diagnostics = relation_diagnostics(bible)

    cycle_ids = {item.relation_id for item in diagnostics if item.kind == "cycle"}
    assert cycle_ids == {"rel_ab", "rel_ba"}


def test_relation_diagnostics_flags_unanchored_events() -> None:
    bible = _timeline_with_three_events()
    bible.event_relations.append(
        EventRelation(kind="follows", source_id="event_b", target_id="event_a")
    )

    diagnostics = relation_diagnostics(bible)

    unanchored = [item for item in diagnostics if item.kind == "unanchored"]
    assert len(unanchored) == 1
    assert unanchored[0].event_id == "event_c"
