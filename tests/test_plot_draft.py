"""Tests for the PlotDraft sandbox: purity, backtrack, insert, staleness, commit."""

from __future__ import annotations

import pytest

from app.world.draft import DraftCommitError, PlotDraft
from app.world.models import (
    Character,
    CharacterBaselineState,
    CharacterIdentity,
    Event,
    EventRelation,
    EventRelationSpec,
    Intimacy,
    IntimacyEvidence,
    Scene,
    SceneBlueprint,
    Signal,
    StoryBible,
    World,
)
from app.world.relations import RelationValidationError
from app.world.store import save_world


def _mira_signal(strength: int = 2) -> Signal:
    return Signal(
        character_id="char_mira",
        interpretation="A hint",
        evidence=[
            IntimacyEvidence(intimacy_id="intim_wary", direction="supports", strength=strength)
        ],
    )


def _bible() -> StoryBible:
    """Three events: gate -> meal (directly_follows), watch follows meal."""

    return StoryBible(
        characters=[
            Character(
                id="char_mira",
                identity=CharacterIdentity(name="Mira"),
                baseline_state=CharacterBaselineState(
                    intimacies=[
                        Intimacy(id="intim_wary", text="Wary of outsiders", strength="minor")
                    ]
                ),
            ),
            Character(id="char_kael", identity=CharacterIdentity(name="Kael")),
        ],
        timeline=[
            Event(id="evt_gate", title="The gate", signals=[_mira_signal()]),
            Event(id="evt_meal", title="The meal", signals=[_mira_signal()]),
            Event(
                id="evt_watch",
                title="The watch",
                signals=[Signal(character_id="char_kael", interpretation="Quiet night")],
            ),
        ],
        event_relations=[
            EventRelation(
                id="rel_meal",
                kind="directly_follows",
                source_id="evt_meal",
                target_id="evt_gate",
            ),
            EventRelation(
                id="rel_watch", kind="follows", source_id="evt_watch", target_id="evt_meal"
            ),
        ],
    )


def _seed_live_world(world: World) -> StoryBible:
    bible = _bible()
    world.story_bible.characters = bible.characters
    world.story_bible.timeline = bible.timeline
    world.story_bible.event_relations = bible.event_relations
    save_world()
    return world.story_bible


# --------------------------------------------------------------------- purity


def test_draft_operations_do_not_touch_base_bible() -> None:
    base = _bible()
    before = base.model_dump(mode="json")
    draft = PlotDraft(base)

    draft.add_event(
        "The alley",
        description="A shortcut goes wrong.",
        relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
        signals=[Signal(character_id="char_mira", interpretation="Trouble follows me.")],
    )
    draft.update_event("evt_gate", description="Rewritten opening.")
    draft.delete_event("evt_watch")

    assert base.model_dump(mode="json") == before
    assert len(draft.steps) == 3


def test_reads_target_the_draft_copy() -> None:
    draft = PlotDraft(_bible())
    draft.add_event(
        "The alley",
        relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
    )

    order = [event.id for event in draft.chronology()]
    assert order[-1].startswith("event_the_alley")
    derived = draft.derived_state()
    assert derived.events_applied == 4
    ranks = draft.explain("char_mira")
    assert "intim_wary" in ranks


# ----------------------------------------------------------------- validation


def test_add_event_requires_relations_when_timeline_not_empty() -> None:
    draft = PlotDraft(_bible())
    with pytest.raises(ValueError, match="Valid events"):
        draft.add_event("Floating event")
    assert draft.steps == ()


def test_add_event_restores_draft_when_relation_is_invalid() -> None:
    draft = PlotDraft(_bible())
    before = draft.bible.model_dump(mode="json")
    with pytest.raises(RelationValidationError):
        draft.add_event(
            "The alley",
            relations=[EventRelationSpec(kind="follows", event_id="evt_hallucinated")],
        )
    assert draft.bible.model_dump(mode="json") == before
    assert draft.steps == ()


def test_update_event_unknown_id_lists_valid_options() -> None:
    draft = PlotDraft(_bible())
    with pytest.raises(ValueError, match="Valid events"):
        draft.update_event("evt_hallucinated", title="Nope")


def test_unknown_signal_character_rejected_with_valid_options() -> None:
    draft = PlotDraft(_bible())
    with pytest.raises(ValueError, match="Valid characters"):
        draft.add_event(
            "The alley",
            relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
            signals=[Signal(character_id="char_ghost", interpretation="Boo")],
        )


