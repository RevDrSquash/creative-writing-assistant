# Agentic Development Setup

How this repository is prepared for autonomous AI-agent development, why each piece exists, and
how to repeat the setup on other projects. This is a process doc, not app architecture; for the
app itself see [architecture.md](architecture.md).

## The three-layer model

An autonomous coding agent needs three things a human teammate also needs, just made explicit:

1. **Context** -- what the project is, where things live, and what the standards are.
   Provided by `AGENTS.md`, `.cursor/rules/`, and the `docs/` folder.
2. **Capabilities** -- task-specific know-how loaded on demand, not burned into every prompt.
   Provided by `.cursor/skills/`.
3. **Verification** -- cheap, deterministic ways for the agent to prove a change works without
   a human watching. Provided by pytest (including in-process UI tests), Ruff, and pre-commit.

The layers feed each other: context tells the agent what "done" means, capabilities tell it how
to do specialized work, and verification closes the loop so it can iterate on its own mistakes
instead of shipping them.

## What exists in this repo and why

### Context layer

- **`AGENTS.md`** (repo root). The single entry point: project premise, module map with
  boundaries, every command, and the definition of done. It is a tool-agnostic convention
  (Cursor, Claude Code, Codex, and others all read it), which makes it the highest-leverage
  file to write. Keep it short; link to `docs/` for depth.
- **`.cursor/rules/`** -- always-applied guardrails, each narrow and behavioral:
  - `read-project-overview`: points the agent at `AGENTS.md` / `docs/overview.md`.
  - `docs-authoritative-architecture`: `/docs` is the source of truth; update docs before
    diverging code.
  - `run-tests-with-poetry`: prevents the recurring "bare `python -m pytest` fails" loop.
  Rules are for things that must hold on *every* task. Anything situational belongs in a
  skill instead, so it does not consume context on unrelated work.
- **`docs/`** -- authoritative architecture and plans. Two patterns worth copying:
  - `known_issues.md` records understood-but-unfixed problems with location, severity, and a
    possible fix, so context survives between sessions and phases.
  - `implementation_plan.md` tracks phases, so an agent can see what is built vs planned.

### Capability layer

- **`.cursor/skills/nicegui-ui-changes/`** -- loaded only when UI work happens. It contains:
  - `SKILL.md`: when to load, where the references are, and the mandatory verification step.
  - `reference.md`: *project-specific* conventions and the pitfalls that actually caused bugs
    here, plus a pointer to the version-matched general guide that ships inside the installed
    package (`.venv/Lib/site-packages/nicegui/llms.md`).

  Design notes worth reusing:
  - Prefer a local, checked-in or package-bundled reference over a per-session web fetch.
    Fetching `llms.txt` every session cost time and context and could drift from the installed
    version.
  - A skill beats a subagent here. Subagents give context *isolation*, which pays off for
    read-heavy work (exploration, review) where a large working context would pollute the main
    conversation. UI *editing* needs the conventions inside the editing agent's context anyway,
    so isolation buys nothing. The actual failure mode -- unverified UI changes -- is fixed by
    the verification layer, not by more agents.

### Verification layer

- **In-process UI tests** (`tests/test_ui_pages.py` + the `user` fixture in
  `tests/conftest.py`). NiceGUI ships a simulated-user harness (`nicegui.testing`) that boots
  the real app and drives pages without a browser or network. The conftest isolates the
  environment: persistence is redirected to a temp dir via the `WRITING_AGENT_DATA_DIR`
  environment variable, a fake OpenRouter key satisfies settings validation, and the model
  catalog is stubbed. This was the biggest gap: before it existed, an agent could change
  `app/ui/` and have no way to prove the page still rendered.
- **Definition of done** (in `AGENTS.md`): focused tests while iterating, then
  `poetry run ruff check . && poetry run pytest` before declaring complete. One command, no
  judgment calls.
- **Pre-commit hooks** (`.pre-commit-config.yaml`): Ruff lint + format on every commit, wired
  through `poetry run` so the hook uses the project's pinned Ruff. Installed with
  `poetry run pre-commit install`.
