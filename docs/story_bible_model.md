# Story Bible Model

## Purpose

The Story Bible holds structured reference material for the story world. It is event-sourced:
Events and Signals record explicit structured effects, and the state of the world or of any
character at a point in the timeline is derived by replaying those effects over editable
baselines. This makes the bible renderable and editable at any point in time, and lets events
be inserted anywhere in the timeline.

This document is the authoritative description of the Story Bible data model and its replay
semantics. The form rendering and save behavior for this data is described in
[forms_and_data_models.md](forms_and_data_models.md).

## Top-Level Shape

The Story Bible lives on the `World` object and contains:

- **Narrative Style**: markdown text describing the intended tone, themes, and writing style.
- **World Facts**: stable setting facts. Locations, lore, history, and concepts are all world
  facts; there are no separate Location or Lore entity types.
- **Baseline World State**: the world-state entries (pressures, open threads, consequences)
  in effect at the start of the timeline.
- **Characters**: identity, baseline state (including intimacies), and scene-level stance.
- **Timeline**: an ordered list of Events.

## Baselines Versus Derived State

The model distinguishes editable source data from derived views:

- **Editable (stored)**: narrative style, world facts, baseline world state, character
  identity, character baseline state, character stance, events (with their effects and
  signals).
- **Derived (computed, never stored)**: the world state and each character's state at any
  timeline position. These are produced by the replay engine and are read-only.

Direct edits by the user or the agent always modify a baseline or an event's recorded
effects. There is no materialized "current state" blob to mutate, so the timeline can never
disagree with current state.

## Entities

### Entity IDs

World entities use readable slug ids assigned once at creation and frozen thereafter.
Renaming a character (or any entity) does not change its id, because signals and effects
reference ids across the timeline.

| Entity type | Prefix | Slug source |
| --- | --- | --- |
| Character | `char_` | `identity.name` |
| World fact | `fact_` | `title` |
| World-state entry | `wse_` | `text` |
| Event | `event_` | `title` |
| Scene | `scene_` | `title` |
| Intimacy | `intim_` | `text` |

A named entity becomes `{prefix}{slugified_text}` (e.g. `char_the_guard`). Blank text at
creation falls back to the bare prefix without its trailing underscore (`char`, `char_2`).
Collisions append a numeric suffix (`char_the_guard_2`).

Signal ids and model-authored inline ids (such as intimacy ids inside signal effects) are
left as supplied. Opaque hex ids from `new_id()` remain the fallback when slug assignment
does not run (e.g. legacy data).

Agent tools validate that each signal's `character_id` resolves to an existing character
before saving an event. Unknown ids raise a tool error listing valid characters as
`name [id]`, so the model can self-correct.

### World Fact

A stable setting fact. Fields: `id`, `title`, `text`, `tags`. World facts are not affected by
replay; if a fact changes during the story, that change is better modeled as a world-state
entry introduced by an event.

### World State Entry

A currently-active pressure, open thread, or recent consequence. Fields: `id`, `text`, and
`kind` (`pressure`, `thread`, or `consequence`). Baseline entries describe the world at the
start of the timeline; events add, update, or remove entries as the story progresses.

### Character

- **Identity** (stable): `name`, `traits`, `appearance`, `background`, `voice`. Identity is
  not affected by replay.
- **Baseline State**: `goal`, `status`, and a list of Intimacies as they stand at the start
  of the timeline.
- **Stance** (ephemeral): `mood`, `intent`, `tactics`, `stakes`. Stance is a scene-level
  scratch field describing the character's current posture. It is freely editable, is not
  event-sourced, and is excluded from replay. Deriving stance from identity, state, signals,
  and world state is an agent workflow concern (Phase 7), not a data-model concern.

### Intimacy

A character-subjective belief, attachment, value, fear, desire, or relationship assumption.
Fields: `id`, `text`, and `strength` (`minor`, `major`, or `defining`). Strength defines the
intimacy's impact on the character's behavior. Intimacies live in character baseline state
and are modified over time by Signal effects.

### Event

An objective story beat on the timeline. Fields: `id`, `title`, `description`, `kind`
(`scene` for normal scene events, `time_passage` for time skips), a list of world-state
effects, and a list of Signals. Event order is the timeline order (list position); events can
be inserted at any position. Events do not store timestamps; position is the ordering.

### Signal

A specific character's subjective interpretation of an Event. Signals are embedded in the
Event that produced them, which keeps the link between event and interpretation structural.
Fields: `id`, `character_id`, `interpretation` (free text), and a list of character-state
effects.

## Effects

Effects are the structured deltas that replay folds over the baselines. They are small,
explicit operations rather than free text.

### World-State Effects (on Events)

- `add_entry`: add a world-state entry (carries the new entry).
- `update_entry`: replace the text/kind of an existing entry by `entry_id`.
- `remove_entry`: remove an entry by `entry_id`.

### Character-State Effects (on Signals)

- `set_goal`: set the character's current goal.
- `set_status`: set the character's current status.
- `add_intimacy`: add an intimacy (carries the new intimacy).
- `set_intimacy_strength`: change an existing intimacy's strength by `intimacy_id`
  (strengthen or weaken).
- `update_intimacy`: replace the text of an existing intimacy by `intimacy_id`.
- `remove_intimacy`: remove an intimacy by `intimacy_id`.

## Replay Semantics

The replay engine is a pure function over the Story Bible:

- Input: the bible plus an optional timeline position (an event id, meaning "after this event
  has been applied"; absent means "after the full timeline").
- Output: the derived world state (list of world-state entries) and the derived state of each
  character (goal, status, intimacies).
- Replay starts from the baselines and applies each event's world-state effects, then each of
  its signals' character-state effects, in timeline order, up to and including the requested
  position.

Replay is tolerant of dangling references: an effect that targets a missing entry or intimacy
(for example, strengthening an intimacy a later edit removed) is skipped silently. Detecting
and surfacing such conflicts is planned future work, not a replay error.

## Editing Rules

- Inserting, reordering, or deleting events is always allowed; derived state simply replays
  differently. The model accepts temporarily inconsistent effect references.
- Deleting a character does not delete events or their signals referencing that character;
  replay skips signals whose `character_id` no longer resolves.
- Intimacy review behavior (merging duplicates, strengthening instead of duplicating, pruning
  stale intimacies, preferring small cumulative changes) is an agent workflow layered on top
  of these primitives in Phase 7. The data model only provides the primitive operations.

## Agent Access

Agent tools provide simple CRUD over the editable entities (narrative style, world facts,
baseline world state, characters, events with effects and signals) plus read access to
derived state at any timeline position. Tools mutate the in-memory `World` and write through
to disk, the same as user edits via forms.