# ------------------------------------------------------------- insert between


def test_insert_between_rewires_atomically() -> None:
    draft = PlotDraft(_bible())
    event = draft.insert_event_between(
        "The alley",
        earlier_event_id="evt_gate",
        later_event_id="evt_meal",
    )

    relation_ids = {relation.id for relation in draft.bible.event_relations}
    assert "rel_meal" not in relation_ids
    pairs = {
        (relation.kind, relation.source_id, relation.target_id)
        for relation in draft.bible.event_relations
    }
    assert ("directly_follows", event.id, "evt_gate") in pairs
    assert ("directly_follows", "evt_meal", event.id) in pairs
    order = [item.id for item in draft.chronology()]
    assert order.index("evt_gate") < order.index(event.id) < order.index("evt_meal")


def test_insert_between_requires_directly_linked_anchors() -> None:
    draft = PlotDraft(_bible())
    before = draft.bible.model_dump(mode="json")
    with pytest.raises(ValueError, match="not directly linked"):
        draft.insert_event_between(
            "The alley",
            earlier_event_id="evt_gate",
            later_event_id="evt_watch",
        )
    assert draft.bible.model_dump(mode="json") == before
    assert draft.steps == ()


# ------------------------------------------------------------------ backtrack


def test_truncate_to_restores_earlier_step_state() -> None:
    draft = PlotDraft(_bible())
    initial = draft.bible.model_dump(mode="json")
    draft.update_event("evt_gate", description="Step one.")
    after_step_one = draft.bible.model_dump(mode="json")
    draft.add_event(
        "The alley",
        relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
    )
    assert len(draft.bible.timeline) == 4

    draft.truncate_to(1)

    assert draft.bible.model_dump(mode="json") == after_step_one
    assert len(draft.steps) == 1

    draft.truncate_to(0)
    assert draft.bible.model_dump(mode="json") == initial
    assert draft.steps == ()
    assert draft.stale_event_ids == frozenset()


def test_truncate_to_rejects_out_of_range() -> None:
    draft = PlotDraft(_bible())
    with pytest.raises(ValueError, match="between 0 and 0"):
        draft.truncate_to(1)


# ---------------------------------------------------------------- stale ripple


def test_insert_flags_scenario_chain_but_not_unrelated_downstream() -> None:
    draft = PlotDraft(_bible())
    draft.insert_event_between(
        "The alley",
        earlier_event_id="evt_gate",
        later_event_id="evt_meal",
    )

    # evt_meal's directly_follows scenario changed; evt_watch is a different
    # character in an unchanged scenario and stays fresh.
    assert "evt_meal" in draft.stale_event_ids
    assert "evt_watch" not in draft.stale_event_ids
    assert "evt_gate" not in draft.stale_event_ids


def test_mid_timeline_edit_flags_downstream_overlapping_events_only() -> None:
    draft = PlotDraft(_bible())
    draft.update_event("evt_gate", description="Rewritten opening.")

    assert "evt_meal" in draft.stale_event_ids  # same character and intimacy
    assert "evt_watch" not in draft.stale_event_ids  # different character, no overlap
    assert draft.steps[0].stale_added == ("evt_meal",)


def test_appending_an_event_flags_nothing() -> None:
    draft = PlotDraft(_bible())
    draft.add_event(
        "The alley",
        relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
        signals=[_mira_signal()],
    )
    assert draft.stale_event_ids == frozenset()


def test_relation_rewire_flags_reordered_endpoint() -> None:
    draft = PlotDraft(_bible())
    draft.remove_relation("rel_watch")
    draft.add_relation("follows", "evt_watch", "evt_gate")

    # evt_watch kept its chronological slot and scenario through both edits.
    assert "evt_watch" not in draft.stale_event_ids

    # Reordering evt_meal behind evt_watch moves it: flagged.
    draft.remove_relation("rel_meal")
    draft.add_relation("follows", "evt_meal", "evt_watch")
    assert "evt_meal" in draft.stale_event_ids


def test_mark_interpreted_clears_stale_flag() -> None:
    draft = PlotDraft(_bible())
    draft.update_event("evt_gate", description="Rewritten opening.")
    assert "evt_meal" in draft.stale_event_ids

    draft.mark_interpreted("evt_meal")
    assert "evt_meal" not in draft.stale_event_ids


