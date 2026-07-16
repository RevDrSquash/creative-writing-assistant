# Agent Workflows

Multi-step agent workflows are built on LangGraph. This doc is the authoritative description of the
workflow pattern and of the built workflows; currently that is the scene-writing workflow
(`generate_scene`). Planned-but-unbuilt workflows (such as the intimacy review workflow) are designed
in [future_work.md](future_work.md). For the surrounding system see
[architecture.md](architecture.md); for the data these workflows read and write see
[story_bible_model.md](story_bible_model.md) and [forms_and_data_models.md](forms_and_data_models.md).

## The Workflow Pattern

A workflow is an enforced LangGraph workflow graph exposed as a single entry point (not as a main-agent tool).

- **Enforced sequence**: graph edges fix the step order. The main agent cannot skip or reorder
  steps; user-triggered generation runs the whole pipeline. This is the reason workflows are
  LangGraph graphs rather than extra tools on the ReAct loop — we want to own the control flow.
- **Tool-enabled nodes**: an individual node may itself be a tool-enabled ReAct sub-loop. This
  lets a node (for example, drafting) pull extra Story Bible detail on demand while still being
  confined to its place in the enforced sequence. Nodes that fetch context use read-only tools.
- **User-triggered**: the compiled graph is registered in a workflow registry in `app/graphs/`
  and invoked by `run_scene_generation()` from the scene editor (via the background generation
  manager). The main agent authors scene blueprints but does not run this workflow.
- **Per-node model config**: each node resolves its model through the per-node model-config
  override system (the same mechanism the chat node uses; see
  [model_configuration.md](model_configuration.md)). Cheap steps (outline, review) can use a
  smaller role while drafting uses a larger one. The resolved config's `system_prompt_prefix`
  is applied transparently on every LLM call via `PrefixedChatOpenAI` in `app/models/client.py`.
- **Persistence**: workflows write through to the `World` incrementally — each completed piece is
  saved as its step finishes, using the existing per-tool-call `world_transaction()` on the store.
  This makes progress visible in the UI and leaves partial-but-usable results if a later step
  fails, rather than discarding the whole run. Run-scoped all-or-nothing semantics are possible
  (see the run-scoped checkpoint note in [architecture.md](architecture.md)) but are not used here:
  for a writing workflow, incremental visibility is preferable to atomicity.

## Scene-Writing Workflow (`generate_scene`)

Produces stances, outline, prose, and a summary from an existing scene blueprint. The user
triggers it from the scene editor; it runs in a background thread so chat and UI stay responsive.
The scene title is an input, not an output: it is set when the scene is proposed (`propose_scene`
requires one) or edited by the user/agent, so proposed scenes are identifiable in the UI before
any prose exists.

### Inputs

The workflow reads the scene's **blueprint** (the editable scene card): premise, purpose, POV,
participating characters, arc beats, enacted and related events, constraints, and notes. The
blueprint is authored by the main agent (`propose_scene`, `update_scene_blueprint`) or edited
manually in the scene editor. The workflow never writes blueprint fields.

`run_scene_generation(scene_id)` validates that the blueprint is generatable (non-empty premise,
at least one enacted event), snapshots a fingerprint of the blueprint, clears prior generated
content and prose, assembles **continuity context** from neighboring scenes (see below), invokes
the graph, then stamps `generated_at` and the fingerprint on `Scene.generated`.

### Continuity context

Before invoking the graph, `run_scene_generation()` builds a formatted continuity block via
`app/world/scene_context.py` and passes it as `continuity_context` on the workflow state.
Selection rules:

- **Previous scene** — the scene ranked immediately before the target by enacted-event
  chronology (`chronological_order()` on blueprint `event_ids`). When scenes have no resolvable
  enacted events, `World.scenes` list order is the fallback.
- **Next scene** — the scene ranked immediately after the target (summary only).
- **Related scenes** — scenes enacting events linked to the target's enacted events by
  `directly_follows` or `during`, plus scenes enacting blueprint `related_event_ids`. Deduped
  against previous/next (a neighbor appears in only one role).

Context depth: **full prose** for the previous scene (with a defensive character cap), **title and
summary only** for next and related scenes. When a neighbor has no prose or summary yet, its
**blueprint** (premise, purpose, POV, arc, characters, constraints, notes) is included instead,
clearly labeled as planned content rather than written prose. The draft node may call `read_scene`
for full prose of related scenes when summaries are not enough.

The continuity block and explicit continuity instructions are injected into the **stances**,
**outline**, **review plan**, **draft prose**, **review prose**, and **revise** prompts. The
plan-review node critiques stances and outline for continuity breaks against this context; the
prose-review node does the same for drafted prose. The **summarize** node does not receive it.

### Staleness

`Scene.generated.blueprint_fingerprint` records the blueprint at generation time. If the blueprint
changes afterward (agent or user edit), `scene_is_stale()` is true: the editor shows a **Stale**
badge and enables **Regenerate** (with a confirm dialog that warns existing prose/outline/stances
will be discarded).

### Nodes (enforced order)

1. **Author initial stances** — write a `SceneCharacterStance` for each participating character
   (`mood` as a list of statements; `intent`, `tactics`, `stakes` as single fields). Writes to
   `Scene.generated.stances`.
