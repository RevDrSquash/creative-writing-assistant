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

- **LangGraph Orchestration**
  - All AI behavior runs through LangGraph.
  - V1 default workflow is a single ReAct loop for free-form chat.
  - Later workflows can compose multiple nodes for tasks like outlining, critiquing, revising, and drafting.

- **Tool Layer**
  - Tools expose explicit actions such as reading scenes, listing world data, appending prose, replacing text, and updating Story Bible fields.
  - Write tools mutate world state before returning.
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

- Known / open issues and architectural debt: see [known_issues.md](known_issues.md).
- Planned enhancements beyond the phased plan: see [future_work.md](future_work.md).
