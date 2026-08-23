"""Plot draft workspace: a sandboxed Story Bible copy with all-or-nothing commit.

``PlotDraft`` wraps a deep copy of the live ``StoryBible`` so a plot run can
add, edit, reorder, and delete events without touching the world. Every write
is validated like the story-bible tools (unknown ids are rejected with the
valid options), recorded in a step log with a post-step snapshot (so
backtracking is cheap), and followed by stale-ripple tracking that flags
downstream events whose *interpretations* are semantically stale. Derived rank
is never stale — replay recomputes it — so the stale set tracks the semantic
layer only.

Commit replaces the live world's ``timeline`` and ``event_relations`` inside
one ``world_transaction()``. It requires the coarse story-bible ``JobManager``
claim (``hold_story_bible_claim``) and refuses to commit if the live events
changed since the draft forked, so wholesale replacement cannot clobber
concurrent edits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from app.world.models import (
    AddIntimacy,
    Event,
    EventRelation,
    EventRelationKind,
    EventRelationSpec,
    Signal,
    StoryBible,
    WorldStateEffect,
    unique_slug,
)
from app.world.relations import (
    RelationValidationError,
    chronological_order,
    normalize_relation,
    scenario_ids,
)
from app.world.replay import (
    DerivedState,
    EffectDiagnostic,
    derive_state,
    effect_diagnostics,
    explain_intimacies,
)
from app.world.scene import prune_event_links
from app.world.store import world_transaction

DraftAction = Literal[
    "add_event",
    "update_event",
    "delete_event",
    "insert_between",
    "add_relation",
    "remove_relation",
]

# Relation kinds insert_event_between can rewire.
_INSERTABLE_KINDS: tuple[EventRelationKind, ...] = ("follows", "directly_follows")


class DraftCommitError(RuntimeError):
    """Raised when a draft commit is not allowed (missing claim or live drift)."""


@dataclass(frozen=True)
class DraftStep:
    """One recorded draft operation, for backtracking and result summaries."""

    index: int
    action: DraftAction
    summary: str
    event_ids: tuple[str, ...]
    stale_added: tuple[str, ...]


class PlotDraft:
    """A draft copy of the Story Bible's events, committed all-or-nothing."""

    def __init__(self, base: StoryBible) -> None:
        self._base = base.model_copy(deep=True)
        self.bible = base.model_copy(deep=True)
        self._steps: list[DraftStep] = []
        self._snapshots: list[tuple[StoryBible, frozenset[str]]] = []
        self._stale: set[str] = set()

    @property
    def steps(self) -> tuple[DraftStep, ...]:
        return tuple(self._steps)

    @property
    def stale_event_ids(self) -> frozenset[str]:
        """Events whose existing interpretations are flagged semantically stale."""

        return frozenset(self._stale)

    # ------------------------------------------------------------------ writes

    def add_event(
        self,
        title: str,
        *,
        description: str = "",
        relations: list[EventRelationSpec] | None = None,
        world_state_effects: list[WorldStateEffect] | None = None,
        signals: list[Signal] | None = None,
    ) -> Event:
        """Add an event to the draft timeline; relations are required once events exist."""

        relation_specs = relations or []
        if self.bible.timeline and not relation_specs:
            raise ValueError(
                "New events must link to existing ones when the timeline is not empty. "
                f"Pass relations with at least one entry. {_event_listing(self.bible)}"
            )
        self._validate_signal_characters(signals or [])

        before = self.bible.model_copy(deep=True)
        event = Event(
            title=title,
            description=description,
            world_state_effects=[item.model_copy(deep=True) for item in world_state_effects or []],
            signals=[item.model_copy(deep=True) for item in signals or []],
        )
        event.id = unique_slug("event_", title, {item.id for item in self.bible.timeline})
        try:
            self.bible.timeline.append(event)
            for spec in relation_specs:
                source_id, target_id = normalize_relation(
                    self.bible, spec.kind, event.id, spec.event_id
                )
                self.bible.event_relations.append(
                    EventRelation(kind=spec.kind, source_id=source_id, target_id=target_id)
                )
        except RelationValidationError:
            self.bible = before
            raise

        stale_added = self._flag_stale(before, {event.id})
        self._record_step(
            "add_event",
            f"Added event '{title or 'Untitled'}' [{event.id}]",
            (event.id,),
            stale_added,
        )
        return event

    def update_event(
        self,
        event_id: str,
        *,
        title: str | None = None,
        description: str | None = None,
        world_state_effects: list[WorldStateEffect] | None = None,
        signals: list[Signal] | None = None,
    ) -> Event:
        """Partially update a draft event; only provided fields change."""

        event = self._require_event(event_id)
        if signals is not None:
            self._validate_signal_characters(signals)

        before = self.bible.model_copy(deep=True)
        if title is not None:
            event.title = title
        if description is not None:
            event.description = description
        if world_state_effects is not None:
            event.world_state_effects = [item.model_copy(deep=True) for item in world_state_effects]
        if signals is not None:
            event.signals = [item.model_copy(deep=True) for item in signals]

        stale_added = self._flag_stale(before, {event.id})
        self._record_step(
            "update_event",
            f"Updated event '{event.title or 'Untitled'}' [{event.id}]",
            (event.id,),
            stale_added,
        )
        return event

    def delete_event(self, event_id: str) -> Event:
        """Delete a draft event and every relation that touches it."""

        event = self._require_event(event_id)

        before = self.bible.model_copy(deep=True)
        self.bible.timeline = [item for item in self.bible.timeline if item.id != event_id]
        self.bible.event_relations = [
            item
            for item in self.bible.event_relations
            if item.source_id != event_id and item.target_id != event_id
        ]

        stale_added = self._flag_stale(before, {event_id})
        self._record_step(
            "delete_event",
            f"Deleted event '{event.title or 'Untitled'}' [{event_id}]",
            (event_id,),
            stale_added,
        )
        return event

    def insert_event_between(
        self,
        title: str,
        *,
        earlier_event_id: str,
        later_event_id: str,
        description: str = "",
        world_state_effects: list[WorldStateEffect] | None = None,
        signals: list[Signal] | None = None,
    ) -> Event:
        """Insert a new event between two directly linked anchors, atomically.

        The existing ``follows`` / ``directly_follows`` edge from the later
        anchor to the earlier one is replaced by two edges of the same kind
        through the new event, so the chain can never be half-rewired.
        """

        earlier = self._require_event(earlier_event_id)
        later = self._require_event(later_event_id)
        if earlier.id == later.id:
            raise ValueError("earlier_event_id and later_event_id must differ.")
        self._validate_signal_characters(signals or [])

        edge = next(
            (
                relation
                for relation in self.bible.event_relations
                if relation.kind in _INSERTABLE_KINDS
                and relation.source_id == later.id
                and relation.target_id == earlier.id
            ),
            None,
        )
        if edge is None:
            raise ValueError(
                f"Events '{earlier.id}' and '{later.id}' are not directly linked by a "
                "follows/directly_follows relation (later must follow earlier). "
                "Insert requires adjacent anchors; use add_event with relations otherwise. "
                f"{_event_listing(self.bible)}"
            )

        before = self.bible.model_copy(deep=True)
        event = Event(
            title=title,
            description=description,
            world_state_effects=[item.model_copy(deep=True) for item in world_state_effects or []],
            signals=[item.model_copy(deep=True) for item in signals or []],
        )
        event.id = unique_slug("event_", title, {item.id for item in self.bible.timeline})
        self.bible.timeline.append(event)
        self.bible.event_relations = [
            item for item in self.bible.event_relations if item.id != edge.id
        ]
        self.bible.event_relations.append(
            EventRelation(kind=edge.kind, source_id=event.id, target_id=earlier.id)
        )
        self.bible.event_relations.append(
            EventRelation(kind=edge.kind, source_id=later.id, target_id=event.id)
        )

        stale_added = self._flag_stale(before, {event.id})
        self._record_step(
            "insert_between",
            f"Inserted event '{title or 'Untitled'}' [{event.id}] "
            f"between [{earlier.id}] and [{later.id}]",
            (event.id, earlier.id, later.id),
            stale_added,
        )
        return event

    def add_relation(
        self,
        kind: EventRelationKind,
        source_id: str,
        target_id: str,
    ) -> EventRelation:
        """Add a typed relation between two draft events (validated, cycle-checked)."""

        before = self.bible.model_copy(deep=True)
        normalized_source, normalized_target = normalize_relation(
            self.bible, kind, source_id, target_id
        )
        relation = EventRelation(
            kind=kind, source_id=normalized_source, target_id=normalized_target
        )
        self.bible.event_relations.append(relation)

        touched = {normalized_source, normalized_target}
        stale_added = self._flag_stale(before, touched, check_touched_reorder=True)
        self._record_step(
            "add_relation",
            f"Added {kind} relation from [{normalized_source}] to [{normalized_target}]",
            (normalized_source, normalized_target),
            stale_added,
        )
        return relation

    def remove_relation(self, relation_id: str) -> EventRelation:
        """Remove a draft relation by id."""

        relation = self.bible.get_event_relation(relation_id)
        if relation is None:
            listing = ", ".join(
                f"{item.kind} [{item.source_id} -> {item.target_id}] [{item.id}]"
                for item in self.bible.event_relations
            )
            raise ValueError(
                f"No event relation with id {relation_id}. Valid relations: {listing or '(none)'}"
            )

        before = self.bible.model_copy(deep=True)
        self.bible.event_relations = [
            item for item in self.bible.event_relations if item.id != relation_id
        ]

        touched = {relation.source_id, relation.target_id}
        stale_added = self._flag_stale(before, touched, check_touched_reorder=True)
        self._record_step(
            "remove_relation",
            f"Removed {relation.kind} relation from "
            f"[{relation.source_id}] to [{relation.target_id}]",
            (relation.source_id, relation.target_id),
            stale_added,
        )
        return relation

    # -------------------------------------------------------------- step log

    def truncate_to(self, step_count: int) -> None:
        """Backtrack: keep the first ``step_count`` steps and restore that state."""

        if not 0 <= step_count <= len(self._steps):
            raise ValueError(
                f"step_count must be between 0 and {len(self._steps)}, got {step_count}."
            )
        if step_count == len(self._steps):
            return
        if step_count == 0:
            self.bible = self._base.model_copy(deep=True)
            self._stale = set()
        else:
            snapshot_bible, snapshot_stale = self._snapshots[step_count - 1]
            self.bible = snapshot_bible.model_copy(deep=True)
            self._stale = set(snapshot_stale)
        del self._steps[step_count:]
        del self._snapshots[step_count:]

    def mark_interpreted(self, event_id: str) -> None:
        """Clear an event's stale flag after its interpretations were refreshed."""

        self._stale.discard(event_id)

    # ----------------------------------------------------------------- reads

    def chronology(self) -> list[Event]:
        return chronological_order(self.bible)

    def derived_state(self, up_to_event_id: str | None = None) -> DerivedState:
        return derive_state(self.bible, up_to_event_id)

    def explain(self, character_id: str, up_to_event_id: str | None = None):
        return explain_intimacies(self.bible, character_id, up_to_event_id)

    def diagnostics(self) -> list[EffectDiagnostic]:
        return effect_diagnostics(self.bible)

    # ---------------------------------------------------------------- commit

    def commit(self) -> None:
        """Replace the live world's events with the draft's, all-or-nothing.

        Requires the story-bible ``JobManager`` claim to be held
        (``hold_story_bible_claim``) and the live events to be unchanged since
        the draft forked. Scene blueprints lose links to events the draft
        deleted, exactly like a live delete. The transaction rolls the world
        back if the save fails.
        """

        # Lazy import: the claim registry lives in the job layer, and app.world
        # must stay importable without it.
        from app.graphs.jobs import STORY_BIBLE_CLAIM, get_job_manager

        if get_job_manager().claim_for(STORY_BIBLE_CLAIM) is None:
            raise DraftCommitError(
                "Committing a plot draft requires holding the story-bible claim "
                "(JobManager.hold_story_bible_claim)."
            )

        with world_transaction() as world:
            if _events_payload(world.story_bible) != _events_payload(self._base):
                raise DraftCommitError(
                    "The live story bible's events changed since this draft was created; "
                    "discard the draft and start over."
                )
            draft_event_ids = {event.id for event in self.bible.timeline}
            removed = [event.id for event in self._base.timeline if event.id not in draft_event_ids]
            for event_id in removed:
                prune_event_links(world, event_id)
            world.story_bible.timeline = [
                event.model_copy(deep=True) for event in self.bible.timeline
            ]
            world.story_bible.event_relations = [
                relation.model_copy(deep=True) for relation in self.bible.event_relations
            ]

    # -------------------------------------------------------------- internals

    def _require_event(self, event_id: str) -> Event:
        event = self.bible.get_event(event_id)
        if event is None:
            raise ValueError(f"No event with id {event_id}. {_event_listing(self.bible)}")
        return event

    def _validate_signal_characters(self, signals: list[Signal]) -> None:
        valid = {
            character.id: character.identity.name or "Unnamed"
            for character in self.bible.characters
        }
        for signal in signals:
            if signal.character_id and signal.character_id not in valid:
                if valid:
                    listing = ", ".join(f"{name} [{cid}]" for cid, name in valid.items())
                    detail = f"Valid characters: {listing}"
                else:
                    detail = "No characters exist yet."
                raise ValueError(
                    f"Unknown character_id '{signal.character_id}' in signal. {detail}"
                )

    def _record_step(
        self,
        action: DraftAction,
        summary: str,
        event_ids: tuple[str, ...],
        stale_added: tuple[str, ...],
    ) -> DraftStep:
        step = DraftStep(
            index=len(self._steps),
            action=action,
            summary=summary,
            event_ids=event_ids,
            stale_added=stale_added,
        )
        self._steps.append(step)
        self._snapshots.append((self.bible.model_copy(deep=True), frozenset(self._stale)))
        return step

    def _flag_stale(
        self,
        before: StoryBible,
        touched_ids: set[str],
        *,
        check_touched_reorder: bool = False,
    ) -> tuple[str, ...]:
        """Flag downstream events whose interpretations the edit made stale.

        Bounded: a downstream event is flagged only when its signal characters
        or referenced intimacies overlap the touched event's, or its scenario
        membership (``directly_follows`` chain) changed. Events with new
        dangling-reference diagnostics (``effect_diagnostics``) seed the set
        regardless of position. Touched events themselves are not flagged
        (their interpretations are refreshed inline by the caller) except on
        relation edits, where a reordered endpoint is stale.
        """

        after = self.bible
        order_before = [event.id for event in chronological_order(before)]
        order_after = [event.id for event in chronological_order(after)]
        pos_before = {event_id: index for index, event_id in enumerate(order_before)}
        pos_after = {event_id: index for index, event_id in enumerate(order_after)}
        after_ids = set(pos_after)

        touched_signals: list[Signal] = []
        for event_id in touched_ids:
            for bible in (before, after):
                event = bible.get_event(event_id)
                if event is not None:
                    touched_signals.extend(event.signals)
        touched_characters = {
            signal.character_id for signal in touched_signals if signal.character_id
        }
        touched_intimacies: set[str] = set()
        for signal in touched_signals:
            touched_intimacies.update(
                entry.intimacy_id for entry in signal.evidence if entry.intimacy_id
            )
            for effect in signal.effects:
                if isinstance(effect, AddIntimacy):
                    touched_intimacies.add(effect.intimacy.id)
                else:
                    touched_intimacies.add(effect.intimacy_id)

        def _downstream(positions: dict[str, int], order: list[str]) -> set[str]:
            boundary = min(
                (positions[event_id] for event_id in touched_ids if event_id in positions),
                default=None,
            )
            if boundary is None:
                return set()
            return set(order[boundary + 1 :])

        candidates = (
            _downstream(pos_before, order_before) | _downstream(pos_after, order_after)
        ) & after_ids

        scenarios_before = scenario_ids(before)
        scenarios_after = scenario_ids(after)
        newly_dangling = {item.event_id for item in effect_diagnostics(after)} - {
            item.event_id for item in effect_diagnostics(before)
        }

        added: set[str] = set()
        for event in after.timeline:
            if not event.signals or event.id in self._stale:
                continue
            scenario_changed = scenarios_before.get(event.id) != scenarios_after.get(event.id)
            if event.id in touched_ids:
                moved = pos_before.get(event.id) != pos_after.get(event.id)
                if check_touched_reorder and (moved or scenario_changed):
                    added.add(event.id)
                continue
            if event.id in newly_dangling:
                added.add(event.id)
                continue
            if event.id not in candidates:
                continue
            if scenario_changed:
                added.add(event.id)
                continue
            characters = {signal.character_id for signal in event.signals}
            intimacies = {
                entry.intimacy_id for signal in event.signals for entry in signal.evidence
            }
            if characters & touched_characters or intimacies & touched_intimacies:
                added.add(event.id)

        self._stale &= after_ids
        self._stale |= added
        return tuple(sorted(added))


def _event_listing(bible: StoryBible) -> str:
    if not bible.timeline:
        return "No events exist yet."
    listing = ", ".join(f"{event.title or 'Untitled'} [{event.id}]" for event in bible.timeline)
    return f"Valid events: {listing}"


def _events_payload(bible: StoryBible) -> tuple[list[Any], list[Any]]:
    return (
        [event.model_dump(mode="json") for event in bible.timeline],
        [relation.model_dump(mode="json") for relation in bible.event_relations],
    )
