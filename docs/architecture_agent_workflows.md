# Agent Workflows

Phase 6 introduces multi-step agent workflows built on LangGraph. This doc is the authoritative
description of the workflow pattern and of the two concrete workflows: the scene-writing workflow
(`draft_scene`) and the intimacy review workflow. For the surrounding system see
[architecture.md](architecture.md); for the data these workflows read and write see
[story_bible_model.md](story_bible_model.md) and [forms_and_data_models.md](forms_and_data_models.md).

## The Workflow Pattern

A workflow is an enforced LangGraph workflow graph exposed to the main agent as a single tool.

- **Enforced sequence**: graph edges fix the step order. The main agent cannot skip or reorder
  steps; it calls one tool and the graph runs the whole pipeline. This is the reason workflows are
  LangGraph graphs rather than extra tools on the ReAct loop — we want to own the control flow.
- **Tool-enabled nodes**: an individual node may itself be a tool-enabled ReAct sub-loop. This
  lets a node (for example, drafting) pull extra Story Bible detail on demand while still being
  confined to its place in the enforced sequence. Nodes that fetch context use read-only tools.
- **Exposed as a tool**: the compiled graph is registered in a workflow registry in `app/graphs/`
  and wrapped as a tool the main agent can call. The main agent treats it as a black box that
  takes a brief and returns a result.
- **Per-node model config**: each node resolves its model through the per-node model-config
  override system (the same mechanism the chat node uses; see
  [model_configuration.md](model_configuration.md)). Cheap steps (outline, review) can use a
  smaller role while drafting uses a larger one.
- **Persistence**: workflows write through to the `World` incrementally — each completed piece is
  saved as its step finishes, using the existing per-tool-call `world_transaction()` on the store.
  This makes progress visible in the UI and leaves partial-but-usable results if a later step
  fails, rather than discarding the whole run. Run-scoped all-or-nothing semantics are possible
  (see the run-scoped checkpoint note in [architecture.md](architecture.md)) but are not used here:
  for a writing workflow, incremental visibility is preferable to atomicity.

## Scene-Writing Workflow (`draft_scene`)

Produces a full scene from a brief, generating the scene blueprint (premise, purpose, stances,
outline) and prose. Exposed to the main agent as the `draft_scene` tool.

### Inputs

The main agent passes a brief: premise, purpose, POV, participating characters, and any
constraints. The workflow targets an existing scene or creates a new one. The brief expresses
intent; the workflow owns craft.

### Nodes (enforced order)

1. **Formalize essential details** — turn the brief into the stored scene `premise` and `purpose`.
2. **Author initial stances** — write a `SceneCharacterStance` for each participating character
   (`mood` as a list of statements; `intent`, `tactics`, `stakes` as single fields).
3. **Outline** — produce the scene's beats as a list of short, concise statements.
4. **Review outline** — critique the outline against premise, purpose, and stances.
5. **Revise outline** — apply the critique. The review/revise loop is bounded by a configurable
   maximum (default 1) rather than looping until satisfied, to cap cost and latency.
6. **Draft prose** — write the scene Markdown. This node is tool-enabled (read-only bible/scene
   tools) so it can pull extra detail while drafting.
7. **Generate title and summary** — produce the scene `title` and `summary`.

### Outputs and storage

Each piece writes through to the `Scene` as its step completes: blueprint fields first, then prose,
then title and summary. The blueprint is shown only in edit mode in the scene editor (hidden in
preview); see [forms_and_data_models.md](forms_and_data_models.md). This phase does not stream the
draft token-by-token into the editor; the finished prose is written on step completion.

## Intimacy Review Workflow

Gates every agent-driven intimacy change behind a retrieval-and-review pipeline so new intimacies
stay well-formed and continuity-safe. This is the highest-leverage continuity guard: intimacy
edits are where a careless change silently corrupts a character.

### Why a workflow, not a subagent

The Story Bible is small, so retrieval is a direct lookup (the character's current intimacies at
the relevant timeline position plus relevant world facts) rather than a vector store, and review
is a single deterministic LLM step. A focused workflow graph is cheaper and more predictable than
a full subagent, and it composes with the existing per-call transaction.

### Description-based tool surface

The agent does not author intimacy effects directly. It describes the intended change in natural
language; the workflow produces the concrete structured effects. This flips the failure mode from
"I asked for X but the agent emitted effects Y" to "I asked for X, and here is the diff (Y) that
implements it."

- **Event signals** (mid-story changes): the agent supplies an interpretation plus a change
  description for the signal; the workflow fills in that signal's effects.
- **Baseline intimacies**: the agent describes the desired baseline; the workflow authors/edits
  the baseline intimacy list.
- The structured effect operations (`add_intimacy`, `set_intimacy_strength`, `update_intimacy`,
  `remove_intimacy`) remain the underlying data model and stay directly editable in the Story
  Bible forms. Only the agent's authoring path changes. World-state effects keep their direct CRUD
  authoring.

### Nodes (enforced order)

1. **Retrieve** — gather the character's current intimacies at the relevant timeline position plus
   relevant world facts, to ground the proposal and review.
2. **Propose** — convert the natural-language change description into specific structured effects.
3. **Review** — enforce simple first-person statements, merge duplicates, prefer strengthening an
   existing intimacy over adding a near-duplicate, and prefer small cumulative changes. Review may
   rewrite a proposed effect (for example, turn a duplicate `add_intimacy` into a
   `set_intimacy_strength` or drop it), so the applied effects can differ from the literal
   proposal.
4. **Apply** — write the reviewed effects to their target (a signal's effects or the baseline
   list) and return a human-readable diff.

### Approval

The workflow auto-applies reviewed changes and returns the diff. Human approval of the diff is
deferred to Phase 8 (tool confirmations), which layers a confirmation/diff step on top without
changing this workflow.

## Related Docs

- System architecture and orchestration overview: see [architecture.md](architecture.md).
- Story Bible data model (characters, intimacies, events, signals, effects): see [story_bible_model.md](story_bible_model.md).
- Scene model and the scene blueprint (premise, purpose, stances, outline): see [forms_and_data_models.md](forms_and_data_models.md).
- Per-node model selection used by workflow nodes: see [model_configuration.md](model_configuration.md).
- Phased plan (Phase 6a/6b/6c): see [implementation_plan.md](implementation_plan.md).
