# NiceGUI in This Project: Conventions and Pitfalls

Project-specific reference for working under `app/ui/`. For the general NiceGUI guide (mental
models, full API, anti-patterns), read the version-matched copy bundled with the installed
package: `.venv/Lib/site-packages/nicegui/llms.md`.

## How the UI is organized

- `app/ui/app.py` is the entry point. It imports `app.ui.pages`, which registers every
  `@ui.page` route as an import side effect, then calls `ui.run(...)`.
- New page module? It MUST be imported in `app/ui/pages/__init__.py` or its routes will
  silently not exist.
- `@ui.page` functions are thin wrappers that delegate to private renderers
  (e.g. `workspace()` calls `_workspace_page(...)`). Keep logic in the renderer or, better, in
  non-UI modules -- the architecture boundary is "UI stays thin; core logic lives outside
  NiceGUI event handlers".
- Shared chrome lives in `app/ui/layout.py` (`render_header`, `render_sidebar`,
  `render_page_shell`) with nav metadata in `app/ui/navigation.py`. Reuse these; do not
  hand-roll headers or drawers per page. The workspace builds its own grouped sidebar in
  `pages/workspace.py` because its scene list is dynamic.
- Reusable widgets live in `app/ui/components/` as `render_*` functions that build elements in
  the caller's current slot.

## Project conventions that override the generic guide

- Double quotes, not single quotes. The bundled NiceGUI guide recommends single-quoted strings;
  this project formats with `ruff format`, which enforces double quotes. Ruff wins.
- No backslash-continuation fluent chains. Chain inline or assign intermediates;
  `ruff format` rewrites continuation styles anyway.
- Styling uses Tailwind utility classes via `.classes(...)` plus Quasar `.props(...)`.
  Existing palette leans on Quasar greys (`bg-grey-1`, `text-grey-7`) and `color=primary`.

## Per-user state

- Per-user values go through `nicegui.app.storage.user` and require the `storage_secret`
  already passed in `app.py`. Existing keys: the selected scene (`CURRENT_SCENE_KEY` in
  `app/ui/scene_selection.py`) and the workspace splitter position (`workspace_split`).
- Story content is NOT per-user: it lives on the process-wide `World` object
  (`app/world/store.py`). Forms bind directly to world model objects and call `save_world()`
  on change (see `components/story_bible_forms.py`).
- Prefer `element.bind_value(target, field)` over manual get/set handlers (see the
  splitter in `pages/workspace.py` and `components/markdown_editor.py`).
- Never store per-user data in module-level variables; NiceGUI is one process shared by all
  sessions.

## Known pitfalls (each of these caused a real bug here)

- `ui.markdown` auto-dedent: the first non-empty line's indentation is treated as the dedent
  amount for every line. A stray leading space (common at the start of an LLM stream) silently
  chews the first character off every subsequent line. Strip leading whitespace before
  rendering or persisting (see `chat.py::_append_streamed_chat_text` and
  `chat_conversation.py::_append`).
- Full-height layouts: the default page content has `1em` padding and gaps. The workspace
  removes it with `ui.query(".nicegui-content").classes("p-0 gap-0 no-wrap")` plus an explicit
  `height: calc(100vh - 80px)`. Columns that must scroll internally need `min-h-0` (and usually
  `overflow-hidden` on the parent) or flexbox lets them overflow the viewport.
- Async event handlers must not block the event loop: no `time.sleep`, no sync HTTP. The chat
  send handler streams via `async for ... astream(...)`; follow that pattern.
- Long-running page builders: `@ui.page` has a 3s response timeout. Do slow work after render
  (background task or timer), not inside the builder.
- `ui.timer` + `@ui.refreshable` is the established pattern for self-updating sections (see the
  debug page sidebar).
- Dialogs opened from inside a timer-refreshed `@ui.refreshable` get deleted when the section
  refreshes: elements built in an event handler land in the handler element's container, so the
  next `refresh()` wipes the open dialog (the Regenerate confirmation closed by itself this way).
  Build the dialog once outside the refreshable and `await dialog` from the handler (see
  `_render_generation_controls` in `pages/workspace.py`).

## Verification (required)

UI changes are verifiable in-process; never declare a UI change done without running:

```bash
poetry run pytest tests/test_ui_pages.py
```

- Tests use the simulated `user` fixture from `tests/conftest.py`: it boots the real app with
  persistence redirected to a temp dir (`WRITING_AGENT_DATA_DIR`) and a fake OpenRouter key.
  No browser, no network.
- Adding a page or significantly changing one? Add or update a test in
  `tests/test_ui_pages.py` (`await user.open(path)` + `await user.should_see(...)`).
- Pages that render the model-config form hit the OpenRouter catalog; use the
  `stub_model_catalog` fixture so tests stay offline.
- Then run the full verify chain before finishing: `poetry run ruff check . && poetry run pytest`.
