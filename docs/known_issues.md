# Known / Open Issues

This document tracks known limitations, edge-case bugs, and architectural debt that are
understood but not yet resolved. Each entry notes severity, where it lives, and a possible
fix so the context is not lost between phases.

## 1. Fuzzy scene-match fallback can be slow on large scenes

- **Severity:** Low (latency, not correctness)
- **Location:** `app/tools/scene.py` — `_find_single_fuzzy_candidate`
- **Introduced:** Phase 3
- **Symptom:** When `replace_scene_text` finds no exact match for `target`, it falls back to a
  windowed fuzzy search that is roughly `O(len(document) × window_range × len(target)²)`. On a
  multi-thousand-character scene with a long `target`, this can take several seconds and stall
  the agent loop.
- **Why it usually doesn't bite:** The common path is an exact verbatim quote from the model,
  which short-circuits before the fuzzy search runs. Only drift on a large document triggers it.
- **Possible fix:** Cap the searchable document size, or cheaply pre-filter candidate offsets
  (e.g. anchor on a rare substring of `target`) before running `SequenceMatcher` on each window.

## 2. Chat history is not yet part of the portable world

- **Severity:** Low (documented deviation, not a bug)
- **Location:** `app/persistence/chat_messages.py` (chat store) vs `app/world/models.py`
  (`World` has no chat field)
- **Introduced:** Phase 5
- **Symptom:** `docs/forms_and_data_models.md` and `docs/zip_import_export.md` originally
  described chat history as part of the portable world. The Phase 5 `World` model keeps chat
  history in its existing app-local store (`data/chat_history.json`), so ZIP export/import
  does not carry the collaboration record. Both docs now note this.
- **Why it is acceptable for now:** Chat history has no structural ties to the bible or
  scenes, and moving it mid-phase would have coupled the world refactor to the chat store.
- **Possible fix:** Add a `chat_history` field to `World`, migrate the chat store into it,
  and include it in `world.json` on export.

## 3. UI form edits are not transactional against save failures

- **Severity:** Low (rare failure path)
- **Location:** `app/ui/components/story_bible_forms.py`, `app/ui/pages/workspace.py`
- **Introduced:** Phase 5 (surfaced by the Phase 5 world-transaction work)
- **Symptom:** UI inputs are bound directly to world objects, so the mutation has already
  happened by the time the change handler calls `save_world()`. If that save fails (e.g. an
  external process briefly locks `world.json`), the in-memory world and disk diverge until the
  next successful save. Agent tools do not have this problem: they mutate inside
  `world_transaction()`, which rolls the mutation back when the save fails.
- **Why it usually doesn't bite:** The save lock in `app/world/store.py` eliminates
  intra-process save races; `JsonFileWorldStore.save()` now retries `os.replace` on transient
  external locks (Windows antivirus/indexers). UI handlers notify on final failure via
  `save_world_ui()`. The next keystroke still resaves the full world when the lock clears.
- **Possible fix:** Route UI edits through id-based accessors instead of direct object bindings
  so they can use `world_transaction()` too, or add a save-failure notification that prompts a
  manual resave. (User notification on failure is implemented; full transactional UI edits remain
  open.)

## 4. Unterminated-canvas rollback can miss appends after a mid-run scene switch

- **Severity:** Low (edge-case correctness)
- **Location:** `app/ui/components/chat.py` — `_apply_canvas_flush_events`
- **Introduced:** Phase 5 (replaces the older pre-run-snapshot rollback issue)
- **Symptom:** Rollback now restores the run's last authoritative scene text (so committed
  `replace_scene_text` edits survive a truncated `<canvas>` block). However, if the agent
  switches scenes mid-run and the truncated canvas text was optimistically appended to a
  scene other than the run's final one, that other scene keeps the partial in-memory append
  until its next authoritative write.
- **Why it usually doesn't bite:** It requires a scene switch and a truncated canvas block in
  the same turn, and the partial text is in memory only (not saved to disk).
- **Possible fix:** Track per-scene authoritative snapshots during the run instead of a single
  `run_scene` record.

## 5. UI-created blank entities get generic slug ids

- **Severity:** Low (cosmetic)
- **Location:** `app/ui/components/story_bible_forms.py` — `add_fact`, `add_entry`,
  `add_character`, `add_intimacy`, `append_event`
- **Introduced:** Schema version 2 (readable slug ids)
- **Symptom:** Entities created from the UI before the user types a name or title receive
  generic slugs (`char`, `char_2`, `event`, etc.) rather than descriptive ones. Agent-created
  entities slug from the supplied text at creation time and are usually more readable.
- **Why it is acceptable:** The slug is frozen at creation; the user can delete and recreate if
  they care, and the display name is independent of the id.
- **Possible fix:** Re-slug on first non-blank save of the primary text field, or prompt for a
  name before creating the entity.

## 6. World schema versions 1–2 are rejected; no migration below v3

- **Severity:** Low (documented breaking change)
- **Location:** `app/persistence/world.py` — `migrate_world_payload`; `app/world/models.py`
  — `SCHEMA_VERSION` (currently 9; the code is authoritative, this number drifts)
- **Introduced:** Schema version 2 (readable slug ids)
- **Symptom:** `migrate_world_payload` upgrades stored worlds from v3 through the current
  version, but loading a `world.json` (or ZIP import) with `schema_version` 1 or 2 fails with
  a clear unsupported-version error. Those worlds must be hand-converted (re-slug entity ids
  and repair signal `character_id` references) before the app will load them.
