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
- chat history associated with the project
- schema version for validation and future migration

World metadata stores project-level information such as title, description, tags, and created/updated timestamps.

## Story Bible Model

The Story Bible holds structured reference material for the story world. The initial model includes:

- Characters: named people or entities with descriptive fields, goals, relationships, and notes.
- Locations: named places with descriptive fields and notes.
- Lore entries: world facts, history, concepts, or reference notes with tags.
- Narrative Style: the intended tone, themes, writing style, etc.

These records are structured so important world information stays editable, reusable, and accessible to agent tools.

## Scene Model

Scenes represent prose. Each scene contains:

- an identifier
- a title
- a short summary
- Markdown prose
- optional notes

Scenes are ordered because narrative sequence matters.

## Chat History Model

Chat history stores the ongoing conversation between the writer, assistant, and tool activity associated with the project. It is part of the portable world so the collaboration record can travel with the project.

## App Data Model

App data is not part of the portable world. It includes:

- model profiles
- app preferences
- secrets

Secrets such as API keys are always local-only and must not appear in exported project data.

## Form Rendering Behavior

Story Bible forms render one field per canonical data-model field.

- List fields such as goals, relationships, and tags render as add/remove lists.
- Multi-line text fields render as textareas sized to the field's purpose.
- Short fields such as names and titles render as single-line inputs.

The UI should present characters, locations, and lore entries as structured forms rather than raw JSON.

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
