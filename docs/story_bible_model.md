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

- **Narrative Style**: four flat fields — `premise`, `tone`, `themes`, and `writing_style` — describing the intended story voice and craft.
- **World Facts**: stable setting facts. Locations, lore, history, and concepts are all world
  facts; there are no separate Location or Lore entity types.
- **Baseline World State**: the world-state entries (pressures, open threads, consequences)
  in effect at the start of the timeline.
- **Characters**: identity and baseline state (including intimacies). Scene-level stance is not
  stored on the character; it lives on the scene (see the Scene model in
  [forms_and_data_models.md](forms_and_data_models.md)).
- **Timeline**: an ordered list of Events.
- **Event Relations**: typed edges between events (stored separately from list order).

## Baselines Versus Derived State

The model distinguishes editable source data from derived views:

- **Editable (stored)**: narrative style fields (premise, tone, themes, writing style), world facts, baseline world state, character
  identity, character baseline state, events (with their effects and signals). Scene-level stance
  is editable too but is stored on the scene, not the character.
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
- **Baseline State**: a list of Intimacies as they stand at the start of the timeline.

A character no longer carries a stance. Stance is ephemeral, per-scene posture and is stored on
the scene as a sparse per-character list (`SceneCharacterStance`: `character_id`, `mood`,
`intent`, `tactics`, `stakes`), where `mood` is a list of short statements and the rest are single
strings. It is freely editable, is not event-sourced, and is excluded from replay. Authoring
stance is an agent workflow concern (the scene-writing workflow, Phase 6b); see the Scene model in
[forms_and_data_models.md](forms_and_data_models.md) and
[architecture_agent_workflows.md](architecture_agent_workflows.md).

### Intimacy

A character-subjective belief, attachment, value, fear, desire, or relationship assumption.
Fields: `id`, `text`, and `strength` (`minor`, `major`, or `defining`). Strength defines the
intimacy's impact on the character's behavior. Intimacies live in character baseline state
and are modified over time by Signal effects.

### Event

An objective story beat on the timeline. Fields: `id`, `title`, `description`, a list of
world-state effects, and a list of Signals. Event order is the timeline order (list position);
events can be inserted at any position. Events do not store timestamps; position is the
ordering. Relationships between events are stored on the Story Bible as `event_relations`, not
on the Event itself.

### Event Relationship

A typed edge between two events. Stored on `StoryBible.event_relations` as a flat list.
Fields: `id`, `kind`, `source_id`, `target_id`.

Kinds (for the directed kinds, `source` is the later event that follows the earlier `target`):

- `follows` (directed, loose): `source` happens after `target`, with no required time gap.
- `directly_follows` (directed, tight): `source` immediately follows `target` on a short
  timescale and they share moment-to-moment continuity (location, time of day, who is present).
- `during` (symmetric): `source` and `target` are concurrent; the pair is unordered.

Both directed kinds reference an earlier event, so an edge can be added from the later event
(usually the one just created) without editing the earlier one. The edge direction is set
explicitly when adding a relation (the form's "Direction" choice picks which event is the
follower), not inferred from timeline list position, so an event can be placed before a
later-listed one. `happens_before` is not stored; read a `follows` edge backwards. Causality and
arc membership are deferred (see [future_work.md](future_work.md)).

The timeline list remains the canonical chronology for replay. Relationships add semantics,
validation diagnostics, and visualization; they do not change replay order. Directed edges whose
`source` (the follower) is at or before `target` in the list order produce order-conflict
warnings; directed cycles produce cycle warnings. Warnings are derived (like replay) and surfaced
in tools and the UI; they do not block edits. Structural errors (unknown event ids, self-loops,
duplicate edges) are rejected at the tool and form boundary.

The Timeline page renders the relations as a Mermaid graph that flows left-to-right in
chronological order (earlier events on the left). Directed edges encode the kind by line style
(solid `follows`, thick `directly_follows`) with a legend below the graph rather than per-edge
labels, and conflicting edges are drawn red. `during` is *not* drawn as an edge: events linked
(transitively) by `during` are wrapped in a dashed outlined subgraph box. Because no edge forces a
rank gap between them, Mermaid/dagre lets the concurrent members settle on the same rank (a shared
vertical band), and the box keeps them visually connected.

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
  character (intimacies).
- Replay starts from the baselines and applies each event's world-state effects, then each of
  its signals' character-state effects, in **timeline list order**, up to and including the
  requested position. Event relationships do not affect replay order.

Replay is tolerant of dangling references: an effect that targets a missing entry or intimacy
(for example, strengthening an intimacy a later edit removed) is skipped silently. Detecting
and surfacing such conflicts is planned future work, not a replay error.

## Editing Rules

- Inserting, reordering, or deleting events is always allowed; derived state simply replays
  differently. The model accepts temporarily inconsistent effect references.
- Deleting a character does not delete events or their signals referencing that character;
  replay skips signals whose `character_id` no longer resolves.
- Intimacy review behavior (merging duplicates, strengthening instead of duplicating, pruning
  stale intimacies, preferring small cumulative changes) is a planned agent workflow that would
  layer on top of these primitives (tracked in [future_work.md](future_work.md)). The data model
  only provides the primitive operations; the intimacy review workflow would propose and review
  effects before they are applied (see
  [architecture_agent_workflows.md](architecture_agent_workflows.md)).

## Agent Access

Agent tools provide simple CRUD over the editable entities (narrative style fields, world facts,
baseline world state, characters, events with world-state effects and signals, event
relationships) plus read access to derived state at any timeline position. Tools mutate the in-memory `World` and write through
to disk, the same as user edits via forms.

Intimacy effects are a planned exception: today the agent authors intimacy effects directly, but
the intended design is that it should not. Under the planned intimacy review workflow the agent
would describe the intended change in natural language and the workflow would propose, review, and
apply the concrete effects, returning a diff. The structured effect operations below remain the
underlying data model and stay directly editable in the UI; only the agent's authoring path would
change. This workflow is tracked in [future_work.md](future_work.md) (see
[architecture_agent_workflows.md](architecture_agent_workflows.md)).