def test_delete_event_prunes_relations_and_stale_entries() -> None:
    draft = PlotDraft(_bible())
    draft.update_event("evt_gate", description="Rewritten opening.")
    assert "evt_meal" in draft.stale_event_ids

    draft.delete_event("evt_meal")

    assert all(
        "evt_meal" not in (relation.source_id, relation.target_id)
        for relation in draft.bible.event_relations
    )
    assert "evt_meal" not in draft.stale_event_ids


# --------------------------------------------------------------------- commit


def test_commit_requires_story_bible_claim(isolated_world: World) -> None:
    bible = _seed_live_world(isolated_world)
    draft = PlotDraft(bible)
    draft.update_event("evt_gate", description="Drafted change.")
    before = isolated_world.model_dump(mode="json")

    with pytest.raises(DraftCommitError, match="story-bible claim"):
        draft.commit()

    assert isolated_world.model_dump(mode="json") == before


def test_commit_under_claim_replaces_events_all_or_nothing(isolated_world: World) -> None:
    from app.graphs.jobs import get_job_manager

    bible = _seed_live_world(isolated_world)
    draft = PlotDraft(bible)
    added = draft.add_event(
        "The alley",
        relations=[EventRelationSpec(kind="follows", event_id="evt_watch")],
    )
    draft.update_event("evt_gate", description="Drafted change.")

    with get_job_manager().hold_story_bible_claim():
        draft.commit()

    live = isolated_world.story_bible
    assert live.get_event(added.id) is not None
    assert live.get_event("evt_gate").description == "Drafted change."
    assert [event.id for event in live.timeline] == [event.id for event in draft.bible.timeline]


def test_commit_refuses_when_live_events_drifted(isolated_world: World) -> None:
    from app.graphs.jobs import get_job_manager

    bible = _seed_live_world(isolated_world)
    draft = PlotDraft(bible)
    draft.update_event("evt_gate", description="Drafted change.")

    bible.timeline.append(Event(id="evt_concurrent", title="Concurrent edit"))
    save_world()

    with (
        get_job_manager().hold_story_bible_claim(),
        pytest.raises(DraftCommitError, match="changed since"),
    ):
        draft.commit()

    assert bible.get_event("evt_concurrent") is not None
    assert bible.get_event("evt_gate").description == ""


def test_commit_rolls_back_memory_on_failed_save(
    isolated_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.world.store as store
    from app.graphs.jobs import get_job_manager

    bible = _seed_live_world(isolated_world)
    draft = PlotDraft(bible)
    draft.update_event("evt_gate", description="Drafted change.")

    def failing_save() -> None:
        raise PermissionError("world.json is locked")

    monkeypatch.setattr(store, "save_world", failing_save)

    with get_job_manager().hold_story_bible_claim(), pytest.raises(PermissionError):
        draft.commit()

    assert isolated_world.story_bible.get_event("evt_gate").description == ""


def test_commit_prunes_scene_links_for_deleted_events(isolated_world: World) -> None:
    from app.graphs.jobs import get_job_manager

    bible = _seed_live_world(isolated_world)
    isolated_world.scenes.append(
        Scene(
            id="scene_watch",
            title="The Watch",
            blueprint=SceneBlueprint(
                premise="A quiet night",
                event_ids=["evt_watch"],
                related_event_ids=["evt_meal"],
            ),
        )
    )
    save_world()

    draft = PlotDraft(bible)
    draft.delete_event("evt_watch")

    with get_job_manager().hold_story_bible_claim():
        draft.commit()

    blueprint = isolated_world.scenes[0].blueprint
    assert blueprint.event_ids == []
    assert blueprint.related_event_ids == ["evt_meal"]


def test_story_bible_claim_rejects_second_acquisition(isolated_world: World) -> None:
    from app.graphs.jobs import STORY_BIBLE_CLAIM, get_job_manager

    manager = get_job_manager()
    with manager.hold_story_bible_claim() as job:
        assert manager.claim_for(STORY_BIBLE_CLAIM) is job
        with pytest.raises(RuntimeError, match="already claimed"):
            with manager.hold_story_bible_claim():
                pass
    assert manager.claim_for(STORY_BIBLE_CLAIM) is None
