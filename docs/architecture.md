# Architecture Overview

The app is a local-first Python writing workspace built around one in-memory `World` object. NiceGUI handles the interface, LangGraph handles AI orchestration, and tools are the only way the AI reads or changes project content.

## Tech Stack

- **Language:** Python
- **Dependency management:** Poetry
- **UI:** NiceGUI
- **AI orchestration:** LangGraph
- **Agent pattern:** default ReAct-style graph loop
- **LLM access:** OpenRouter-compatible model profiles, likely through LangChain/LiteLLM
- **Data modeling:** Pydantic
- **Content format:** Markdown scenes plus structured Story Bible data
- **Storage:** local JSON, world ZIP import/export, and readable story HTML ZIP export

## Module Structure

- `app/ui/` - NiceGUI layout, navigation, editor/forms, chat, model config.
- `app/graphs/` - LangGraph workflows, graph builders, workflow registry, run state.
- `app/tools/` - Agent tools for reading, searching, creating, and editing world content.
- `app/world/` - Pydantic world models, validation, and in-memory world state.
- `app/persistence/` - Local save/load, world ZIP import/export, and readable story HTML ZIP export.
- `app/models/` - Model profiles, resolved model bundles, and LLM client setup.

## Major Components

- **NiceGUI UI**
  - Three-column workspace: navigation, content editor/forms, AI chat.
  - The workspace defaults to the Narrative Style Story Bible page; the scene editor opens only at `/workspace/scenes/{id}`.
  - Worlds may have zero scenes; create one explicitly via the sidebar or agent tools.
  - Shows markdown scenes, Story Bible forms, streamed assistant output, and tool-call results.

- **World State**
  - A single in-memory `World` object is the source of truth.
  - Contains metadata, scenes, Story Bible data, and chat history.
  - User edits and AI tool calls both update this same object.
  - All writes to `world.json` are serialized behind a process-wide lock in `app/world/store.py`.
    The lock alone only prevents overlapping saves from colliding (on Windows two overlapping
    atomic saves collide on the file lock); it does not fix ordering. The tool node runs a single
    AI message's batched tool calls concurrently (`asyncio.gather` async, a thread pool sync), so
    order-sensitive mutations (``add_event`` with inline ``relations`` referencing
    siblings created earlier in the batch) could run against a partial timeline or
    fail validation out of emission order. ``SerializeToolCallsMiddleware``
    (`app/graphs/serialize_tools_middleware.py`) gates each call on its index within the emitting
    message and runs the batch one at a time, in emission order, on both execution paths.
  - Programmatic write paths (agent tools, scene helpers) mutate and save inside
    `world_transaction()`: the lock is held across the whole mutate+save, and the in-memory
    mutation is rolled back if the save fails, so memory and disk never diverge. Without this, a
    failed save left a phantom mutation in memory that the model's retry then duplicated.
  - The transaction is per tool call. If a future workflow needs all-or-nothing semantics across
    many edits (e.g. a subagent run), build that as a run-scoped checkpoint/commit on the store;
    it composes with the per-call transactions and does not require copy-on-write of the
    singleton, which would break the UI's direct object bindings.
  - UI form edits mutate bound objects directly and then call `save_world()`; they get the save
    lock but not rollback (see known issues).

- **LangGraph Orchestration**
  - All AI behavior runs through LangGraph.
  - Background scene generation, intimacy interpretation, and chat turns are tracked by
    `JobManager`
    (`app/graphs/jobs.py`) with resource claims; see
    [architecture_async_jobs.md](architecture_async_jobs.md).
  - The default workflow is a single ReAct loop for free-form chat.
  - Named multi-step workflows compose several nodes for tasks like outlining, critiquing,
    revising, and drafting. Each is an enforced LangGraph workflow graph (graph edges fix the
    step order), and individual nodes may themselves be tool-enabled ReAct sub-loops. Workflows
    are user- or system-triggered entry points, not main-agent tools (see
    [architecture_agent_workflows.md](architecture_agent_workflows.md)). A workflow registry in
    `app/graphs/` builds and looks up these named workflows.
  - Two such workflows are built: the scene-writing workflow (`generate_scene`) and the
    evidence-based intimacy interpretation workflow (`interpret_intimacy`), which is
    triggered per relevant character through `JobManager`. Both are described
    in [architecture_agent_workflows.md](architecture_agent_workflows.md).
  - Workflow nodes resolve their model the same way the chat node does — through the per-node
    model-config override system — so cheaper roles can drive cheap steps while drafting uses a
    larger model.

- **Tool Layer**
  - Tools expose explicit actions such as reading scenes, updating scene metadata, listing world data, appending prose, replacing text, and updating Story Bible fields.
  - Write tools mutate world state before returning.
  - Tools raise `ToolException` for expected domain errors (e.g. an unknown entity id). The agent is built with a `ToolRetryMiddleware(max_retries=0, on_failure="continue")` so a failing tool call produces an error `ToolMessage` for the model to recover from instead of aborting the run. Tools are local and deterministic, so retries are disabled.
  - Workflows or subagents can also be exposed as tools.
  - Intimacy edits are not authored by the agent. `add_event` / `update_event` accept
    signals as hints (`character_id` + `interpretation`); the intimacy interpretation
    workflow runs automatically, interprets the event per relevant character, and writes
    approved signals with evidence and creation/rewording records. Intimacy rank is
    derived by replay rather than mutated. Evidence entries and baseline intimacies stay
    directly editable in the UI, and world-state effects keep their direct CRUD authoring.
    See [story_bible_model.md](story_bible_model.md) ("Evidence-Based Intimacy State") and
    [architecture_agent_workflows.md](architecture_agent_workflows.md).

- **Context Assembly**
  - Builds each model call from the system prompt, chat history, current UI context, and workflow-specific context.
  - World content is fetched through tools instead of being loaded wholesale into every prompt.

- **Persistence**
  - Saves and loads local project state.
  - Exports complete worlds as ZIP files containing `world.json`, scene markdown files, and an assets folder.
  - Exports a readable story ZIP of HTML scene pages plus a chapter index (export-only; see [zip_import_export.md](zip_import_export.md)).
  - Keeps app config, model profiles, and secrets outside exported worlds.

## Core Boundaries

- UI stays thin; core logic lives outside NiceGUI event handlers.
- World data, app config, and secrets remain separate.
- Workflow state is ephemeral unless a tool writes to the world.
- Agent edits should use patch-style tools where possible instead of full-document replacement.

## Related Docs

- Multi-step agent workflows (scene writing and intimacy interpretation): see [architecture_agent_workflows.md](architecture_agent_workflows.md).
- Async jobs, resource claims, and background execution: see [architecture_async_jobs.md](architecture_async_jobs.md).
- LLM call logging and the Debug page: see [architecture_llm_debug_logging.md](architecture_llm_debug_logging.md).
- Model configuration and per-node model selection: see [model_configuration.md](model_configuration.md).
- Known / open issues and architectural debt: see [known_issues.md](known_issues.md).
- Planned enhancements beyond the phased plan: see [future_work.md](future_work.md).
