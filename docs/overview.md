# AI Writing Assistant Overview

This project is a local-first AI writing workspace for long-form fiction and worldbuilding. It brings prose, Story Bible data, reference material, and AI collaboration into one app so writers can keep continuity without relying on disconnected chat transcripts.

## Main Goals

- Help solo writers create, revise, and maintain story worlds, characters, locations, lore, and scenes in one workspace.
- Let an AI assistant understand and edit project content through tools, not just generate text for manual copy/paste.
- Keep projects locally owned and portable through import/export.
- Use LangGraph as the core orchestration layer to learn and validate agentic workflows in a real application.

## Goal Priority

When the product goal and the LangGraph learning goal conflict, choose the LangGraph or agentic path for anything that touches the agent loop, tool execution, workflow orchestration, or multi-agent coordination.

For supporting code such as UI glue, persistence helpers, model client wrappers, file I/O, and config management, choose the simpler implementation that serves the agent layer without adding unnecessary architecture.

## Major Features

- NiceGUI-based three-column interface with navigation, content editing, and AI chat.
- Markdown scene writing, previewing, and editing.
- Structured Story Bible forms for characters, locations, and lore.
- LangGraph-powered default chat agent with tool-based content editing.
- Planned named workflows such as `draft_scene` for multi-step writing tasks.
- Local world state with ZIP import/export for complete story projects.
- Configurable model profiles for experimenting with OpenRouter-compatible models, parameters, streaming, and prompt prefixes.
