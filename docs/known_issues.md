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
  intra-process save races (the only observed failure cause); external file locks are rare and
  the next keystroke resaves the full world anyway.
- **Possible fix:** Route UI edits through id-based accessors instead of direct object bindings
  so they can use `world_transaction()` too, or add a save-failure notification that prompts a
  manual resave.

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
  `add_character`, `add_intimacy`, `insert_event`
- **Introduced:** Schema version 2 (readable slug ids)
- **Symptom:** Entities created from the UI before the user types a name or title receive
  generic slugs (`char`, `char_2`, `event`, etc.) rather than descriptive ones. Agent-created
  entities slug from the supplied text at creation time and are usually more readable.
- **Why it is acceptable:** The slug is frozen at creation; the user can delete and recreate if
  they care, and the display name is independent of the id.
- **Possible fix:** Re-slug on first non-blank save of the primary text field, or prompt for a
  name before creating the entity.

## 6. World schema version 1 is rejected; no automatic migration

- **Severity:** Low (documented breaking change)
- **Location:** `app/persistence/world.py` — `validate_world_payload`; `app/world/models.py`
  — `SCHEMA_VERSION = 2`
- **Introduced:** Schema version 2 (readable slug ids)
- **Symptom:** Loading a `world.json` (or ZIP import) with `schema_version: 1` fails with a
  clear unsupported-version error. Existing v1 worlds must be hand-converted (re-slug entity
  ids and repair signal `character_id` references) before the app will load them.
- **Why it is acceptable:** Automatic migration would need to rewrite every cross-reference;
  the project has a single dev world and migration tooling is deferred.
- **Possible fix:** Add a one-shot migration script or import-time rewriter that maps old hex
  ids to new slugs and updates all references.

## 7. Scene workflow has no cross-scene context, so adjacent scenes drift

- **Severity:** Medium (correctness of generated content)
- **Location:** `app/graphs/scene_workflow.py`, `app/graphs/context.py`, `app/tools/scene.py`
  — `draft_scene`
- **Introduced:** Phase 3 (scene workflow)
- **Symptom:** The scene-writing workflow only sees the brief (premise, purpose, POV,
  characters, constraints) for the scene it is generating. It receives no context from
  surrounding scenes, so two scenes that take place close together (e.g. two parts of the same
  conversation) can drift on shared details like location, time of day, who is present, and
  ongoing action.
- **Why it usually doesn't bite:** Scenes far apart in the story rarely share fine-grained
  state, so the gaps are only obvious when scenes are tightly coupled.
- **Possible fix:** Simple first iteration — always pass the previous scene as context to the
  workflow. A fuller fix depends on the scene/event linking and event-relationship work tracked
  in `docs/future_work.md` (scenes linked to events, events related by causality), which would
  let the workflow select genuinely relevant neighboring scenes rather than always the previous
  one.
