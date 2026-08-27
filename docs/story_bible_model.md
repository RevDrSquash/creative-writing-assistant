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
- **Timeline**: an append-only list of Events (creation order is a tie-breaker only).
- **Event Relations**: typed edges between events that define chronology.

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
``Scene.generated.stances`` as a sparse per-character list (`SceneCharacterStance`: `character_id`,
`mood`, `intent`, `tactics`, `stakes`), where `mood` is a list of short statements and the rest are
single strings. Generated stances are workflow output (see
[architecture_agent_workflows.md](architecture_agent_workflows.md)); they are freely editable in the
UI but regenerate overwrites them. Stance is not event-sourced and is excluded from replay.

A scene is a unit of prose in which something changes — continuous dramatized action. Since
change is represented by events, a scene enacts one or more events through its blueprint:
`event_ids` (the events the scene dramatizes on-page) and `related_event_ids` (context-only
events relevant to the scene without being enacted — for example, an off-page event or one
enacted in another scene). Each event may be enacted by **at most one** scene; tools reject a
second scene claiming the same enacted event. An unenacted event is either not yet placed or
deliberately off-page — it still affects derived state via replay.

These links are scene-local scratch on the blueprint, not authoritative structural edges on the
timeline. They are validated when drafting; deleting an event prunes its ids from every blueprint
(see [forms_and_data_models.md](forms_and_data_models.md)). See the Scene model in
[forms_and_data_models.md](forms_and_data_models.md).

### Intimacy

A character-subjective belief, attachment, value, fear, desire, or relationship assumption.
Fields: `id`, `text`, and `strength` (`minor`, `moderate`, `major`, or `defining`). Strength
defines the intimacy's impact on the character's behavior. Intimacies live in character baseline
state.

An intimacy's rank at any timeline position is **derived** during replay from accumulated
signal evidence rather than mutated by effects. Contradicting evidence erodes rank; erosion
below `minor` derives to a **dormant** (no-strength) state while the intimacy and its evidence
history remain stored and can re-strengthen. The accumulation formula lives in
`app/world/evidence.py` and is specified below.

### Event

An atomic story fact — a specific thing that happens at a particular point in story time, at
any scale (from "Brad is murdered" to "Alice wears her new dress for the first time"). Events
are the only carriers of change: world-state effects and character signals attach to events, and
replay derives state from them. Big plot developments decompose into multiple events.

**Timeline leanness:** the test for eventhood is plot necessity, not size. If nothing in the
story depends on a detail happening at a specific time, it should *not* be an event — incidental
detail belongs to the prose. Over-populating the timeline with trivia constrains scene generation
and makes scenes worse. Plot-necessary details that are omitted from the timeline cannot be seen
by replay or continuity tools.

Fields: `id`, `title`, `description`, a list of world-state effects, and a list of Signals.
Events are stored in `timeline` (append-only storage; creation order breaks ties among unrelated
events). Canonical chronology is derived from directed relationships (see below). Events do not
store timestamps. Relationships between events are stored on the Story Bible as
`event_relations`, not on the Event itself. Events do not store a back-reference to scenes;
`read_timeline` and `read_event` show which scene (if any) enacts each event.

When creating events via agent tools, the first event needs no relations; every subsequent
event must include at least one inline relation linking it to an existing event.

### Event Relationship

A typed edge between two events. Stored on `StoryBible.event_relations` as a flat list.
Fields: `id`, `kind`, `source_id`, `target_id`.

Kinds (for directed kinds, `source` is the later event and `target` the earlier one):

- `directly_follows` (directed, tight): `source` immediately follows `target` on a short
  timescale and they share moment-to-moment continuity (location, time of day, who is present).
  Chains of `directly_follows` form one scenario.
- `depends_on` (directed, causal): `source` is narratively or causally dependent on `target`;
  the target must have happened (and be known) for the source to make sense.
- `follows` (directed, loose): `source` happens after `target` with no required continuity or
  causality (time-skips, cross-arc ordering).
- `during` (symmetric): `source` and `target` are concurrent; the pair is unordered.

