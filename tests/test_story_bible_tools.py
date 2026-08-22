"""Tests for the story bible agent tools."""

from __future__ import annotations

import time

import pytest
from langchain_core.tools import ToolException

from app.graphs.jobs import get_job_manager
from app.tools import READ_ONLY_WRITING_TOOLS
from app.tools.scene import read_scene_blueprint
from app.tools.story_bible import (
    STORY_BIBLE_TOOLS,
    add_event,
    add_event_relation,
    delete_character,
    delete_event,
    delete_world_fact,
    delete_world_state_entry,
    read_character,
    read_character_arc,
    read_event,
    read_story_bible,
    read_timeline,
    read_world_fact,
    read_world_state,
    remove_event_relation,
    update_event,
    update_narrative_style,
    upsert_character,
    upsert_world_fact,
    upsert_world_state_entry,
)
from app.world.models import (
    AddIntimacy,
    AddWorldStateEntry,
    EventRelationSpec,
    Intimacy,
    IntimacyEvidence,
    Scene,
    SceneBlueprint,
    SceneCharacterStance,
    Signal,
    World,
    WorldStateEntry,
)


def _add_follows_event(title: str, after_id: str, **kwargs) -> str:
    return add_event.func(
        title,
        relations=[EventRelationSpec(kind="follows", event_id=after_id)],
        **kwargs,
    )


def _add_during_event(title: str, other_id: str, **kwargs) -> str:
    return add_event.func(
        title,
        relations=[EventRelationSpec(kind="during", event_id=other_id)],
        **kwargs,
    )


def _attach_add_intimacy(event, intimacy: Intimacy) -> None:
    event.signals[0].effects.append(AddIntimacy(intimacy=intimacy))


def test_upsert_world_fact_creates_slug_id(isolated_world: World) -> None:
    upsert_world_fact.func("The Reach", "A coastal region")

    assert isolated_world.story_bible.world_facts[0].id == "fact_the_reach"


def test_upsert_world_state_entry_creates_slug_id(isolated_world: World) -> None:
    upsert_world_state_entry.func("Drought in the valley", "pressure")

    assert isolated_world.story_bible.baseline_world_state[0].id == "wse_drought_in_the_valley"


def test_upsert_character_creates_slug_id(isolated_world: World) -> None:
    upsert_character.func(name="Mira")

    assert isolated_world.story_bible.characters[0].id == "char_mira"


def test_add_event_creates_slug_id(isolated_world: World) -> None:
    add_event.func("The Fork in the Road")

    assert isolated_world.story_bible.timeline[0].id == "event_the_fork_in_the_road"


def test_add_event_rejects_unknown_signal_character_id(isolated_world: World) -> None:
    with pytest.raises(ToolException, match="Unknown character_id 'char_missing'"):
        add_event.func(
            "Betrayal",
            signals=[Signal(character_id="char_missing", interpretation="Ignored")],
        )

    assert isolated_world.story_bible.timeline == []


def test_add_event_lists_valid_characters_on_unknown_signal_character_id(
    isolated_world: World,
) -> None:
    upsert_character.func(name="Mira")

    with pytest.raises(ToolException, match="Mira \\[char_mira\\]"):
        add_event.func(
            "Betrayal",
            signals=[Signal(character_id="char_wrong", interpretation="Ignored")],
        )