2. **Outline** — produce the scene's beats as a list of short, concise statements. Writes to
   `Scene.generated.outline`.
3. **Review plan** — critique the stances **and** outline against premise, purpose, and
   continuity with surrounding scenes. Structured critique only; nothing is mutated.
4. **Revise plan** — a tool-enabled ReAct sub-loop that applies targeted edits via
   `edit_outline` (batched text-anchored ops) and `update_stance` (field-level updates). The
   agent works on injected outline/stances state; the node persists the result through
   `update_scene_generated`. The review/revise loop is bounded by a configurable maximum
   (default 1) rather than looping until satisfied, to cap cost and latency.
5. **Draft prose** — write the scene Markdown. This node is tool-enabled (read-only bible/scene
   tools) so it can pull extra detail while drafting.
6. **Review prose** — critique the drafted prose against premise, purpose, stances, outline,
   and continuity. Structured critique only.
7. **Revise prose** — a tool-enabled ReAct sub-loop that applies targeted search/replace edits
   via `edit_prose`. The agent works on `current_scene`; the node persists through
   `set_scene_text`. Bounded by the same `max_revisions` counter (tracked separately as
   `prose_revision_count`).
8. **Summarize** — produce the one-line scene `summary` from the (possibly revised) prose. The
   title is never touched.

The former **Formalize essential details** node was removed: the blueprint *is* the input; the
workflow does not rewrite premise or purpose.

### Edit-tool semantics

Workflow revise nodes use batched, text-anchored edit tools rather than regenerating whole
artifacts (which invites drift on untouched material):

- **`edit_outline`** — one tool call carries a list of ops (`replace`, `add_after`, `add_first`,
  `delete`). Each op matches a beat by a unique case-insensitive substring fragment; zero or
  multiple matches fail that op. Ops apply in order; the tool returns a per-op success/error
  report so the agent can fix failures in a follow-up call.
- **`update_stance`** — updates provided fields on one character's existing stance.
  `character_id` is resolved against scene participants (hallucinated ids are rejected).
- **`edit_prose`** — one tool call carries a list of `{match, replacement}` ops with the same
  unique-match and partial-application semantics. Empty replacement deletes; insert by
  replacing an anchor with the anchor plus new text.

These tools mutate the revise agent's injected state, not the world. The enclosing workflow
node writes through after the agent finishes.

Models may emit several tool calls in one turn, and LangGraph executes them in parallel within a
single step — so every state key these tools write must carry a reducer, or the run dies with
`INVALID_CONCURRENT_GRAPH_UPDATE`. The agent state schemas (`app/graphs/state.py`) handle this:

- **`stances`** uses a per-character merge reducer. `update_stance` returns only the stance it
  changed (never the full list), so parallel updates to different characters combine losslessly.
- **`outline`** and **`current_scene`** use a last-write-wins reducer. Batching is built into
  `edit_outline`/`edit_prose` and the prompts instruct one batched call, so concurrent full
  rewrites are an edge case; if a model still issues two calls in one turn, the later one wins
  and the per-op tool reports let the agent notice and re-apply.

### Outputs and storage

Stances and outline write to `Scene.generated` as their steps complete; prose writes to
`Scene.markdown`; the summary writes to the scene metadata field. The blueprint remains
user/agent-editable inputs only. Generated outline and stances appear in a **Generated** expansion
in the scene editor (still user-editable, but regenerate overwrites them). See
[forms_and_data_models.md](forms_and_data_models.md).

The structured-output nodes (stances, outline, plan review, prose review, summary) build their
model with `streaming=False`. They are one-shot `with_structured_output(...).invoke()` calls that
do not need token streaming, and streaming aggregation serializes the structured `parsed` payload,
which emits noisy Pydantic serializer warnings; the non-streaming path excludes that field.
The drafting and revise nodes keep the default streaming model; drafting still uses canvas tags
internally.

### Background execution

`app/graphs/jobs.py` (`JobManager`) exposes `start_scene_generation(scene_id)`,
`is_generating(scene_id)`, and `last_error(scene_id)`. A second concurrent run for the same scene
is rejected. Chat turns use `start_chat_turn()` with a `chat` resource claim. The scene editor and
chat panel poll job state with `ui.timer` and the refreshable pattern. See
[architecture_async_jobs.md](architecture_async_jobs.md) for claims, enforcement, and notifications.

## Planned Workflows

The intimacy review workflow is designed but not yet built. Its full design lives in
[future_work.md](future_work.md). Until it exists, agents author intimacy effects through the direct
structured operations described in [story_bible_model.md](story_bible_model.md).

## Related Docs

- System architecture and orchestration overview: see [architecture.md](architecture.md).
- Story Bible data model (characters, intimacies, events, signals, effects): see [story_bible_model.md](story_bible_model.md).
- Scene model, blueprint vs generated split, and scene editor UI: see [forms_and_data_models.md](forms_and_data_models.md).
- Per-node model selection used by workflow nodes: see [model_configuration.md](model_configuration.md).
- Phased plan (completed core phases): see [implementation_plan.md](implementation_plan.md).
- Planned enhancements, including scene review and copy-before-regenerate: see [future_work.md](future_work.md).