At most one directed edge is allowed per ordered pair (any kind). A directed edge and a
`during` edge between the same two events are mutually exclusive.

Chronology is derived entirely from directed edges for replay, display (`read_timeline`, the
Timeline page graph and editor), and derived-state "as of" selectors. Among events with no directed path,
creation order in `timeline` is the tie-breaker. `chronological_order()` performs a stable
topological sort of directed edges (`target` before `source`), using creation order to break
ties. Directed cycles are rejected when adding a relation; legacy cycles are warned and replay
appends leftover nodes in creation order. `happens_before` is not stored; read a directed edge
backwards. Arc membership beyond these primitives is deferred (see [future_work.md](future_work.md)).

Unanchored events (no relations when other events exist) surface as derived warnings in tools
and the UI but do not block edits.

`effect_diagnostics()` warns when an update/remove effect targets an intimacy or world-state
entry that is not present at that event's replay position (for example, strengthening an intimacy
before it is added). Replay still skips such effects silently; warnings are derived and surfaced
in tools and the UI but do not block edits. Structural relation errors (unknown event ids,
self-loops, duplicate edges, cycles) are rejected at the tool and form boundary.

The Timeline page renders the relations as a Mermaid graph that flows left-to-right in
chronological order (earlier events on the left). The diagram renders at its natural size
(not shrink-to-fit) inside a horizontally scrollable container: the mouse wheel scrolls the
graph sideways, Ctrl+wheel (or the pinned zoom buttons) zooms it. Nodes are
clickable: selecting one highlights it and opens an inline editor pane beneath the graph.
Quick-connect buttons create a relation from the selected event to a subsequently clicked
node. Directed edges encode the kind by line style (solid `follows`, thick `directly_follows`,
dotted `depends_on`) with a legend below the graph rather than per-edge labels, and
cycle-participating edges are drawn red. `during` is *not* drawn as an edge: events linked
(transitively) by `during` are wrapped in a dashed outlined subgraph box.

### Signal

A specific character's subjective interpretation of an Event. Signals are embedded in the
Event that produced them, which keeps the link between event and interpretation structural.
Fields: `id`, `character_id`, `interpretation` (free text), `evidence` (scored intimacy
relationships), `effects` (structural creation/rewording records and leftover legacy
mutations), optional `review` metadata, and `evidence_schema_version`.

Each evidence entry records the affected intimacy id, a `direction` (`supports` or
`contradicts`), an ordinal strength (1–5), a brief rationale, a `novelty` tag
(`novel` or `duplicate`, default `novel`), optional confidence, and an `author`
provenance tag (`interpretation`, the default, or `plot_agent` for the plot sub-agent's
bounded nudges — capped at strength 1). Interpretation re-runs replace only
`interpretation`-authored entries, so plot-agent nudges survive them. Structural records
for intimacy creation and rewording remain effect-shaped (see Character-State Effects
below); review metadata from the interpretation workflow lives on the signal, not on
those records.

## Effects

Effects are the structured deltas that replay folds over the baselines. They are small,
explicit operations rather than free text.

### World-State Effects (on Events)

- `add_entry`: add a world-state entry (carries the new entry).
- `update_entry`: replace the text/kind of an existing entry by `entry_id`.
- `remove_entry`: remove an entry by `entry_id`.

### Character-State Effects (on Signals)

- `add_intimacy`: add an intimacy (carries the new intimacy). Survives in the evidence-based
  model as the event-sourced **creation record**: new intimacies are always created at `minor`,
  and the creating signal also carries an evidence entry so the history explains why the
  intimacy exists.
- `set_intimacy_strength`: change an existing intimacy's strength by `intimacy_id`
  (strengthen or weaken). **Legacy under the evidence-based model:** rank becomes derived, so
  no new `set_intimacy_strength` effects are authored; the v8→v9 migration converts existing
  ones into equivalent evidence entries.
- `update_intimacy`: replace the text of an existing intimacy by `intimacy_id`. Survives as
  the event-sourced **rewording record** (wording evolution is separate from rank change).
