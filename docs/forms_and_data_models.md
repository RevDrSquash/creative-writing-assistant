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

- Narrative Style: the intended tone, themes, writing style, etc.
- World Facts: stable setting facts. Locations and lore are world facts, not separate types.
- Baseline World State: pressures, open threads, and consequences at the start of the timeline.
- Characters: stable identity, baseline state with intimacies, and ephemeral scene stance.
- Timeline: an ordered list of Events carrying world-state effects and character Signals.

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

Scenes are ordered because narrative sequence matters.

## Scene Editor Layout

The workspace scene editor uses one edit/preview toggle on the title row. In edit mode
the writer sees title, summary, and Markdown prose as inputs; in preview mode those
fields render as read-only labels and Markdown preview. Scene notes stay editable in
an expansion below the prose editor.

Agent scene tools can read and replace prose (`read_scene`, `replace_scene_text`) and
manage scene metadata and navigation (`list_scenes`, `create_scene`, `select_scene`,
`update_scene`, `delete_scene`). Use `update_scene` to rename a scene or change its
summary without editing prose.

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

- Structured list fields such as intimacies, effects, and signals render as add/remove lists.
- Tag lists render as a single comma-separated input.
- Multi-line text fields render as textareas sized to the field's purpose.
- Short fields such as names and titles render as single-line inputs.
- Derived state (world state or character state at a timeline position) renders read-only,
  with a selector for the timeline position.

The UI should present characters, world facts, and events as structured forms rather than raw JSON.

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
