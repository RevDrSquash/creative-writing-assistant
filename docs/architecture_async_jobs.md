# Async Jobs

Background work in the writing workspace (scene generation and chat turns) runs as tracked **jobs** with **resource claims**. The UI and agent tools enforce claims at their boundaries so concurrent edits do not collide with in-flight generation or chat.

## JobManager

`app/graphs/jobs.py` exposes a process-wide singleton (`get_job_manager()`). Jobs are in-memory only; on restart there are no running jobs.

Each **Job** record includes:

| Field | Purpose |
| --- | --- |
| `id` | UUID |
| `kind` | `"scene_generation"` or `"chat_turn"` |
| `label` | Human-readable name for toasts and debugging |
| `claims` | Resource keys this job owns while running |
| `status` | `running`, `finished`, or `failed` |
| `created_at` / `finished_at` | Timestamps |
| `error` | Failure message when `status == failed` |
| `cancel_requested` | Reserved for future cancellation |
| `live` | Kind-specific streaming payload with a monotonic `version` |

## Resource claims

Claims are plain string keys:

- `scene:{scene_id}` — scene generation holds the scene being generated.
- `chat` — an in-flight chat agent turn.

`JobManager.claim_for(resource)` returns the running job that holds a claim, or `None`.

**Enforcement boundaries** (never inside `world_transaction()` — the owning job's own writes pass through freely):

1. **Tool boundary** — scene-mutating tools in `app/tools/scene.py` call `_reject_if_scene_claimed()` and raise `ToolException` when the target scene is claimed.
2. **UI boundary** — the scene editor disables the edit toggle and forces view mode while its scene is claimed; chat send is disabled while a `chat` claim exists.

Generation writes go through `app/world/scene.py` helpers, not tools, so they are unaffected by claim checks.

## Execution model

The manager tracks and claims; it is not a scheduler or queue.

- **Scene generation** — same as before: a daemon thread runs `run_scene_generation()` synchronously via `workflow.invoke`.
- **Chat turns** — `start_chat_turn()` creates an `asyncio.create_task` owned by the manager. The task streams from `get_chat_agent().astream()`, accumulates assistant text in the job's `ChatLive` buffer, applies scene text side effects, and persists the assistant message on completion.

Jobs on different resources run in parallel. A conflicting start (same scene or second chat while one runs) is rejected with `RuntimeError`, matching the previous generation manager behavior.

## UI integration

Updates use the established poll-based pattern (`ui.timer` + `@ui.refreshable`), not an event bus.

| Surface | Location | Behavior |
| --- | --- | --- |
| Scene list spinner | `app/ui/pages/workspace.py` sidebar | Shown while `scene:{id}` is claimed |
| Edit lock | Scene editor | Generate forces view mode; edit toggle disabled while claimed |
| Chat live buffer | `app/ui/components/chat.py` | Renders streaming assistant text from `ChatLive`; re-attaches on page mount |
| Chat send lock | Chat panel | Send disabled while `chat` claim exists |
| Header indicator | `app/ui/layout.py` | Running job count + spinner |
| Completion toasts | `app/ui/layout.py` | Per-client `ui.timer` polls finished jobs; each toast fires once per browser tab via `app.storage.user["notified_job_ids"]` |

Toast copy: `"{label} generated"`, `"Scene generation failed: …"`, `"Agent reply ready"`.

## Persistence hardening

`app/persistence/world.py` `JsonFileWorldStore.save()` retries `os.replace` on `PermissionError` (5 attempts, exponential backoff). UI save handlers use `save_world_ui()` in `app/ui/save_helpers.py`, which notifies `"Save failed — retry by editing again"` when retries exhaust.

## Deferred

See [future_work.md](future_work.md):

- Job cancellation via `cancel_requested`
- Jobs page listing all jobs with status/cancel
- Wait-queue for conflicting starts instead of rejection

## Related docs

- [architecture.md](architecture.md) — system overview
- [architecture_agent_workflows.md](architecture_agent_workflows.md) — scene generation workflow
- [known_issues.md](known_issues.md) — UI save transaction gap (#3)