- **Branch + PR gate**: `master` is never committed to directly -- every change, including
  docs-only ones, lands through a pull request from a feature branch (see "Git workflow" in
  `AGENTS.md`). This keeps agent-made changes reviewable before they become the baseline other
  agents build on.
- **CI** (future): once the repo has a remote, a workflow running the same verify chain makes
  the gate independent of any one machine (tracked in [future_work.md](future_work.md)).

### Cloud execution environment (Cursor Cloud Agents)

Cloud agents run on Cursor's default Ubuntu VM with internet access; there is no custom
Dockerfile because the project needs nothing beyond Python 3.10+ and Poetry, and the test suite
runs fully offline (see the verification layer above). The setup is:

- **`.cursor/environment.json`** (committed, authoritative) defines the `install` command:
  ensure Poetry is on `PATH` (installing via pipx if missing), then `poetry install`. Cursor
  runs it when building the environment and snapshots the result, so subsequent agents boot
  fast. Keeping this file in the repo makes the environment reproducible and reviewable rather
  than living only in dashboard state.
- **`OPENROUTER_API_KEY`** is a Cloud Agents runtime secret (encrypted, injected as an env
  var). `ModelSettings` reads env vars directly, so no `.env` file exists in Cloud. Tests and
  lint never need it; only running the app with live AI calls does. Use a dedicated key so it
  can be revoked and its spend tracked independently of local development.
- **Operational notes for agents** (Poetry location, headless-browser log noise, port 8080)
  live in the "Cursor Cloud specific instructions" section of `AGENTS.md`, where every agent
  reads them.

To re-verify the environment end-to-end, launch a cloud agent with a smoke task such as "run
`poetry run ruff check . && poetry run pytest` and report the results; change nothing" and
confirm the environment build succeeds and the suite passes.

## When to reach for which mechanism

| Mechanism | Use when | Avoid when |
| --- | --- | --- |
| `AGENTS.md` | Facts every task needs: map, commands, definition of done | Long reference material (link to docs instead) |
| Rule (always-applied) | A behavior must hold on every task (test runner, doc authority) | Situational knowledge -- it taxes every prompt |
| Skill | Specialized know-how for a recognizable task type (UI work, a deploy flow) | Knowledge needed on every task (promote to AGENTS.md/rule) |
| Subagent | Read-heavy work whose working context would pollute the main thread (codebase exploration, large-doc research, review passes) | Editing tasks -- the editor needs the knowledge in its own context |
| Tests/lint as agent tools | Always; this is the layer that makes autonomy safe | -- |
| Pre-commit / CI | Mechanical gates that should not depend on agent discipline | Slow checks on commit (full test suite belongs in CI / definition of done) |

## Porting checklist for a new project

1. Write `AGENTS.md`: one-paragraph premise, module map with boundaries, exact commands (run,
   test, lint, format), and an explicit definition of done. Do this first; everything else
   hangs off it.
2. Make verification one command (`lint && test`). If the project cannot verify itself, fix
   that before adding any AI tooling -- agents amplify whatever feedback loop exists, including
   a missing one.
3. Close the biggest "unverifiable change" gap. Here it was UI rendering; find your framework's
   in-process test harness (most have one) and add smoke tests plus the shared fixtures that
   make new tests cheap to write. Isolate tests from real user data and the network.
4. Add 2-4 narrow always-on rules for failure modes you have actually hit (wrong test runner,
   ignoring docs). Write them after the second occurrence, not preemptively.
5. Create a skill per specialized task type, containing: project conventions, known pitfalls
   (with the bug each one caused), and the mandatory verification command. Prefer local
   references over web fetches.
6. Keep a `known_issues.md` so understood-but-deferred problems survive context loss.
7. Add pre-commit for fast mechanical gates; add CI with the same verify chain once a remote
   exists.
8. Feed the loop: when an agent makes the same mistake twice, encode the correction as a rule
   (if universal) or into a skill (if situational), and where possible add a test that catches
   it mechanically. Prefer the test -- guidance can be ignored; a red test cannot.
