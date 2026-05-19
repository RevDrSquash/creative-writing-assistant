# ZIP Import/Export Behavior

## Purpose

ZIP import/export preserves a complete story world as a portable local file while keeping app-level configuration and secrets outside the shared project data.

The exported ZIP represents the world, not the user's whole app installation.

## Export Contents

An exported world ZIP contains:

```text
world.zip
|-- world.json
|-- scenes/
|   |-- scene_<id>.md
|   |-- scene_<id>.md
|   `-- ...
`-- assets/
```

### `world.json`

`world.json` contains the serialized `World` object:

- world identity and metadata
- Story Bible data
- ordered scene records
- chat history associated with the project
- schema version

Each exported `Scene` record remains in `world.json`, but its `markdown` field is set to an empty string. Scene prose is stored in the per-scene Markdown files instead.

### Scene Markdown Files

Each scene is exported as a Markdown file at:

```text
scenes/scene_<id>.md
```

The file contains the full Markdown prose for that scene.

### Assets Folder

The ZIP includes an `assets/` folder reserved for future attachments. It may be empty.

## Excluded Data

Exports must not include local-only app data:

- API keys
- `.env` contents
- model profiles
- workflow definitions
- app preferences
- other local secrets or machine-specific configuration

## Import Behavior

Import reads `world.json`, validates it, loads scene Markdown files back into their matching `Scene.markdown` fields, and replaces the active world with the imported world.

If the active world has unsaved changes, the app asks for confirmation before replacing it.

## Schema Version Handling

Import validates the imported world's `schema_version` against the current schema.

If the schema version does not match, import fails with a clear error. Migration is deferred until schema migrations are explicitly implemented.

## Model Profile References

Imported chat history may reference model profile names that do not exist in the local app configuration.

Those chat messages are allowed to load. Future LLM calls should fall back to the current default model profile when a referenced profile is unavailable.