- **Why it is acceptable:** Migrating v1/v2 would need to rewrite every cross-reference; the
  project has a single dev world that is already past those versions.
- **Possible fix:** Add a one-shot migration script or import-time rewriter that maps old hex
  ids to new slugs and updates all references.

## 8. Dangling effect references are warned but not prevented

- **Severity:** Medium (correctness of derived state, surfaced but not blocked)
- **Location:** `app/world/replay.py` — replay fold and `effect_diagnostics`; UI timeline
  warnings card; `read_timeline` / `read_event` / `read_world_state` tools
- **Introduced:** Graph-derived timeline order (chronology changes when relations are edited,
  making prior effect references invalid at replay time)
- **Symptom:** An event's `set_intimacy_strength`, `update_intimacy`, `remove_intimacy`,
  signal evidence entry, or world-state `update_entry` / `remove_entry` may target an id that
  is not present when that event is replayed (for example, evidence for an intimacy before
  the event that adds it).
  Replay skips the effect silently; `effect_diagnostics()` and the Timeline warnings card
  surface the problem but edits are still allowed.
- **Why it is acceptable for now:** Warning-first keeps authoring flexible while surfacing
  mistakes. Stale signals after relation edits are an accepted limitation until a reorder or
  repair workflow exists.
- **Possible fix:** Reject or auto-repair dangling effects when saving an event or when
  chronology changes (edit relations), or offer a guided fix in the UI (move the effect, add
  the missing entry first, or adjust relations).

## 7. Scene workflow continuity is limited without event links or character state

- **Severity:** Low (partially addressed; residual gaps)
- **Location:** `app/world/scene_context.py`, `app/graphs/scene_workflow.py`
- **Introduced:** Phase 3 (scene workflow); cross-scene context added 2026
- **Symptom:** The scene-writing workflow injects continuity context from neighboring scenes
  (previous scene full prose; next and related scenes by summary) and scoped character arcs
  (identity plus intimacies entering and during the scene) into stance and outline prompts.
  Remaining gap: scenes without event links fall back to list order only for neighbor
  selection.
- **Possible fix:** For list-order fallback, consider explicit scene-to-scene links when
  event linking is absent.

## 9. Save retry blocks the NiceGUI event loop on transient file locks

- **Severity:** Low (latency, not correctness)
- **Location:** `app/persistence/world.py` — `JsonFileWorldStore.save()` retry loop
- **Introduced:** Phase 5 (transient Windows lock retries)
- **Symptom:** When `os.replace` fails with a transient external file lock, the save helper
  retries with `time.sleep` (up to ~0.75s total). `save()` is called from sync UI handlers
  and the async chat task, both on the NiceGUI event loop, so all sessions can freeze for the
  duration of the retry window.
- **Why it usually doesn't bite:** Retries only run when an external process briefly holds the
  lock (Windows antivirus/indexers); the happy path is a single non-blocking replace.
- **Possible fix:** Offload saves to a worker thread, or make the retry async-aware at the UI
  boundary so the event loop is not blocked while waiting.

## 10. Scene blueprint event links (partially resolved)

- **Severity:** Low (advisory scaffolding, not source-of-truth data)
- **Location:** `app/world/models.py` (`SceneBlueprint.event_ids`,
  `SceneBlueprint.related_event_ids`); `app/tools/scene.py` — `propose_scene`,
  `update_scene_blueprint`; `app/tools/story_bible.py` — `delete_event`
- **Introduced:** Scene-to-event linking on scene proposal
- **Symptom (resolved):** Deleting an event used to leave dangling ids in scene blueprints.
  `delete_event` (tool and UI) now calls `prune_event_links` to remove the id from every
  blueprint's `event_ids` and `related_event_ids`.
- **Remaining:** Legacy worlds may still contain duplicate enactment (the same event listed in
  two scenes' `event_ids`). New writes enforce at-most-one enacting scene per event; duplicate
  enactment in existing data is surfaced as a warning in `read_event` / `read_timeline` but not
  auto-repaired.
- **Possible fix:** A one-time migration or repair tool to split or reassign duplicate enactments.

## 11. UI test teardown intermittently fails with a Windows file lock

- **Severity:** Low (test flake, not app behavior)
- **Location:** `tests/conftest.py` `user` fixture teardown → NiceGUI
  `nicegui_reset_globals()` → `app.storage.clear()` unlinking
  `.nicegui/storage-user-*.json`
- **Introduced:** Pre-existing on Windows; unrelated to any app change
- **Symptom:** Random `test_ui_pages.py` tests report an ERROR at teardown with
  `PermissionError: [WinError 32]` when NiceGUI deletes its per-test user-storage file while an
  external process (antivirus/indexer) briefly holds it. All tests themselves pass; only the
  fixture cleanup errors, and which test is hit varies run to run.
- **Why it is acceptable for now:** The flake is environmental and does not affect assertions
  or app code; re-running the suite typically passes clean.
- **Possible fix:** Wrap the storage cleanup in a retry (as `JsonFileWorldStore.save()` does for
  `os.replace`), point NiceGUI storage at a `tmp_path` excluded from indexing, or upstream a
  `missing_ok`/retry to NiceGUI's `Storage.clear()`.
