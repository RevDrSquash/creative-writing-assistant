# Story Bible Forms and Data Model

## Purpose

Story Bible forms give writers a structured way to edit world reference material without managing raw JSON. The forms write to the same in-memory `World` object that agent tools use, so user edits and agent edits share one source of truth.

## Data Boundaries

The data model has two layers:

- **World data**: portable story project content.
- **App data**: local configuration that supports the app but is not exported as part of the story world.

World data is the canonical project record. App data stays outside the exported world.

## World Data Model

The `World` is the root object for a project. It contains:

- world identity and metadata
- Story Bible data
- ordered scene data
- schema version for validation and future migration

World metadata stores project-level information such as title, description, tags, and created/updated timestamps.

## Story Bible Model

The Story Bible holds structured reference material for the story world. It is event-sourced;
the authoritative model description lives in [story_bible_model.md](story_bible_model.md). In
summary it contains:

- Narrative Style: premise, tone, themes, and writing style for the project.
- World Facts: stable setting facts. Locations and lore are world facts, not separate types.
- Baseline World State: pressures, open threads, and consequences at the start of the timeline.
- Characters: stable identity and baseline state with intimacies. Ephemeral scene stance is not
  stored on the character; it lives on the scene (see the Scene Model below).
- Timeline: an append-only list of Events carrying world-state effects and character Signals,
  plus a separate list of typed Event Relationships that define chronology.

World state and character state at any timeline position are derived by replaying event
effects over the baselines; derived views are read-only. These records are structured so
important world information stays editable, reusable, and accessible to agent tools.

## Scene Model

Scenes represent prose. Each scene contains:

- an identifier
- a title
- a short summary
- Markdown prose
- optional notes
- a scene blueprint: editable scene-card inputs (premise, purpose, POV, scene frame, characters, events, constraints, notes)
- generated artifacts: stances, outline, and generation metadata (fingerprint, timestamp)

Scenes are ordered because narrative sequence matters.

### Scene Blueprint

The scene blueprint holds **inputs only** — the scene card the writer and main agent edit:

- **Premise** and **Purpose**: what happens and why the scene exists.
- **POV**: point-of-view character or narrator.
- **Scene frame**: `starting_state` (how the scene opens), `central_conflict` (the conflict it
  dramatizes), and `required_resolution` (the outcome later scenes depend on). Beat-level
  planning is left to the generation workflow.
- **Character ids**: participating characters (`character_ids`).
- **Event links**: `event_ids` (enacted events — every event dramatized on-page in this scene;
  a scene enacts one or more events; each event may be enacted by at most one scene) and
  `related_event_ids` (context-only — off-page events or events enacted elsewhere). Both are
  scene-local scratch. Deleting an event prunes its id from every blueprint automatically.
- **Constraints** and **Notes**: hard limits and free-form planning notes.

### Scene Generated

Workflow output lives on `Scene.generated`:

- **Stances**: per-character ephemeral posture (`SceneCharacterStance`).
- **Outline**: beat list.
- **blueprint_fingerprint** and **generated_at**: staleness detection; when the fingerprint no
  longer matches the current blueprint, the scene is **stale** until the user regenerates.

Blueprint and generated fields are excluded from Story Bible replay; they are scene-local scratch,
not event-sourced.

## Scene Editor Layout

The workspace scene editor uses one edit/preview toggle on the title row. A scene that has been
generated opens in preview (view) mode; a scene that has never been generated opens in edit mode
with the Blueprint expansion open, so the writer can review the scene card and trigger
generation. In edit mode the writer sees title, summary, and Markdown prose as
inputs; in preview mode those fields render as read-only labels and Markdown preview. Scene
notes stay editable in an expansion below the prose editor. Delete scene lives in the editor
header (next to the edit/preview toggle), not in the sidebar scene list.

The scene blueprint (inputs) and generated outline/stances are shown only in edit mode and hidden in
preview, so the reading view stays focused on the prose while planning scaffolding remains
available while writing. The title row includes **Generate** / **Regenerate** (user-triggered
workflow), a **Stale** badge when the blueprint changed after generation, and generation status
polling while a run is active.

Agent scene tools can read prose and blueprints (`read_scene`, `read_scene_blueprint`), propose
and edit blueprints (`propose_scene`, `update_scene_blueprint`), and manage scene metadata and
navigation (`list_scenes`, `select_scene`, `update_scene`, `delete_scene`). The main agent cannot
edit scene prose directly; generation is user-triggered from the editor.

## Chat History Model

Chat history stores the ongoing conversation between the writer, assistant, and tool activity associated with the project. The long-term intent is for it to be part of the portable world so the collaboration record can travel with the project; for now it lives in an app-local store and is not exported (see `known_issues.md`).

## App Data Model

App data is not part of the portable world. It includes:

- model profiles
- app preferences
- secrets

Secrets such as API keys are always local-only and must not appear in exported project data.

## Form Rendering Behavior

Story Bible forms render one field per canonical data-model field.

- Structured list fields such as intimacies, effects, signals, and signal evidence entries
  render as add/remove lists. Evidence entries (direction, intimacy, 1–5 strength, rationale)
  are the user's manual lever over derived intimacy rank.
- Tag lists render as a single comma-separated input.
- Multi-line text fields render as textareas sized to the field's purpose.
- Short fields such as names and titles render as single-line inputs.
- Derived state (world state or character state at a timeline position) renders read-only,
  with a selector for the timeline position.

The UI should present characters, world facts, and events as structured forms rather than raw JSON.

The Timeline page shows a scrollable, zoomable event-relationship graph (Mermaid).
Clicking a graph node opens an inline editor pane for that event (replacing the old
chronological list). Events are appended from the UI and selected automatically;
relationships define order. Quick-connect buttons on the selected event ("Follows…",
"Directly follows…", "Depends on…", "During…") let the user click a second graph node
to create a typed edge. Each event editor still includes a Relationships section for
adding reverse-direction edges and removing existing ones. The deep-link route
`/workspace/events/{id}` remains available for the same editor.

## Validation Behavior

Field-level validation follows the Pydantic model constraints.

Invalid values surface inline errors and do not persist to world state.

## Save Behavior

Changes write through to world state on focus loss or explicit save.

Persistence to disk follows the app's broader save policy, but the in-memory `World` object should reflect valid form changes promptly.

## User And Agent Edit Behavior

World state is the source of truth for both user edits and agent tool edits.

If the user and agent edit the same Story Bible entry, the current rule is last write wins. The form should not overwrite the user's in-progress edit while they are typing, but it should re-read from world state on the next focus-in.

Live conflict resolution UI is out of scope for the initial Story Bible form behavior.
