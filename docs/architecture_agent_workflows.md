# Agent Workflows

Multi-step agent workflows are built on LangGraph. This doc is the authoritative description of the
workflow pattern and of the built workflows; currently that is the scene-writing workflow
(`draft_scene`). Planned-but-unbuilt workflows (such as the intimacy review workflow) are designed
in [future_work.md](future_work.md). For the surrounding system see
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
  smaller role while drafting uses a larger one. The resolved config's `system_prompt_prefix`
  is applied transparently on every LLM call via `PrefixedChatOpenAI` in `app/models/client.py`.
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
constraints. `draft_scene` always creates a new scene; revising an existing scene via a
workflow (`revise_scene`) is deferred. The brief expresses intent; the workflow owns craft.

`character_ids` are validated and normalized at the tool boundary before the workflow runs.
The agent sometimes emits a slightly-off id (for example `char_narrator` for the real
`char_the_narrator`), so `draft_scene` resolves each id against the Story Bible via
`StoryBible.resolve_character_id` (exact match, then a forgiving match on significant id tokens
that ignores dropped articles). Unresolvable ids raise a `ToolException` listing the valid
characters — mirroring the signal-tool validation — so the agent retries with correct ids rather
than seeding the scene with dangling stance references. The stance node applies the same
resolution against the scene's character set and drops any stance it cannot resolve, so a
persisted blueprint never references a character that does not exist.

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

The structured-output nodes (formalize, stances, outline, review, revise, title/summary) build
their model with `streaming=False`. They are one-shot `with_structured_output(...).invoke()` calls
that do not need token streaming, and streaming aggregation serializes the structured `parsed`
payload, which emits noisy Pydantic serializer warnings; the non-streaming path excludes that field.
The drafting node keeps the default streaming model.

## Planned Workflows

The intimacy review workflow is designed but not yet built. Its full design lives in
[future_work.md](future_work.md). Until it exists, agents author intimacy effects through the direct
structured operations described in [story_bible_model.md](story_bible_model.md).

## Related Docs

- System architecture and orchestration overview: see [architecture.md](architecture.md).
- Story Bible data model (characters, intimacies, events, signals, effects): see [story_bible_model.md](story_bible_model.md).
- Scene model and the scene blueprint (premise, purpose, stances, outline): see [forms_and_data_models.md](forms_and_data_models.md).
- Per-node model selection used by workflow nodes: see [model_configuration.md](model_configuration.md).
- Phased plan (completed core phases): see [implementation_plan.md](implementation_plan.md).
- Planned enhancements, including the intimacy review workflow: see [future_work.md](future_work.md).
