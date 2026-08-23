"""Tests for intimacy apply, relevant-character selection, and failed saves."""

from __future__ import annotations

import pytest

from app.graphs.intimacy_interpretation import (
    NO_RELEVANT_CHARACTERS_MESSAGE,
    apply_interpretation,
    apply_interpretation_to_bible,
    relevant_character_ids,
    run_and_apply_intimacy_interpretation,
)
from app.graphs.intimacy_workflow import InterpretationResult, RewordingProposal
from app.world.models import (
    AddIntimacy,
    Character,
    CharacterBaselineState,
    CharacterIdentity,
    Event,
    Intimacy,
    IntimacyEvidence,
    Scene,
    SceneBlueprint,
    SetIntimacyStrength,
    Signal,
    SignalReview,
    UpdateIntimacy,
    World,
)
from app.world.replay import derive_state
from app.world.store import save_world


def _character(
    name: str, character_id: str, *, intimacies: list[Intimacy] | None = None
) -> Character:
    return Character(
        id=character_id,
        identity=CharacterIdentity(name=name),
        baseline_state=CharacterBaselineState(intimacies=intimacies or []),
    )


def _approved_result(
    event_id: str,
    character_id: str,
    *,
    interpretation: str = "They meant it.",
    evidence: list[IntimacyEvidence] | None = None,
    new_intimacies: list[Intimacy] | None = None,
    rewordings: list[RewordingProposal] | None = None,
) -> InterpretationResult:
    return InterpretationResult(
        event_id=event_id,
        character_id=character_id,
        interpretation=interpretation,
        evidence=evidence or [],
        new_intimacies=new_intimacies or [],
        rewordings=rewordings or [],
        review=SignalReview(decision="approved", notes="ok"),
    )


def test_relevant_characters_empty_when_no_signals_or_cast(isolated_world: World) -> None:
    isolated_world.story_bible.timeline.append(Event(id="evt_look", title="A look"))

    assert relevant_character_ids(isolated_world, "evt_look") == []
    assert NO_RELEVANT_CHARACTERS_MESSAGE


def test_relevant_characters_union_of_signals_and_scene_cast(isolated_world: World) -> None:
    isolated_world.story_bible.characters.extend(
        [
            _character("Mira", "char_mira"),
            _character("Kael", "char_kael"),
            _character("Ghost", "char_ghost"),
        ]
    )
    isolated_world.story_bible.timeline.append(
        Event(
            id="evt_look",
            title="A look",
            signals=[
                Signal(character_id="char_mira", interpretation="Hint"),
                Signal(character_id="char_missing", interpretation="Dropped"),
            ],
        )
    )
    isolated_world.scenes.append(
        Scene(
            id="scene_look",
            title="The Look",
            blueprint=SceneBlueprint(
                premise="A glance",
                event_ids=["evt_look"],
                character_ids=["char_kael", "char_mira", "char_nobody"],
            ),
        )
    )

    assert relevant_character_ids(isolated_world, "evt_look") == ["char_mira", "char_kael"]


def test_apply_approved_writes_signal_evidence_and_creation(isolated_world: World) -> None:
    intimacy = Intimacy(id="intim_wary", text="Wary of outsiders", strength="minor")
    created = Intimacy(id="intim_debt", text="Owes Kael a debt", strength="minor")
    isolated_world.story_bible.characters.append(
        _character("Mira", "char_mira", intimacies=[intimacy])
    )
    isolated_world.story_bible.timeline.append(
        Event(
            id="evt_look",
            title="A look",
            signals=[Signal(character_id="char_mira", interpretation="Hint")],
        )
    )

    apply_interpretation(
        _approved_result(
            "evt_look",
            "char_mira",
            evidence=[
                IntimacyEvidence(
                    intimacy_id="intim_wary",
                    direction="supports",
                    strength=2,
                    rationale="The glance confirmed it.",
                ),
                IntimacyEvidence(
                    intimacy_id="intim_debt",
                    direction="supports",
                    strength=3,
                    rationale="The favor starts here.",
                ),
            ],
            new_intimacies=[created],
            rewordings=[RewordingProposal(intimacy_id="intim_wary", text="Cannot trust strangers")],
        )
    )

    signal = isolated_world.story_bible.timeline[0].signals[0]
    assert signal.interpretation == "They meant it."
    assert signal.review is not None
    assert signal.review.decision == "approved"
    assert [entry.intimacy_id for entry in signal.evidence] == ["intim_wary", "intim_debt"]
    assert any(
        isinstance(effect, AddIntimacy) and effect.intimacy.id == "intim_debt"
        for effect in signal.effects
    )
    assert any(
        isinstance(effect, UpdateIntimacy) and effect.text == "Cannot trust strangers"
        for effect in signal.effects
    )
    derived = derive_state(isolated_world.story_bible).characters["char_mira"]
    texts = {item.text for item in derived.intimacies}
    assert "Owes Kael a debt" in texts
    assert "Cannot trust strangers" in texts


