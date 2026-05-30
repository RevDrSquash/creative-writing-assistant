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

## 2. Unterminated-canvas rollback discards mid-run tool edits

- **Severity:** Low (edge-case correctness)
- **Location:** `app/ui/components/chat.py` — `_apply_canvas_flush_events` and the
  `send_message` streaming loop
- **Introduced:** Phase 3
- **Symptom:** Rollback resets the scene to `pre_stream_scene`, which is captured before the
  entire agent run. If the model commits a `replace_scene_text` edit and then emits an
  unterminated `<canvas>` block in the same turn (for example, cut off by a token limit), the
  committed edit is wiped from the UI even though the backend graph state still retains it.
- **Why it usually doesn't bite:** It requires a successful tool edit followed by a truncated
  canvas block within one turn.
- **Possible fix:** Track the last committed scene (the most recent `updates` value) and roll
  back to that instead of the run's starting snapshot.

## 3. Scene state couples the world layer to NiceGUI

- **Severity:** Low (architectural debt, not a bug)
- **Location:** `app/world/scene.py` — `get_current_scene_text` / `set_current_scene_text`
- **Introduced:** Phase 3
- **Symptom:** These helpers read and write `nicegui.app.storage.user` directly, so the
  `app/world/` layer depends on the UI framework. This is in tension with the
  `docs/architecture.md` boundary that core logic should live outside NiceGUI and that world
  state should be a single `World` object.
- **Why it is acceptable for now:** There is no `World` object yet (planned for Phase 5), and
  `docs/overview.md` permits the simpler implementation for supporting code that serves the
  agent layer.
- **Possible fix:** When the structured `World` model lands in Phase 5, move scene text into it
  and have the UI bind to that object instead of `app.storage.user`.