def test_update_event_rejects_unknown_signal_character_id(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    add_event.func("Betrayal")
    event = isolated_world.story_bible.timeline[0]

    with pytest.raises(ToolException, match="Unknown character_id"):
        update_event.func(
            event.id,
            signals=[Signal(character_id="char_missing", interpretation="Ignored")],
        )

    assert event.signals == []


def test_add_event_strips_agent_evidence_and_intimacy_effects(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]
    created = Intimacy(id="intim_new_debt", text="Owes Kael a debt", strength="minor")

    add_event.func(
        "A favor",
        signals=[
            Signal(
                character_id=character.id,
                interpretation="I owe him now.",
                effects=[AddIntimacy(intimacy=created)],
                evidence=[
                    IntimacyEvidence(
                        intimacy_id="intim_missing",
                        direction="supports",
                        strength=3,
                        rationale="Hallucinated id is ignored.",
                    )
                ],
            )
        ],
    )

    signal = isolated_world.story_bible.timeline[0].signals[0]
    assert signal.character_id == character.id
    assert signal.interpretation == "I owe him now."
    assert signal.evidence == []
    assert signal.effects == []


def test_read_story_bible_overview_lists_entities(isolated_world: World) -> None:
    upsert_world_fact.func("The Reach", "A coastal region")
    upsert_character.func(name="Mira")
    add_event.func("Storm hits")

    overview = read_story_bible.func()

    assert "The Reach" in overview
    assert "Mira" in overview
    assert "Storm hits" in overview
    assert "Timeline (1 events)" in overview


def test_update_narrative_style_persists(isolated_world: World) -> None:
    update_narrative_style.func(tone="Lyrical, slow-burn fantasy.", themes="Loss and renewal")

    bible = isolated_world.story_bible
    assert bible.tone == "Lyrical, slow-burn fantasy."
    assert bible.themes == "Loss and renewal"
    assert bible.premise == ""
    assert bible.writing_style == ""


def test_world_fact_crud(isolated_world: World) -> None:
    result = upsert_world_fact.func("The Reach", "A coastal region", tags=["region"])
    fact = isolated_world.story_bible.world_facts[0]
    assert "Created" in result

    upsert_world_fact.func("The Reach", "A storm-battered coastal region", fact_id=fact.id)
    assert fact.text == "A storm-battered coastal region"
    assert fact.tags == ["region"]

    detail = read_world_fact.func(fact.id)
    assert "storm-battered" in detail

    delete_world_fact.func(fact.id)
    assert isolated_world.story_bible.world_facts == []

    with pytest.raises(ToolException, match="No world fact"):
        read_world_fact.func(fact.id)


def test_baseline_world_state_crud(isolated_world: World) -> None:
    upsert_world_state_entry.func("Drought in the valley", "pressure")
    entry = isolated_world.story_bible.baseline_world_state[0]

    upsert_world_state_entry.func("Drought worsening", "pressure", entry_id=entry.id)
    assert entry.text == "Drought worsening"

    delete_world_state_entry.func(entry.id)
    assert isolated_world.story_bible.baseline_world_state == []


def test_upsert_character_creates_and_partially_updates(isolated_world: World) -> None:
    upsert_character.func(
        name="Mira",
        traits="Curious, guarded",
        intimacies=[Intimacy(text="Hungry for knowledge", strength="defining")],
    )
    character = isolated_world.story_bible.characters[0]
    assert character.identity.name == "Mira"

    upsert_character.func(
        character_id=character.id,
        intimacies=[
            Intimacy(text="Hungry for knowledge", strength="defining"),
            Intimacy(text="Wary of strangers", strength="minor"),
        ],
    )

    assert len(character.baseline_state.intimacies) == 2
    assert character.identity.traits == "Curious, guarded"
    assert character.baseline_state.intimacies[0].strength == "defining"


def test_upsert_character_rolls_back_when_save_fails(
    isolated_world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed save must not leave a phantom character behind.

    Regression test for the duplicate-character incident: a save failure after
    the in-memory append meant the character survived invisibly, so the
    model's retry created it a second time.
    """

    from app.persistence.world import get_world_store

    store = get_world_store()
    original_save = store.save
    fail_once = {"armed": True}

    def flaky_save(world: World) -> None:
        if fail_once["armed"]:
            fail_once["armed"] = False
            raise PermissionError("world.json is locked by another process")
        original_save(world)

    monkeypatch.setattr(store, "save", flaky_save)

    with pytest.raises(PermissionError):
        upsert_character.func(name="The Narrator")
    assert isolated_world.story_bible.characters == []

    upsert_character.func(name="The Narrator")

    names = [c.identity.name for c in isolated_world.story_bible.characters]
    assert names == ["The Narrator"]


def test_read_character_includes_identity_baseline_and_derived_state(
    isolated_world: World,
) -> None:
    upsert_character.func(
        name="Mira",
        intimacies=[Intimacy(text="Find the archive", strength="major")],
    )
    character = isolated_world.story_bible.characters[0]
    add_event.func(
        "Betrayal",
        signals=[Signal(character_id=character.id, interpretation="Shaken")],
    )
    _attach_add_intimacy(
        isolated_world.story_bible.timeline[0],
        Intimacy(text="Shaken", strength="minor"),
    )

    detail = read_character.func(character.id)

    assert "Mira" in detail
    assert "Find the archive" in detail
    assert "Current State (after full timeline)" in detail
    assert "Shaken" in detail
    assert "## Stance" not in detail
    assert "### State at start" not in detail


def test_read_character_scoped_replaces_full_timeline_state(isolated_world: World) -> None:
    upsert_character.func(
        name="Mira",
        intimacies=[Intimacy(text="Find the archive", strength="major")],
    )
    character = isolated_world.story_bible.characters[0]
    add_event.func(
        "Meeting",
        signals=[Signal(character_id=character.id, interpretation="A debt begins.")],
    )
    meeting = isolated_world.story_bible.timeline[0]
    _attach_add_intimacy(meeting, Intimacy(text="Owes Kael a debt", strength="major"))
    _add_follows_event(
        "Betrayal",
        meeting.id,
        signals=[Signal(character_id=character.id, interpretation="Shaken")],
    )
    _attach_add_intimacy(
        isolated_world.story_bible.timeline[1],
        Intimacy(text="Shaken", strength="minor"),
    )

    scoped = read_character.func(character.id, end_event_id=meeting.id)
    unscoped = read_character.func(character.id)

    assert "### State at start" in scoped
    assert "### Transitions" in scoped
    assert "### State at end" in scoped
    assert "Current State (after full timeline)" not in scoped
    assert "Owes Kael a debt" in scoped
    assert "Shaken" not in scoped
    assert "Current State (after full timeline)" in unscoped
    assert "Shaken" in unscoped


def test_read_character_arc_happy_path(isolated_world: World) -> None:
    upsert_character.func(
        name="Mira",
        intimacies=[Intimacy(text="Wary of outsiders", strength="minor")],
    )
    character = isolated_world.story_bible.characters[0]
    add_event.func(
        "Meeting at the gate",
        signals=[
            Signal(
                character_id=character.id,
                interpretation="This stranger may be useful.",
            )
        ],
    )
    meeting = isolated_world.story_bible.timeline[0]
    _attach_add_intimacy(meeting, Intimacy(text="Owes Kael a debt", strength="major"))

    rendered = read_character_arc.func(character.id, end_event_id=meeting.id)

    assert f"# Mira [id: {character.id}]" in rendered
    assert "### State at start" in rendered
    assert "### Transitions" in rendered
    assert "### State at end" in rendered
    assert "Wary of outsiders" in rendered
    assert "Added intimacy Owes Kael a debt (major)" in rendered
    assert "This stranger may be useful." in rendered


def test_read_character_arc_rejects_hallucinated_character_id(isolated_world: World) -> None:
    upsert_character.func(name="Mira")

    with pytest.raises(ToolException, match="Mira \\[char_mira\\]"):
        read_character_arc.func("char_missing")


def test_read_character_arc_rejects_hallucinated_event_id(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    add_event.func("Meeting")
    character = isolated_world.story_bible.characters[0]

    with pytest.raises(ToolException, match=r"Meeting \[event_meeting\]"):
        read_character_arc.func(character.id, start_event_id="event_missing")


def test_read_character_rejects_hallucinated_ids_when_scoped(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    add_event.func("Meeting")
    event = isolated_world.story_bible.timeline[0]
    character = isolated_world.story_bible.characters[0]

    with pytest.raises(ToolException, match="Mira \\[char_mira\\]"):
        read_character.func("char_missing", end_event_id=event.id)

    with pytest.raises(ToolException, match=r"Meeting \[event_meeting\]"):
        read_character.func(character.id, end_event_id="event_missing")


def test_read_character_arc_is_registered_on_tool_lists() -> None:
    assert read_character_arc in STORY_BIBLE_TOOLS
    assert read_character_arc in READ_ONLY_WRITING_TOOLS


def test_read_scene_blueprint_includes_premise_outline_and_stances(
    world_with_scene: World,
) -> None:
    upsert_character.func(name="Mira")
    character = world_with_scene.story_bible.characters[0]
    scene = world_with_scene.scenes[0]
    scene.blueprint.premise = "A tense negotiation"
    scene.generated.outline = ["Mira arrives", "Terms are refused"]
    scene.generated.stances.append(
        SceneCharacterStance(
            character_id=character.id,
            mood=["Wary"],
            intent="Secure passage",
        )
    )
    state = {"current_scene_id": scene.id}

    detail = read_scene_blueprint.func(state)

    assert "A tense negotiation" in detail
    assert "Mira arrives" in detail
    assert "Wary" in detail
    assert "Secure passage" in detail
    assert "Generated" in detail


def test_delete_character_keeps_events(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]
    add_event.func(
        "Betrayal",
        signals=[Signal(character_id=character.id, interpretation="Shaken")],
    )

    delete_character.func(character.id)

    assert isolated_world.story_bible.characters == []
    assert len(isolated_world.story_bible.timeline) == 1
    # Replay must skip the dangling signal rather than fail.
    assert "World State" in read_world_state.func()


def test_add_event_appends_in_creation_order(isolated_world: World) -> None:
    add_event.func("First")
    first = isolated_world.story_bible.timeline[0]
    _add_follows_event("Second", first.id)
    _add_follows_event("Third", first.id)

    titles = [event.title for event in isolated_world.story_bible.timeline]
    assert titles == ["First", "Second", "Third"]
    timeline = read_timeline.func()
    assert "1. First" in timeline
    assert "0 signals" in timeline
    assert "scene" not in timeline
    assert "time_passage" not in timeline


def test_add_event_rejects_unanchored_when_timeline_nonempty(isolated_world: World) -> None:
    add_event.func("First")

    with pytest.raises(ToolException, match="must link to existing ones"):
        add_event.func("Second")

    assert len(isolated_world.story_bible.timeline) == 1


def test_add_event_with_inline_relations(isolated_world: World) -> None:
    add_event.func("First")
    first = isolated_world.story_bible.timeline[0]

    add_event.func(
        "Second",
        relations=[EventRelationSpec(kind="depends_on", event_id=first.id)],
    )

    assert len(isolated_world.story_bible.timeline) == 2
    relation = isolated_world.story_bible.event_relations[0]
    assert relation.kind == "depends_on"
    assert relation.source_id == isolated_world.story_bible.timeline[1].id
    assert relation.target_id == first.id


def test_add_event_rejects_hallucinated_relation_event_id(isolated_world: World) -> None:
    add_event.func("First")

    with pytest.raises(ToolException, match="Unknown target event id"):
        add_event.func(
            "Second",
            relations=[EventRelationSpec(kind="follows", event_id="event_hallucinated")],
        )

    # The transaction must roll back: no phantom event or relation persists.
    assert [event.title for event in isolated_world.story_bible.timeline] == ["First"]
    assert isolated_world.story_bible.event_relations == []


def test_read_timeline_and_event_omit_kind(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]
    add_event.func(
        "Betrayal",
        description="An ally turns on the party.",
        signals=[Signal(character_id=character.id, interpretation="Shocked")],
    )
    event = isolated_world.story_bible.timeline[0]

    timeline = read_timeline.func()
    assert "1 signals" in timeline
    assert "scene" not in timeline
    assert "time_passage" not in timeline

    detail = read_event.func(event.id)
    assert detail.startswith(f"# Event 1: Betrayal [id: {event.id}]")
    assert "(scene)" not in detail
    assert "(time_passage)" not in detail


def test_add_and_update_event_reject_kind_parameter(isolated_world: World) -> None:
    with pytest.raises(TypeError):
        add_event.func("First", kind="scene")

    add_event.func("First")
    event = isolated_world.story_bible.timeline[0]

    with pytest.raises(TypeError):
        update_event.func(event.id, kind="time_passage")


def test_read_story_bible_overview_omits_event_kind(isolated_world: World) -> None:
    add_event.func("Storm hits")

    overview = read_story_bible.func()

    assert "Storm hits" in overview
    assert "(0 signals)" in overview
    assert "scene" not in overview
    assert "time_passage" not in overview


def test_update_event_replaces_effects(isolated_world: World) -> None:
    add_event.func("First")
    first = isolated_world.story_bible.timeline[0]
    _add_follows_event("Second", first.id)
    event = isolated_world.story_bible.timeline[1]

    update_event.func(
        event.id,
        title="Second (updated)",
        world_state_effects=[
            AddWorldStateEntry(entry=WorldStateEntry(text="Gate sealed", kind="consequence"))
        ],
    )

    timeline = isolated_world.story_bible.timeline
    assert [item.title for item in timeline] == ["First", "Second (updated)"]
    assert len(timeline[1].world_state_effects) == 1


def test_read_event_shows_effects_and_signals(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]
    add_event.func(
        "Betrayal",
        description="An ally turns on the party.",
        world_state_effects=[AddWorldStateEntry(entry=WorldStateEntry(text="Gate sealed"))],
        signals=[
            Signal(
                character_id=character.id,
                interpretation="Outsiders cannot be trusted",
                effects=[AddIntimacy(intimacy=Intimacy(text="Wary of outsiders"))],
            )
        ],
    )
    event = isolated_world.story_bible.timeline[0]
    _attach_add_intimacy(event, Intimacy(text="Wary of outsiders"))

    detail = read_event.func(event.id)

    assert "Betrayal" in detail
    assert "An ally turns on the party." in detail
    assert "add_entry" in detail
    assert "Mira" in detail
    assert "Outsiders cannot be trusted" in detail
    assert "Wary of outsiders" in detail


def test_delete_event_removes_it(isolated_world: World) -> None:
    add_event.func("Doomed event")
    event = isolated_world.story_bible.timeline[0]

    delete_event.func(event.id)

    assert isolated_world.story_bible.timeline == []
    with pytest.raises(ToolException, match="No event"):
        delete_event.func(event.id)


def test_add_event_relation_creates_edge(isolated_world: World) -> None:
    add_event.func("First")
    first = isolated_world.story_bible.timeline[0]
    _add_follows_event("Middle", first.id)
    middle = isolated_world.story_bible.timeline[1]
    _add_follows_event("Second", middle.id)
    second = isolated_world.story_bible.timeline[2]

    result = add_event_relation.func("follows", second.id, first.id)

    assert "Added follows relation" in result
    shortcut = isolated_world.story_bible.event_relations[-1]
    assert shortcut.kind == "follows"
    assert shortcut.source_id == second.id
    assert shortcut.target_id == first.id


def test_add_event_relation_rejects_cycle(isolated_world: World) -> None:
    add_event.func("First")
    first = isolated_world.story_bible.timeline[0]
    _add_follows_event("Middle", first.id)
    middle = isolated_world.story_bible.timeline[1]
    _add_follows_event("Second", middle.id)
    second = isolated_world.story_bible.timeline[2]

    with pytest.raises(ToolException, match="would create a cycle"):
        add_event_relation.func("follows", first.id, second.id)

    assert len(isolated_world.story_bible.event_relations) == 2


def test_read_timeline_lists_chronological_order(isolated_world: World) -> None:
    add_event.func("First")
    first = isolated_world.story_bible.timeline[0]
    _add_follows_event("Middle", first.id)
    middle = isolated_world.story_bible.timeline[1]
    _add_during_event("Second", middle.id)
    second = isolated_world.story_bible.timeline[2]
    add_event_relation.func("follows", first.id, second.id)

    result = read_timeline.func()

    first_pos = result.index(first.id)
    second_pos = result.index(second.id)
    assert second_pos < first_pos


def test_add_event_relation_rejects_unknown_event_id(isolated_world: World) -> None:
    add_event.func("Only event")
    event = isolated_world.story_bible.timeline[0]

    with pytest.raises(ToolException, match="Unknown target event id"):
        add_event_relation.func("follows", event.id, "event_missing")

    assert isolated_world.story_bible.event_relations == []


def test_add_event_relation_rejects_self_loop(isolated_world: World) -> None:
    add_event.func("Lonely event")
    event = isolated_world.story_bible.timeline[0]

    with pytest.raises(ToolException, match="cannot relate to itself"):
        add_event_relation.func("during", event.id, event.id)


def test_add_event_relation_rejects_duplicate_edge(isolated_world: World) -> None:
    add_event.func("First")
    first = isolated_world.story_bible.timeline[0]
    _add_follows_event("Second", first.id)
    second = isolated_world.story_bible.timeline[1]

    with pytest.raises(ToolException, match="Conflicting relation"):
        add_event_relation.func("depends_on", second.id, first.id)


def test_remove_event_relation_deletes_edge(isolated_world: World) -> None:
    add_event.func("First")
    first = isolated_world.story_bible.timeline[0]
    _add_during_event("Second", first.id)
    relation_id = isolated_world.story_bible.event_relations[0].id

    remove_event_relation.func(relation_id)

    assert isolated_world.story_bible.event_relations == []
    with pytest.raises(ToolException, match="No event relation"):
        remove_event_relation.func(relation_id)


def test_read_event_lists_relationships(isolated_world: World) -> None:
    add_event.func("First")
    first = isolated_world.story_bible.timeline[0]
    _add_follows_event("Middle", first.id)
    middle = isolated_world.story_bible.timeline[1]
    _add_follows_event("Second", middle.id)
    second = isolated_world.story_bible.timeline[2]
    add_event_relation.func("directly_follows", second.id, first.id)

    detail = read_event.func(second.id)

    assert "## Relationships" in detail
    assert "directly_follows 'First'" in detail


def test_delete_event_removes_related_edges(isolated_world: World) -> None:
    add_event.func("First")
    first = isolated_world.story_bible.timeline[0]
    _add_follows_event("Second", first.id)

    delete_event.func(first.id)

    assert isolated_world.story_bible.event_relations == []


def test_read_world_state_at_event_position(isolated_world: World) -> None:
    upsert_world_state_entry.func("Drought in the valley", "pressure")
    add_event.func(
        "Storm",
        world_state_effects=[AddWorldStateEntry(entry=WorldStateEntry(text="Roads flooded"))],
    )
    first_event = isolated_world.story_bible.timeline[0]
    _add_follows_event("Recovery", first_event.id)

    at_first = read_world_state.func(first_event.id)
    full = read_world_state.func()

    assert "after 1 of 2 events" in at_first
    assert "Roads flooded" in at_first
    assert "after 2 of 2 events" in full

    with pytest.raises(ToolException, match="Event not found"):
        read_world_state.func("missing")


def test_add_event_invoked_with_json_payload_coerces_effects(isolated_world: World) -> None:
    """The real tool-call path passes JSON dicts; the args schema must coerce them."""

    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]

    add_event.invoke(
        {
            "title": "Betrayal",
            "world_state_effects": [
                {"op": "add_entry", "entry": {"text": "Gate sealed", "kind": "consequence"}}
            ],
            "signals": [
                {
                    "character_id": character.id,
                    "interpretation": "Outsiders cannot be trusted",
                    "effects": [
                        {
                            "op": "add_intimacy",
                            "intimacy": {"text": "Wary of outsiders", "strength": "minor"},
                        }
                    ],
                }
            ],
        }
    )

    event = isolated_world.story_bible.timeline[0]
    assert isinstance(event.world_state_effects[0], AddWorldStateEntry)
    assert event.signals[0].effects == []
    assert event.signals[0].interpretation == "Outsiders cannot be trusted"


def test_write_tools_persist_to_disk(isolated_world: World, isolated_data_dir) -> None:
    import json

    upsert_character.func(name="Mira")

    raw = json.loads((isolated_data_dir / "world.json").read_text(encoding="utf-8"))
    assert raw["story_bible"]["characters"][0]["identity"]["name"] == "Mira"


def test_delete_event_prunes_blueprint_links(isolated_world: World) -> None:
    add_event.func("Arrival")
    event = isolated_world.story_bible.timeline[0]
    isolated_world.scenes.append(
        Scene(
            id="scene_arrival",
            title="The Arrival",
            blueprint=SceneBlueprint(
                premise="Hero arrives.",
                event_ids=[event.id],
                related_event_ids=[event.id],
            ),
        )
    )

    result = delete_event.func(event.id)

    assert event.id not in isolated_world.story_bible.timeline
    assert isolated_world.scenes[0].blueprint.event_ids == []
    assert isolated_world.scenes[0].blueprint.related_event_ids == []
    assert "Removed the event from 1 scene blueprint" in result


def test_read_timeline_shows_event_placement(isolated_world: World) -> None:
    add_event.func("Arrival")
    event = isolated_world.story_bible.timeline[0]

    unplaced = read_timeline.func()
    assert "unplaced" in unplaced

    isolated_world.scenes.append(
        Scene(
            id="scene_arrival",
            title="The Arrival",
            blueprint=SceneBlueprint(premise="Hero arrives.", event_ids=[event.id]),
        )
    )

    placed = read_timeline.func()
    assert "enacted by 'The Arrival' [scene id: scene_arrival]" in placed


def test_read_event_shows_placement_and_related_scenes(isolated_world: World) -> None:
    add_event.func("Background")
    background = isolated_world.story_bible.timeline[0]
    add_event.func(
        "Main beat",
        relations=[EventRelationSpec(kind="follows", event_id=background.id)],
    )
    main = isolated_world.story_bible.timeline[1]
    isolated_world.scenes.append(
        Scene(
            id="scene_main",
            title="Main Scene",
            blueprint=SceneBlueprint(
                premise="The main action.",
                event_ids=[main.id],
                related_event_ids=[background.id],
            ),
        )
    )

    background_detail = read_event.func(background.id)
    assert "## Scene Placement" in background_detail
    assert "unplaced" in background_detail
    assert "Related by scene blueprints" in background_detail
    assert "Main Scene" in background_detail

    main_detail = read_event.func(main.id)
    assert "enacted by 'Main Scene' [scene id: scene_main]" in main_detail


def test_read_timeline_warns_on_duplicate_enactment(isolated_world: World) -> None:
    add_event.func("Shared beat")
    event = isolated_world.story_bible.timeline[0]
    isolated_world.scenes.extend(
        [
            Scene(
                id="scene_a",
                title="Scene A",
                blueprint=SceneBlueprint(premise="A", event_ids=[event.id]),
            ),
            Scene(
                id="scene_b",
                title="Scene B",
                blueprint=SceneBlueprint(premise="B", event_ids=[event.id]),
            ),
        ]
    )

    timeline = read_timeline.func()

    assert "Duplicate enactment warnings" in timeline
    assert "Scene A" in timeline
    assert "Scene B" in timeline


def test_add_event_starts_interpretation_for_signal_characters(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]

    message = add_event.func(
        "A look",
        signals=[Signal(character_id=character.id, interpretation="They meant it.")],
    )

    event = isolated_world.story_bible.timeline[0]
    assert "Started intimacy interpretation for 1 character" in message
    manager = get_job_manager()
    deadline = time.time() + 2
    while manager.is_interpreting(event.id) and time.time() < deadline:
        time.sleep(0.01)
    assert any(job.kind == "intimacy_interpretation" for job in manager.finished_jobs())


def test_add_event_without_relevant_characters_is_noop(isolated_world: World) -> None:
    message = add_event.func("A look")

    assert "No relevant characters" in message
    assert not any(
        job.kind == "intimacy_interpretation" for job in get_job_manager().finished_jobs()
    )


def test_update_event_retriggers_interpretation(isolated_world: World) -> None:
    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]
    add_event.func(
        "A look",
        signals=[Signal(character_id=character.id, interpretation="Hint")],
    )
    event = isolated_world.story_bible.timeline[0]
    deadline = time.time() + 2
    manager = get_job_manager()
    while manager.is_interpreting(event.id) and time.time() < deadline:
        time.sleep(0.01)

    message = update_event.func(event.id, title="A longer look")
    assert "Started intimacy interpretation for 1 character" in message


def test_update_event_keeps_existing_evidence_when_hints_replace_signals(
    isolated_world: World,
) -> None:
    upsert_character.func(name="Mira")
    character = isolated_world.story_bible.characters[0]
    character.baseline_state.intimacies.append(
        Intimacy(id="intim_wary", text="Wary of outsiders", strength="minor")
    )
    add_event.func(
        "A look",
        signals=[Signal(character_id=character.id, interpretation="Hint")],
    )
    event = isolated_world.story_bible.timeline[0]
    entry = IntimacyEvidence(
        intimacy_id="intim_wary",
        direction="supports",
        strength=3,
        rationale="Kept until apply.",
    )
    event.signals[0].evidence.append(entry)

    update_event.func(
        event.id,
        signals=[
            Signal(
                character_id=character.id,
                interpretation="Revised hint",
                effects=[AddIntimacy(intimacy=Intimacy(text="Should not persist"))],
                evidence=[
                    IntimacyEvidence(
                        intimacy_id="intim_missing",
                        direction="contradicts",
                        strength=5,
                    )
                ],
            )
        ],
    )

    signal = isolated_world.story_bible.timeline[0].signals[0]
    assert signal.interpretation == "Revised hint"
    assert signal.evidence == [entry]
    assert signal.effects == []


def test_relation_tools_do_not_start_interpretation(
    isolated_world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[str] = []

    def spy(self, event_id: str, **kwargs):
        started.append(event_id)
        return []

    monkeypatch.setattr(
        "app.graphs.jobs.JobManager.start_event_interpretation",
        spy,
    )
    add_event.func("First")
    first = isolated_world.story_bible.timeline[0]
    add_event.func(
        "Second",
        relations=[EventRelationSpec(kind="follows", event_id=first.id)],
    )
    started.clear()
    second = isolated_world.story_bible.timeline[1]
    relation_id = isolated_world.story_bible.event_relations[0].id
    remove_event_relation.func(relation_id)
    add_event_relation.func("follows", second.id, first.id)
    assert started == []
