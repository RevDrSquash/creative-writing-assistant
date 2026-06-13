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
- **Storage:** local JSON and ZIP import/export

## Module Structure

- `app/ui/` - NiceGUI layout, navigation, editor/forms, chat, model config.
- `app/graphs/` - LangGraph workflows, graph builders, workflow registry, run state.
- `app/tools/` - Agent tools for reading, searching, creating, and editing world content.
- `app/world/` - Pydantic world models, validation, and in-memory world state.
- `app/persistence/` - Local save/load plus ZIP import/export.
- `app/models/` - Model profiles, resolved model bundles, and LLM client setup.

## Major Components

- **NiceGUI UI**
  - Three-column workspace: navigation, content editor/forms, AI chat.
  - Shows markdown scenes, Story Bible forms, streamed assistant output, and tool-call results.

- **World State**
  - A single in-memory `World` object is the source of truth.
  - Contains metadata, scenes, Story Bible data, and chat history.
  - User edits and AI tool calls both update this same object.
  - All writes to `world.json` are serialized behind a process-wide lock in `app/world/store.py`.
    Agent tool calls can run concurrently in worker threads, and on Windows two overlapping
    atomic saves collide on the file lock.
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
  - V1 default workflow is a single ReAct loop for free-form chat.
  - Later workflows can compose multiple nodes for tasks like outlining, critiquing, revising, and drafting.

- **Tool Layer**
  - Tools expose explicit actions such as reading scenes, listing world data, appending prose, replacing text, and updating Story Bible fields.
  - Write tools mutate world state before returning.
  - Tools raise `ToolException` for expected domain errors (e.g. an unknown entity id). The agent is built with a `ToolRetryMiddleware(max_retries=0, on_failure="continue")` so a failing tool call produces an error `ToolMessage` for the model to recover from instead of aborting the run. Tools are local and deterministic, so retries are disabled.
  - Workflows or subagents can also be exposed as tools.

- **Context Assembly**
  - Builds each model call from the system prompt, chat history, current UI context, and workflow-specific context.
  - World content is fetched through tools instead of being loaded wholesale into every prompt.

- **Persistence**
  - Saves and loads local project state.
  - Exports complete worlds as ZIP files containing `world.json`, scene markdown files, and an assets folder.
  - Keeps app config, model profiles, and secrets outside exported worlds.

## Core Boundaries

- UI stays thin; core logic lives outside NiceGUI event handlers.
- World data, app config, and secrets remain separate.
- Workflow state is ephemeral unless a tool writes to the world.
- Agent edits should use patch-style tools where possible instead of full-document replacement.

## Related Docs

- LLM call logging and the Debug page: see [architecture_llm_debug_logging.md](architecture_llm_debug_logging.md).
- Model configuration and per-node model selection: see [model_configuration.md](model_configuration.md).
- Known / open issues and architectural debt: see [known_issues.md](known_issues.md).
- Planned enhancements beyond the phased plan: see [future_work.md](future_work.md).