def test_apply_rejected_clears_evidence_and_skips_proposals(isolated_world: World) -> None:
    isolated_world.story_bible.characters.append(_character("Mira", "char_mira"))
    isolated_world.story_bible.timeline.append(
        Event(
            id="evt_look",
            title="A look",
            signals=[
                Signal(
                    character_id="char_mira",
                    interpretation="Old hint",
                    evidence=[
                        IntimacyEvidence(
                            intimacy_id="intim_wary",
                            direction="supports",
                            strength=3,
                        )
                    ],
                )
            ],
        )
    )

    apply_interpretation(
        InterpretationResult(
            event_id="evt_look",
            character_id="char_mira",
            interpretation="This is just weather.",
            evidence=[IntimacyEvidence(intimacy_id="intim_wary", direction="supports", strength=5)],
            new_intimacies=[Intimacy(id="intim_new", text="Should not exist")],
            review=SignalReview(decision="rejected", notes="Event summary, not a signal."),
        )
    )

    signal = isolated_world.story_bible.timeline[0].signals[0]
    assert signal.interpretation == "This is just weather."
    assert signal.review is not None
    assert signal.review.decision == "rejected"
    assert signal.review.notes == "Event summary, not a signal."
    assert signal.evidence == []
    assert signal.effects == []
    derived = derive_state(isolated_world.story_bible).characters["char_mira"]
    assert derived.intimacies == []


def test_apply_rejected_rerun_drops_prior_workflow_effects(isolated_world: World) -> None:
    """A rejected re-run removes earlier creation/rewording records, not just evidence."""

    intimacy = Intimacy(id="intim_wary", text="Wary of outsiders", strength="minor")
    isolated_world.story_bible.characters.append(
        _character("Mira", "char_mira", intimacies=[intimacy])
    )
    isolated_world.story_bible.timeline.append(
        Event(
            id="evt_look",
            title="A look",
            signals=[
                Signal(
                    character_id="char_mira",
                    interpretation="Old approved read",
                    review=SignalReview(decision="approved"),
                    evidence=[
                        IntimacyEvidence(intimacy_id="intim_debt", direction="supports", strength=3)
                    ],
                    effects=[
                        AddIntimacy(intimacy=Intimacy(id="intim_debt", text="Owes Kael a debt")),
                        UpdateIntimacy(intimacy_id="intim_wary", text="Cannot trust strangers"),
                        # UI/legacy record the workflow never authors; apply must not touch it.
                        SetIntimacyStrength(intimacy_id="intim_wary", strength="major"),
                    ],
                )
            ],
        )
    )

    apply_interpretation(
        InterpretationResult(
            event_id="evt_look",
            character_id="char_mira",
            interpretation="Just weather.",
            review=SignalReview(decision="rejected", notes="Overread."),
        )
    )

    signal = isolated_world.story_bible.timeline[0].signals[0]
    assert signal.evidence == []
    assert [type(effect) for effect in signal.effects] == [SetIntimacyStrength]
    derived = derive_state(isolated_world.story_bible).characters["char_mira"]
    texts = {item.text for item in derived.intimacies}
    assert "Owes Kael a debt" not in texts
    assert "Cannot trust strangers" not in texts


