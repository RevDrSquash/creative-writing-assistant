---
name: nicegui-ui-changes
description: Project conventions, pitfalls, and required verification for NiceGUI work. Use whenever editing, creating, refactoring, or reviewing any file under app/ui/ in this project.
---

# NiceGUI UI Changes

Before making ANY change to files under `app/ui/`:

1. Read `reference.md` in this skill folder. It contains this project's UI conventions,
   the pitfalls that have actually caused bugs here, and the required verification steps.
2. If you need general NiceGUI API details beyond that, read the guide bundled with the
   installed package: `.venv/Lib/site-packages/nicegui/llms.md`. It is version-matched to the
   `nicegui` release this project actually runs, so prefer it over web docs. Only fetch
   `https://nicegui.io/llms.txt` if the local file is missing.

After making UI changes, you MUST verify them before declaring the work done:

```bash
poetry run pytest tests/test_ui_pages.py
```

Add or update a page test in `tests/test_ui_pages.py` when you add a page or meaningfully
change what one renders. Finish with the full verify chain:
`poetry run ruff check . && poetry run pytest`.
