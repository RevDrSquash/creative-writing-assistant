"""Tests for cross-scene continuity context selection and formatting."""

from __future__ import annotations

from app.world.models import Event, EventRelation, SceneBlueprint, World
from app.world.scene import create_scene, set_scene_text
from app.world.scene_context import (
    PREVIOUS_SCENE_PROSE_CAP,
    SceneContinuityContext,
    SceneSnapshot,
    build_scene_continuity_context,
    format_continuity_context,
)
from app.world.store import get_world, world_transaction


def _neighbor_scene_ids(context: SceneContinuityContext) -> set[str]:
    ids: set[str] = set()
    if context.previous is not None:
        ids.add(context.previous.scene_id)
    if context.next is not None:
        ids.add(context.next.scene_id)
    ids.update(snapshot.scene_id for snapshot in context.related)
    return ids


def _scene_with_blueprint(
    title: str,
    *,
    event_ids: list[str] | None = None,
    related_event_ids: list[str] | None = None,
    markdown: str = "",
    summary: str = "",
) -> str:
    scene = create_scene(title, summary=summary)
    scene.blueprint = SceneBlueprint(
        premise="Premise",
        purpose="Purpose",
        event_ids=event_ids or [],
        related_event_ids=related_event_ids or [],
    )
    if markdown:
        set_scene_text(scene.id, markdown)
    return scene.id


def _seed_events_with_relations() -> tuple[str, str, str]:
    with world_transaction() as world:
        world.story_bible.timeline = [
            Event(id="event_a", title="Alpha"),
            Event(id="event_b", title="Beta"),
            Event(id="event_c", title="Gamma"),
        ]
        world.story_bible.event_relations = [
            EventRelation(kind="follows", source_id="event_b", target_id="event_a"),
            EventRelation(kind="directly_follows", source_id="event_c", target_id="event_b"),
        ]
    return "event_a", "event_b", "event_c"


def test_build_context_selects_event_linked_previous_and_next(isolated_world: World) -> None:
    event_a, event_b, event_c = _seed_events_with_relations()
    scene_one = _scene_with_blueprint("Scene One", event_ids=[event_a], markdown="First prose.")
    scene_two = _scene_with_blueprint("Scene Two", event_ids=[event_b], markdown="Second prose.")
    scene_three = _scene_with_blueprint("Scene Three", event_ids=[event_c], markdown="Third prose.")

    context = build_scene_continuity_context(get_world(), scene_two)

    assert context.previous is not None
    assert context.previous.scene_id == scene_one
    assert context.previous.markdown == "First prose."
    assert context.next is not None
    assert context.next.scene_id == scene_three
    assert context.next.markdown == ""


def test_build_context_falls_back_to_list_order_without_event_links(isolated_world: World) -> None:
    scene_one = _scene_with_blueprint("Scene One", markdown="List prose one.")
    scene_two = _scene_with_blueprint("Scene Two", markdown="List prose two.")

    context = build_scene_continuity_context(get_world(), scene_two)

    assert context.previous is not None
    assert context.previous.scene_id == scene_one
    assert context.previous.markdown == "List prose one."
    assert context.next is None


def test_build_context_includes_directly_follows_related_scene(isolated_world: World) -> None:
    event_a, event_b, event_c = _seed_events_with_relations()
    _scene_with_blueprint("Earlier", event_ids=[event_a])
    target = _scene_with_blueprint("Target", event_ids=[event_b])
    next_scene = _scene_with_blueprint(
        "Tight follow", event_ids=[event_c], summary="Immediate next."
    )

    context = build_scene_continuity_context(get_world(), target)

    assert context.next is not None
    assert context.next.scene_id == next_scene
    assert context.next.summary == "Immediate next."
    assert {snapshot.scene_id for snapshot in context.related} == set()