- `remove_intimacy`: remove an intimacy by `intimacy_id`. **Legacy under the evidence-based
  model:** intimacies are never removed by the pipeline — they erode. Existing effects are
  honored by replay as erode-to-dormant markers; no new ones are authored.

## Evidence-Based Intimacy State

Decided in the 2026-08-21 project review; the evidence data model (schema v9) and the
deterministic accumulation/threshold engine are shipped. The per-character interpretation
graph (`interpret_intimacy`) is also shipped. Triggering, parallel fan-out, and
deterministic apply run through `JobManager` (`start_event_interpretation`). Agent
tools no longer persist intimacy effects or evidence; incoming signals are hints.
There is no dual-path rollout period.

- **Representation: derived accumulation.** Evidence lives on signals as stored source data;
  intimacy rank is computed during replay by a deterministic accumulator. The pipeline writes
  no materialized rank-change effects, and there is no explicit rank-override channel in v1 —
  the user's manual levers are editing baseline intimacies and editing signal evidence entries
  (both UI-editable), with replay recomputing rank.
- **Evidence entries.** Each entry records the affected intimacy id, a `direction`
  (`supports` | `contradicts` — mixed evidence is represented as multiple separate entries,
  and prompts must state this explicitly), an ordinal strength, and a brief rationale.
- **Distinct events and recency.** Chains of `directly_follows` relations count as one
  scenario when weighing evidence breadth: repeated evidence from one scenario is worth less
  than the same evidence across distinct scenarios. "Recent" is defined by the stable total
  order from `chronological_order()`.
- **Accumulator shape.** Replay folds approved evidence through `accumulate_rank` in
  `app/world/evidence.py`: a pure, side-effect-free function (observations in → rank
  state out) that replay and a planned plot-editor agent can both call. Rejected
  signals (`review.decision == rejected`) contribute nothing to replay — neither
  evidence nor structural effects fold until a re-run changes the verdict; missing
  review counts as approved. The function never reads the world — callers attach
  scenario id, chronology, and novelty. See "Rank accumulation" below.
- **Creation and erosion are symmetric.** Intimacies are never removed by the pipeline:
  contradicting evidence erodes rank, and erosion below `minor` derives to a dormant
  (no-strength) state while the intimacy and its evidence history remain stored and can
  re-strengthen. Creation is strengthening from nothing: the `add_intimacy` record mints the
  id and wording at the conservative floor (`minor`), and the creating signal carries an
  evidence entry explaining why the intimacy exists. Full removal/archival belongs to a
  separate maintenance/consolidation workflow (future work, not part of v1).
- **No candidate/incubating intimacies in v1.** Approved new-intimacy proposals create
  canonically at `minor`.
- **Migration.** The v8→v9 migration converts existing `set_intimacy_strength` effects into
  equivalent evidence entries; `add_intimacy` / `update_intimacy` effects are kept as the
  creation/rewording records; legacy `remove_intimacy` effects are honored by replay as
  erode-to-dormant markers and no new ones are authored.
- **Reordering posture.** Replay recomputes rewordings and evidence deterministically under
  any relation edit; records that land before their intimacy's establishing record are skipped
  and surfaced as `effect_diagnostics()` warnings (extending the existing dangling-effect
  behavior to evidence entries). Semantic re-analysis after a reorder is manual (the re-run
  action), never automatic.

The workflow that produces signals and evidence (per-character interpretation, review, apply)
is described in [architecture_agent_workflows.md](architecture_agent_workflows.md).

## Replay Semantics

The replay engine is a pure function over the Story Bible:

