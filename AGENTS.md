# AGENTS.md

Local-first AI writing workspace for long-form fiction and worldbuilding. NiceGUI provides a
three-column UI (navigation, markdown scene editor, AI chat); LangGraph runs the agent loop; the
agent reads and edits project content exclusively through tools. This is also a learning project:
for anything touching the agent loop, tools, or orchestration, prefer the LangGraph/agentic
approach over shortcuts (see `docs/overview.md` "Goal Priority").

Start here for deeper context:

- `docs/overview.md` - premise, goals, and goal priority.
- `docs/architecture.md` - authoritative architecture. `/docs` is the source of truth; if your
  change diverges from it, update the doc first, then the code.
- `docs/implementation_plan.md` - phased plan and current progress.
- `docs/known_issues.md` - known limitations and architectural debt, with context for fixes.
- `docs/agentic_development.md` - how this repo's agent tooling (rules, skills, tests, hooks)
  fits together and why.

## Module map

| Path | Responsibility | Boundary notes |
| --- | --- | --- |
| `app/ui/` | NiceGUI layout, pages, components | Keep thin: no core logic in event handlers |
| `app/graphs/` | LangGraph agent, state, middleware, context assembly | All AI behavior runs through here |
| `app/tools/` | LangChain tools for reading/editing world content | The only way the agent mutates content |
| `app/world/` | World models, story bible replay, in-memory world state | Source of truth for story content |
| `app/persistence/` | Local JSON stores (world, chat, model configs, LLM logs) + world ZIP | No secrets in exported data |
| `app/models/` | Model configs, OpenRouter client, debug logging | API key comes from `.env` |
| `tests/` | Pytest suite; shared fixtures in `tests/conftest.py` | UI tests use the NiceGUI `user` fixture |

## Commands

All commands run through Poetry from the repo root (the system Python does not have project deps):

| Task | Command |
| --- | --- |
| Run the app | `poetry run writing-agent` |
| Full test suite | `poetry run pytest` |
| Focused tests | `poetry run pytest tests/test_scene_tools.py` |
| Lint | `poetry run ruff check .` |
| Format | `poetry run ruff format .` |
| Verify (definition of done) | `poetry run ruff check . && poetry run pytest` |

## Definition of done

Before declaring any task complete:

1. Run focused tests for the area you changed while iterating.
2. Run the full verify chain: `poetry run ruff check . && poetry run pytest`.
3. New behavior gets new tests. UI pages and components are testable in-process via the NiceGUI
   `user` fixture (see `tests/test_ui_pages.py`); there is no excuse for unverified UI changes.
   Agent tools additionally need tests that exercise hallucinated or malformed inputs (e.g. an
   unknown or drifted id), asserting the tool rejects or normalizes them instead of persisting bad
   data.
4. If behavior or architecture changed, update the relevant doc in `docs/`. If you discovered a
   limitation you are not fixing, record it in `docs/known_issues.md` (severity, location,
   symptom, possible fix - follow the existing format).

## Conventions

- Python 3.10+, line length 100, Ruff for lint and format (config in `pyproject.toml`).
- Pydantic v2 models for structured data.
- Agent tools must validate every parameter with strict requirements (ids, references, enums, etc.)
  against the world before acting. The model can hallucinate values, so resolve or reject them up
  front (raise `ToolException` with the valid options) rather than writing dangling references. See
  `_resolve_scene_character_ids` in `app/tools/scene.py` for the pattern.
- Persistence is plain JSON files under `data/`; tests must use `tmp_path`, never `data/`.
- Before editing anything under `app/ui/`, follow the `nicegui-ui-changes` skill
  (`.cursor/skills/nicegui-ui-changes/`).