def test_build_context_includes_during_related_scene(isolated_world: World) -> None:
    with world_transaction() as world:
        world.story_bible.timeline = [
            Event(id="event_a", title="Alpha"),
            Event(id="event_b", title="Beta"),
            Event(id="event_c", title="Gamma"),
            Event(id="event_d", title="Delta"),
        ]
        world.story_bible.event_relations = [
            EventRelation(kind="follows", source_id="event_c", target_id="event_a"),
            EventRelation(kind="during", source_id="event_c", target_id="event_b"),
            EventRelation(kind="follows", source_id="event_d", target_id="event_c"),
        ]

    _scene_with_blueprint("Earlier", event_ids=["event_a"])
    related = _scene_with_blueprint("Concurrent", event_ids=["event_b"], summary="Same moment.")
    target = _scene_with_blueprint("Target", event_ids=["event_c"])
    next_scene = _scene_with_blueprint("Later", event_ids=["event_d"], summary="After target.")

    context = build_scene_continuity_context(get_world(), target)

    assert related in _neighbor_scene_ids(context)
    assert context.next is not None
    assert context.next.scene_id == next_scene


def test_build_context_includes_scenes_for_related_event_ids(isolated_world: World) -> None:
    with world_transaction() as world:
        world.story_bible.timeline = [
            Event(id="event_a", title="Alpha"),
            Event(id="event_b", title="Beta"),
            Event(id="event_c", title="Gamma"),
            Event(id="event_d", title="Delta"),
        ]
        world.story_bible.event_relations = [
            EventRelation(kind="follows", source_id="event_c", target_id="event_a"),
            EventRelation(kind="follows", source_id="event_d", target_id="event_c"),
        ]

    _scene_with_blueprint("Earlier", event_ids=["event_a"])
    related = _scene_with_blueprint("Context only", event_ids=["event_b"], summary="Background.")
    target = _scene_with_blueprint(
        "Target",
        event_ids=["event_c"],
        related_event_ids=["event_b"],
    )
    next_scene = _scene_with_blueprint("Later", event_ids=["event_d"], summary="After target.")

    context = build_scene_continuity_context(get_world(), target)

    assert related in _neighbor_scene_ids(context)
    assert context.next is not None
    assert context.next.scene_id == next_scene


def test_build_context_skips_dangling_event_ids(isolated_world: World) -> None:
    scene_one = _scene_with_blueprint("Scene One", event_ids=["event_missing"])
    scene_two = _scene_with_blueprint("Scene Two")

    context = build_scene_continuity_context(get_world(), scene_two)

    assert context.previous is not None
    assert context.previous.scene_id == scene_one


def test_build_context_empty_for_unknown_scene(isolated_world: World) -> None:
    context = build_scene_continuity_context(get_world(), "scene_missing")
    assert context == SceneContinuityContext()


def test_build_context_empty_for_first_scene(isolated_world: World) -> None:
    scene_id = _scene_with_blueprint("Only scene")
    context = build_scene_continuity_context(get_world(), scene_id)
    assert context.previous is None
    assert context.next is None
    assert context.related == []


def test_format_context_includes_previous_prose_and_related_summaries() -> None:
    context = SceneContinuityContext(
        previous=SceneSnapshot(
            scene_id="scene_prev",
            title="Previous",
            summary="Ended tense.",
            markdown="She closed the door.",
        ),
        next=SceneSnapshot(
            scene_id="scene_next",
            title="Next",
            summary="Opens elsewhere.",
        ),
        related=[
            SceneSnapshot(
                scene_id="scene_related",
                title="Related",
                summary="Parallel thread.",
            )
        ],
    )

    formatted = format_continuity_context(context)

    assert "## Surrounding scene context" in formatted
    assert "Maintain continuity with the surrounding scenes" in formatted
    assert "### Previous scene (full prose)" in formatted
    assert "She closed the door." in formatted
    assert "### Next scene" in formatted
    assert "Opens elsewhere." in formatted
    assert "### Related scene" in formatted
    assert "Parallel thread." in formatted


def test_format_context_empty_when_no_neighbors() -> None:
    assert format_continuity_context(SceneContinuityContext()) == ""


def test_previous_scene_prose_is_capped(isolated_world: World) -> None:
    _scene_with_blueprint("Scene One", markdown="x" * (PREVIOUS_SCENE_PROSE_CAP + 500))
    scene_two = _scene_with_blueprint("Scene Two")

    context = build_scene_continuity_context(get_world(), scene_two)

    assert context.previous is not None
    assert len(context.previous.markdown) <= PREVIOUS_SCENE_PROSE_CAP + len(
        "\n\n[... truncated ...]"
    )
    assert context.previous.markdown.endswith("[... truncated ...]")