- Input: the bible plus an optional timeline position (an event id, meaning "after this event
  has been applied"; absent means "after the full timeline").
- Output: the derived world state (list of world-state entries) and the derived state of each
  character (intimacies).
- Replay starts from the baselines and applies each event's world-state effects, then each of
  its signals' structural records and evidence entries, in **chronological order**
  (relation-derived with creation order tie-break), up to and including the requested position.

Replay is tolerant of dangling references: an effect that targets a missing entry or intimacy
(for example, strengthening an intimacy a later edit removed) is skipped silently.
`effect_diagnostics()` surfaces these as warnings in tools and the UI; replay does not error.
Preventing or auto-repairing dangling effects on edit is tracked in
[known_issues.md](known_issues.md) ("Dangling effect references are warned but not prevented").

Replay folds each signal's evidence entries into derived rank via `accumulate_rank`: an
intimacy's rank at a position is computed from its baseline plus the accumulated evidence
up to that position, never stored. Evidence that lands before its intimacy's establishing
record is skipped and surfaced via `effect_diagnostics()`, the same posture as dangling
mutation effects. Legacy `remove_intimacy` effects derive `dormant` and reset that
intimacy's evidence track so later evidence can re-strengthen from nothing. Leftover
`set_intimacy_strength` effects still set rank directly and reset the track (the v8→v9
migration converts them to evidence, so this path is rare).

## Rank accumulation

`accumulate_rank(baseline_rank, observations) -> RankState` is the what-if oracle.
Replay builds `EvidenceObservation` values from stored signal evidence (plus
`chronological_order` index and the `directly_follows` scenario id) and calls it
after each approved evidence entry. The same function accepts a hypothetical
observation list with no bible access.

A migrated world that had a single `set_intimacy_strength` effect will not
necessarily reconstruct that exact rank: the engine follows the accumulation
rules below rather than last-write.

### Weights and modifiers

Ordinal strength maps to a raw weight: incidental 1 → 1.0, noticeable 2 → 2.0,
meaningful 3 → 3.5, pivotal 4 → 5.5, identity-shaking 5 → 9.0. Modifiers
multiply that weight:

- **Scenario repeat:** the first observation for an intimacy in a
  `directly_follows` component is full weight; later ones in the same scenario
  are × 0.4. Isolated events are their own scenario.
- **Duplicate novelty:** reviewer-tagged `duplicate` entries are × 0.35. Untagged
  or `novel` entries are full weight. Both modifiers stack.

Support and contradiction are accumulated separately (contradictory evidence is
not cancelled away in the explanation). Standing net is `seed + support -
contradict`, where the seed parks the baseline rank inside its hysteresis band
(dormant 0, minor 5, moderate 8.5, major 13, defining 20).

**Recent momentum** is the signed total of observations from the last three
distinct contributing events. Effective net is `standing_net + 0.25 *
momentum_net`, so recent evidence is slightly amplified without discarding
long-term history. "Recent" is position in the observation list's event order,
which replay fills from `chronological_order()`.

### Thresholds and hard rules

Promotion (effective net ≥) and demotion (effective net ≤) are asymmetric:

| Current rank | Promote at | Demote at |
| --- | --- | --- |
| dormant | 3.5 → minor | — |
| minor | 9.5 → moderate | 1.5 → dormant |
| moderate | 15.5 → major | 5.0 → minor |
| major | 22.0 → defining | 9.5 → moderate |
| defining | — | 10.0 → major |

Thresholds are calibrated for a lean timeline: one or two strong novel beats can cross a band,
while the 4.5–6 point hysteresis overlaps still absorb momentum jitter. Successive distinct
meaningful supports can promote minor → moderate → major; repeats in one scenario are diminished.
Defining is resistant — two ordinary contradictions will not crack it.

Hard rules on top of the numbers:

- Rank changes at most one step per observation.
- A single ordinary event (strength 1–4) never changes rank by itself.
- A single identity-shaking event (strength 5) may change rank except when the
  current or target rank is `defining`.
- Reinforcement without a rank change is the normal outcome.

Legacy `remove_intimacy` is not scored: replay sets `dormant` and clears the
track. Creation (`add_intimacy`) mints the intimacy at `minor` and its creating
evidence is ordinary accumulation from that seed — one creating signal does not
promote it.

### Explanation and distance-to-threshold

`RankState` lists every weighted contribution, every rank crossing (which
signals moved the threshold and why), and the remaining distance to the next
promotion and demotion boundaries. `explain_intimacies` / `explain_intimacies_at`
expose this for a character at a timeline position. Character-arc markdown and
`read_character` / `read_world_state` append the distances next to each derived
intimacy (for example `4.5 from moderate, 3.5 above dormant`).

Because the hard rules can hold a rank back even when the score has crossed a
threshold (for example a single strength-4 event pushing effective net past a
promote boundary), a met-but-gated threshold is annotated instead of rendered
as a negative distance: `score met for moderate; needs another event to cross`
(promotion) or `eroded to the minor threshold; needs another event to cross`
(demotion).

## Character Arc Derivation

`derive_character_arc` (`app/world/character_arc.py`) is a pure function over the bible. It
returns a character's derived state entering a timeline window, the transitions inside that
window, and the state after it. Chronology is the same graph-derived order replay uses.

- **Start state**: `DerivedCharacterState` **before** the start event (`derive_state_at` at the
  start index). When no start event is given, this is the baseline.
- **End state**: `DerivedCharacterState` **after** the end event. When no end event is given,
  this is the full timeline.
- **Window**: inclusive of both endpoints. `transitions` has one entry per event in the window
  that carries a signal for this character (events without such a signal are omitted). Each
  transition records the event id/title/description, the signal interpretation, and
  human-readable `changes` (for example "Added intimacy … (moderate)", "Strengthened … to
  defining", "Derived rank …: minor to moderate"). Start and end intimacy lines include
  distance-to-threshold from the accumulator. The names `transitions` and `changes` are
  change-kind-agnostic so later state kinds (appearance and so on) can be added without
  renaming the API.
- **Validation**: unknown event ids and a start that is chronologically after the end raise
  `ValueError`. Tools that expose this derivation translate those errors to `ToolException`
  listing valid event ids.

`format_character_arc` renders the arc as markdown with `### State at start`,
`### Transitions` (per event), and `### State at end`. Tools and the scene workflow reuse this
renderer so scoped character context cannot leak late-story state into an earlier window.

## Editing Rules

- Adding or deleting events is always allowed; derived state simply replays differently. To
  change chronology, edit event relations rather than reordering the timeline list. The model
  accepts temporarily inconsistent effect references (including stale signals after relation
  edits); improving that workflow is deferred.
- Deleting a character does not delete events or their signals referencing that character;
  replay skips signals whose `character_id` no longer resolves.
- Intimacy changes are the domain of the evidence-based interpretation workflow (see
  "Evidence-Based Intimacy State" above and
  [architecture_agent_workflows.md](architecture_agent_workflows.md)): signals carry evidence,
  rank is derived, and a separate maintenance workflow (future work) handles global
  consolidation (merging duplicates, pruning stale intimacies). The data model only provides
  the primitive records; the workflow proposes and reviews them before they are applied.

## Agent Access

Agent tools provide simple CRUD over the editable entities (narrative style fields, world facts,
baseline world state, characters, events with world-state effects and signals, event
relationships) plus read access to derived state at any timeline position. Tools mutate the in-memory `World` and write through
to disk, the same as user edits via forms. Write tools that take several sibling
prose fields (`update_narrative_style`, `upsert_character`) treat each field as its
own JSON argument and reject leftover tool-call markup (XML `<parameter>` tags or
sibling field tags concatenated into an earlier string) with `ToolException` so the
model can retry instead of persisting the leak.

`read_character_arc(character_id, start_event_id="", end_event_id="")` returns the formatted
arc for a character. Start state is entering the window (before the start event); end state
is after the window. Blank window ids mean the start or end of the timeline.

`read_character` accepts the same optional window ids. When either is provided, the
"Current State (after full timeline)" section is replaced by the scoped arc so late-story
state cannot leak into an earlier scene's context. Unknown character or event ids, and a
start that is chronologically after the end, raise `ToolException` listing valid ids.

Intimacy rank is derived from signal evidence. The intimacy interpretation
workflow runs automatically after `add_event` / `update_event` (and from the
event editor's re-run action) for each relevant character. Agent-authored
signals are hints (`character_id` + `interpretation`); the apply stage writes
approved evidence and creation/rewording records. Evidence entries and
baseline intimacies stay directly editable in the UI. See "Evidence-Based
Intimacy State" above and
[architecture_agent_workflows.md](architecture_agent_workflows.md).
