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

## 3. Unterminated-canvas rollback can miss appends after a mid-run scene switch

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
