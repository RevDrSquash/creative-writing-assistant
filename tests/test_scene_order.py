"""Tests for deterministic scene generation ordering."""

from __future__ import annotations

from datetime import datetime, timezone

from app.world.models import (
    Event,
    EventRelation,
    Scene,
    SceneBlueprint,
    SceneGenerated,
    StoryBible,
    World,
    blueprint_fingerprint,
)
from app.world.scene_order import build_scene_generation_plan


def _world_with_events(*titles: str) -> World:
    timeline = [Event(id=f"event_{title.lower()}", title=title) for title in titles]
    return World(story_bible=StoryBible(timeline=list(timeline)))


def _scene(
    scene_id: str,
    title: str,
    *,
    event_ids: list[str] | None = None,
    related_event_ids: list[str] | None = None,
    premise: str = "A premise",
    generated: bool = False,
) -> Scene:
    blueprint = SceneBlueprint(
        premise=premise,
        event_ids=event_ids or [],
        related_event_ids=related_event_ids or [],
    )
    return Scene(
        id=scene_id,
        title=title,
        blueprint=blueprint,
        generated=SceneGenerated(
            generated_at=datetime.now(timezone.utc) if generated else None,
            blueprint_fingerprint=blueprint_fingerprint(blueprint) if generated else "",
        ),
    )


def test_linear_chain_gives_sequential_prerequisites() -> None:
    world = _world_with_events("A", "B", "C")
    world.story_bible.event_relations.extend(
        [
            EventRelation(kind="follows", source_id="event_b", target_id="event_a"),
            EventRelation(kind="follows", source_id="event_c", target_id="event_b"),
        ]
    )
    world.scenes = [
        _scene("scene_c", "C", event_ids=["event_c"]),
        _scene("scene_a", "A", event_ids=["event_a"]),
        _scene("scene_b", "B", event_ids=["event_b"]),
    ]

    plan = build_scene_generation_plan(world)
    ids = [item.scene_id for item in plan.items]
    assert ids == ["scene_a", "scene_b", "scene_c"]

    by_id = {item.scene_id: item for item in plan.items}
    assert by_id["scene_a"].prerequisite_scene_ids == ()
    assert by_id["scene_b"].prerequisite_scene_ids == ("scene_a",)
    assert by_id["scene_c"].prerequisite_scene_ids == ("scene_a", "scene_b")


def test_during_events_have_no_dependency_edge() -> None:
    world = _world_with_events("A", "B")
    world.story_bible.event_relations.append(
        EventRelation(kind="during", source_id="event_a", target_id="event_b")
    )
    world.scenes = [
        _scene("scene_a", "A", event_ids=["event_a"]),
        _scene("scene_b", "B", event_ids=["event_b"]),
    ]

    plan = build_scene_generation_plan(world)
    by_id = {item.scene_id: item for item in plan.items}
    assert by_id["scene_a"].prerequisite_scene_ids == ()
    assert by_id["scene_b"].prerequisite_scene_ids == ()


def test_unrelated_events_have_no_dependency_edge() -> None:
    world = _world_with_events("A", "B")
    world.scenes = [
        _scene("scene_a", "A", event_ids=["event_a"]),
        _scene("scene_b", "B", event_ids=["event_b"]),
    ]

    plan = build_scene_generation_plan(world)
    by_id = {item.scene_id: item for item in plan.items}
    assert by_id["scene_a"].prerequisite_scene_ids == ()
    assert by_id["scene_b"].prerequisite_scene_ids == ()


def test_related_event_creates_dependency() -> None:
    world = _world_with_events("A", "B")
    world.scenes = [
        _scene("scene_a", "A", event_ids=["event_a"]),
        _scene(
            "scene_b",
            "B",
            event_ids=["event_b"],
            related_event_ids=["event_a"],
        ),
    ]

    plan = build_scene_generation_plan(world)
    by_id = {item.scene_id: item for item in plan.items}
    assert by_id["scene_b"].prerequisite_scene_ids == ("scene_a",)


def test_non_generatable_scenes_flagged() -> None:
    world = _world_with_events("A", "B")
    world.scenes = [
        _scene("scene_a", "A", event_ids=["event_a"], premise=""),
        _scene("scene_b", "B", event_ids=[], premise="Has premise"),
    ]

    plan = build_scene_generation_plan(world)
    by_id = {item.scene_id: item for item in plan.items}
    assert by_id["scene_a"].generatable is False
    assert by_id["scene_a"].not_generatable_reason == "Missing premise"
    assert by_id["scene_a"].selected_by_default is False
    assert by_id["scene_b"].generatable is False
    assert by_id["scene_b"].not_generatable_reason == "No enacted events"


def test_already_generated_defaults_unselected() -> None:
    world = _world_with_events("A", "B")
    world.scenes = [
        _scene("scene_a", "A", event_ids=["event_a"], generated=True),
        _scene("scene_b", "B", event_ids=["event_b"], generated=False),
    ]

    plan = build_scene_generation_plan(world)
    by_id = {item.scene_id: item for item in plan.items}
    assert by_id["scene_a"].selected_by_default is False
    assert by_id["scene_a"].status == "up to date"
    assert by_id["scene_b"].selected_by_default is True
    assert by_id["scene_b"].status == "never generated"


def test_display_order_is_deterministic() -> None:
    world = _world_with_events("A", "B", "C")
    world.story_bible.event_relations.append(
        EventRelation(kind="follows", source_id="event_c", target_id="event_a")
    )
    world.scenes = [
        _scene("scene_c", "C", event_ids=["event_c"]),
        _scene("scene_b", "B", event_ids=["event_b"]),
        _scene("scene_a", "A", event_ids=["event_a"]),
    ]

    first = [item.scene_id for item in build_scene_generation_plan(world).items]
    second = [item.scene_id for item in build_scene_generation_plan(world).items]
    assert first == second == ["scene_a", "scene_b", "scene_c"]