def test_apply_rerun_replaces_stale_structural_effects(isolated_world: World) -> None:
    """A re-run drops records the new result no longer proposes but keeps the
    establishing record for an intimacy the new evidence still references."""

    intimacy = Intimacy(id="intim_wary", text="Wary of outsiders", strength="minor")
    isolated_world.story_bible.characters.append(
        _character("Mira", "char_mira", intimacies=[intimacy])
    )
    isolated_world.story_bible.timeline.append(
        Event(
            id="evt_look",
            title="A look",
            signals=[
                Signal(
                    character_id="char_mira",
                    interpretation="Old approved read",
                    review=SignalReview(decision="approved"),
                    effects=[
                        AddIntimacy(intimacy=Intimacy(id="intim_debt", text="Owes Kael a debt")),
                        AddIntimacy(intimacy=Intimacy(id="intim_stale", text="A passing fancy")),
                        UpdateIntimacy(intimacy_id="intim_wary", text="Old rewording"),
                    ],
                )
            ],
        )
    )

    apply_interpretation(
        _approved_result(
            "evt_look",
            "char_mira",
            evidence=[IntimacyEvidence(intimacy_id="intim_debt", direction="supports", strength=2)],
        )
    )

    signal = isolated_world.story_bible.timeline[0].signals[0]
    add_ids = [effect.intimacy.id for effect in signal.effects if isinstance(effect, AddIntimacy)]
    assert add_ids == ["intim_debt"]
    assert not any(isinstance(effect, UpdateIntimacy) for effect in signal.effects)
    derived = derive_state(isolated_world.story_bible).characters["char_mira"]
    texts = {item.text for item in derived.intimacies}
    assert "Owes Kael a debt" in texts
    assert "A passing fancy" not in texts
    assert "Wary of outsiders" in texts


def test_apply_to_bible_writes_passed_bible_without_touching_world(
    isolated_world: World,
) -> None:
    isolated_world.story_bible.characters.append(_character("Mira", "char_mira"))
    isolated_world.story_bible.timeline.append(
        Event(
            id="evt_look",
            title="A look",
            signals=[Signal(character_id="char_mira", interpretation="Hint")],
        )
    )
    draft = isolated_world.story_bible.model_copy(deep=True)
    before = isolated_world.model_dump(mode="json")

    apply_interpretation_to_bible(draft, _approved_result("evt_look", "char_mira"))

    draft_signal = draft.timeline[0].signals[0]
    assert draft_signal.interpretation == "They meant it."
    assert draft_signal.review is not None
    assert draft_signal.review.decision == "approved"
    assert isolated_world.model_dump(mode="json") == before
    assert isolated_world.story_bible.timeline[0].signals[0].interpretation == "Hint"


def test_apply_failed_save_rolls_back_memory(
    isolated_world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolated_world.story_bible.characters.append(_character("Mira", "char_mira"))
    isolated_world.story_bible.timeline.append(
        Event(
            id="evt_look",
            title="A look",
            signals=[Signal(character_id="char_mira", interpretation="Hint")],
        )
    )
    save_world()

    import app.world.store as store

    def failing_save() -> None:
        raise PermissionError("world.json is locked")

    monkeypatch.setattr(store, "save_world", failing_save)

    with pytest.raises(PermissionError):
        apply_interpretation(_approved_result("evt_look", "char_mira"))

    signal = isolated_world.story_bible.timeline[0].signals[0]
    assert signal.interpretation == "Hint"
    assert signal.review is None
    assert signal.evidence == []


def test_apply_remaps_duplicate_new_intimacy_text(isolated_world: World) -> None:
    existing = Intimacy(id="intim_wary", text="Wary of outsiders", strength="minor")
    isolated_world.story_bible.characters.append(
        _character("Mira", "char_mira", intimacies=[existing])
    )
    isolated_world.story_bible.timeline.append(Event(id="evt_look", title="A look"))

    apply_interpretation(
        _approved_result(
            "evt_look",
            "char_mira",
            evidence=[
                IntimacyEvidence(
                    intimacy_id="intim_new_copy",
                    direction="supports",
                    strength=3,
                )
            ],
            new_intimacies=[Intimacy(id="intim_new_copy", text="Wary of outsiders")],
        )
    )

    signal = isolated_world.story_bible.timeline[0].signals[0]
    assert [entry.intimacy_id for entry in signal.evidence] == ["intim_wary"]
    assert not any(isinstance(effect, AddIntimacy) for effect in signal.effects)


def test_run_and_apply_uses_injected_models(
    isolated_world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_world.story_bible.characters.append(_character("Mira", "char_mira"))
    isolated_world.story_bible.timeline.append(Event(id="evt_look", title="A look"))
    captured: list[str] = []

    def fake_interpret(event_id: str, character_id: str, *, models=None):
        captured.append(character_id)
        return _approved_result(event_id, character_id)

    monkeypatch.setattr(
        "app.graphs.intimacy_interpretation.run_intimacy_interpretation",
        fake_interpret,
    )
    result = run_and_apply_intimacy_interpretation("evt_look", "char_mira", models={"x": None})
    assert captured == ["char_mira"]
    assert result.review.decision == "approved"
    assert isolated_world.story_bible.timeline[0].signals[0].interpretation == "They meant it."
