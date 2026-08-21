"""Tests for scene/event link helpers and UI option filtering."""

from __future__ import annotations

from app.ui.components.story_bible_forms import _enacted_event_select_options
from app.world.models import Event, Scene, SceneBlueprint, World
from app.world.scene import enacting_scenes, prune_event_links


def test_enacting_scenes_returns_matching_scenes(isolated_world: World) -> None:
    event = Event(id="event_a", title="Beat A")
    isolated_world.story_bible.timeline.append(event)
    isolated_world.scenes.append(
        Scene(
            id="scene_a",
            title="Scene A",
            blueprint=SceneBlueprint(event_ids=["event_a"]),
        )
    )

    scenes = enacting_scenes(isolated_world, "event_a")

    assert len(scenes) == 1
    assert scenes[0].id == "scene_a"


def test_prune_event_links_removes_ids_from_all_blueprints(isolated_world: World) -> None:
    event = Event(id="event_a", title="Beat A")
    isolated_world.story_bible.timeline.append(event)
    isolated_world.scenes.append(
        Scene(
            id="scene_a",
            title="Scene A",
            blueprint=SceneBlueprint(
                event_ids=["event_a"],
                related_event_ids=["event_a"],
            ),
        )
    )

    affected = prune_event_links(isolated_world, "event_a")

    assert affected == ["scene_a"]
    assert isolated_world.scenes[0].blueprint.event_ids == []
    assert isolated_world.scenes[0].blueprint.related_event_ids == []


def test_enacted_event_select_options_excludes_elsewhere_enacted_events(isolated_world: World) -> None:
    event_a = Event(id="event_a", title="Beat A")
    event_b = Event(id="event_b", title="Beat B")
    isolated_world.story_bible.timeline.extend([event_a, event_b])
    scene_one = Scene(
        id="scene_one",
        title="Scene One",
        blueprint=SceneBlueprint(event_ids=["event_a"]),
    )
    scene_two = Scene(
        id="scene_two",
        title="Scene Two",
        blueprint=SceneBlueprint(event_ids=[]),
    )
    isolated_world.scenes.extend([scene_one, scene_two])

    options = _enacted_event_select_options(isolated_world.story_bible, scene_two)

    assert "event_a" not in options
    assert "event_b" in options
