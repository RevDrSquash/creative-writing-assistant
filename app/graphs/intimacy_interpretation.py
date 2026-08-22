"""Programmatic apply and fan-out helpers for intimacy interpretation.

``run_intimacy_interpretation`` (in ``intimacy_workflow``) is analyze-only.
This module persists a reviewed result and resolves which characters to run
for an event. ``JobManager`` is the public trigger; UI and agent tools both
call it. See ``docs/architecture_agent_workflows.md``.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from app.graphs.intimacy_workflow import InterpretationResult, run_intimacy_interpretation
from app.world.models import (
    AddIntimacy,
    Event,
    Intimacy,
    IntimacyEvidence,
    Signal,
    StoryBible,
    UpdateIntimacy,
    World,
)
from app.world.scene import enacting_scenes
from app.world.store import world_transaction

NO_RELEVANT_CHARACTERS_MESSAGE = "No relevant characters — add a signal or scene cast, then re-run."


def relevant_character_ids(world: World, event_id: str) -> list[str]:
    """Return characters to interpret for ``event_id``, in stable order.

    The set is the union of character ids on the event's signals and character
    ids on any scene that enacts the event. Unknown ids are dropped. An empty
    result is a no-op: do not interpret every character in the bible.
    """

    event = world.story_bible.get_event(event_id)
    if event is None:
        msg = f"Event not found: {event_id}"
        raise ValueError(msg)

    seen: set[str] = set()
    ordered: list[str] = []

    def _add(character_id: str) -> None:
        if not character_id or character_id in seen:
            return
        if world.story_bible.get_character(character_id) is None:
            return
        seen.add(character_id)
        ordered.append(character_id)

    for signal in event.signals:
        _add(signal.character_id)
    for scene in enacting_scenes(world, event_id):
        for character_id in scene.blueprint.character_ids:
            _add(character_id)
    return ordered


def apply_interpretation(result: InterpretationResult) -> None:
    """Persist a reviewed interpretation through ``world_transaction()``.

    Approved and revised results write the signal, evidence, and approved
    creation/rewording records even when rank will not change. Rejected
    results write interpretation plus review metadata and clear this signal's
    evidence so the event stops contributing; they do not add proposals.
    """

    with world_transaction() as world:
        event = world.story_bible.get_event(result.event_id)
        if event is None:
            msg = f"Event not found: {result.event_id}"
            raise ValueError(msg)
        if world.story_bible.get_character(result.character_id) is None:
            msg = f"Character not found: {result.character_id}"
            raise ValueError(msg)

        signal = _upsert_signal(event, result.character_id)
        signal.interpretation = result.interpretation
        signal.review = result.review

        if result.review.decision == "rejected":
            signal.evidence = []
            return

        evidence, new_intimacies = _dedupe_new_intimacies(
            world.story_bible,
            result.character_id,
            result.evidence,
            result.new_intimacies,
        )
        signal.evidence = evidence
        _merge_structural_effects(signal, new_intimacies, result.rewordings)


def run_and_apply_intimacy_interpretation(
    event_id: str,
    character_id: str,
    *,
    models: dict[str, BaseChatModel] | None = None,
) -> InterpretationResult:
    """Interpret one character-event pair and persist the reviewed result.

    This is the programmatic entry point used by ``JobManager``. It does not
    depend on NiceGUI. Analysis is read-only; apply is the only writer.
    """

    result = run_intimacy_interpretation(event_id, character_id, models=models)
    apply_interpretation(result)
    return result


def _upsert_signal(event: Event, character_id: str) -> Signal:
    for signal in event.signals:
        if signal.character_id == character_id:
            return signal
    signal = Signal(character_id=character_id)
    event.signals.append(signal)
    return signal


def _dedupe_new_intimacies(
    bible: StoryBible,
    character_id: str,
    evidence: list[IntimacyEvidence],
    new_intimacies: list[Intimacy],
) -> tuple[list[IntimacyEvidence], list[Intimacy]]:
    """Skip new intimacies that already exist (by id or text); remap evidence."""

    catalog = bible.intimacy_catalog(character_id)
    known_ids = {intimacy_id for intimacy_id, _text in catalog}
    text_to_id = {
        text.strip().lower(): intimacy_id for intimacy_id, text in catalog if text.strip()
    }
    remap: dict[str, str] = {}
    kept: list[Intimacy] = []

    for intimacy in new_intimacies:
        existing = text_to_id.get(intimacy.text.strip().lower())
        if existing and existing != intimacy.id:
            remap[intimacy.id] = existing
            continue
        if intimacy.id in known_ids:
            continue
        kept.append(intimacy)
        known_ids.add(intimacy.id)
        if intimacy.text.strip():
            text_to_id[intimacy.text.strip().lower()] = intimacy.id

    remapped = [
        entry.model_copy(update={"intimacy_id": remap.get(entry.intimacy_id, entry.intimacy_id)})
        for entry in evidence
    ]
    return remapped, kept


def _merge_structural_effects(
    signal: Signal,
    new_intimacies: list[Intimacy],
    rewordings: list,
) -> None:
    existing_add_ids = {
        effect.intimacy.id for effect in signal.effects if isinstance(effect, AddIntimacy)
    }
    for intimacy in new_intimacies:
        if intimacy.id in existing_add_ids:
            continue
        signal.effects.append(AddIntimacy(intimacy=intimacy))
        existing_add_ids.add(intimacy.id)

    reword_ids = {item.intimacy_id for item in rewordings if item.intimacy_id and item.text.strip()}
    signal.effects = [
        effect
        for effect in signal.effects
        if not (isinstance(effect, UpdateIntimacy) and effect.intimacy_id in reword_ids)
    ]
    for item in rewordings:
        if not item.intimacy_id or not item.text.strip():
            continue
        signal.effects.append(UpdateIntimacy(intimacy_id=item.intimacy_id, text=item.text.strip()))
