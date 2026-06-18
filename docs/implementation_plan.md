# Implementation Plan

> **Status: core phased implementation complete.** Every phase below is done. Further enhancements
> (including work formerly scoped as Phases 6c, 7, and 8) are tracked in
> [future_work.md](future_work.md) rather than as numbered phases here.

## Phase 0: Pre-Coding & Environment Setup (Completed)

* Dependency Management: Initialize project using Poetry.
* Environment Configuration: Create a .env file for API keys and configuration variables.
* Directory Structure: Establish a clean, basic layout before writing core logic.

---

## Phase 1: UI Skeleton & Proof of Concept (Completed)

* Main Layout: Construct the primary UI window/dashboard with two main panels, story bible navigation in a sidebar, settings screen, model config screen, and model selection screen.
* Placeholders: Populate panels with mock/placeholder data.
* Execution Verification: Run the application to confirm the UI renders successfully and is fully accessible.

---

## Phase 2: LangGraph Agent & Chat Interface (Completed)

* LangGraph Agent: Implement the LangGraph agent using a hard-coded model configuration.
* Chat UI: Replace the right side panel from Phase 1 with a simple streaming chat interface for interacting with the agent. 
* Context Assembler: Build the context assembler class to construct the agent's context with the system prompt and chat history. 
* LangGraph Tests: Add Pytest unit tests for the LangGraph agent logic.

---

## Phase 3: Markdown UI & Tool Integration (Completed)

* Markdown UI: Replace the placeholder panel from Phase 1 with the actual Markdown scene interface/renderer.
* Scene Editing Tools: Build and bind the tools required for the agent to read and edit scene Markdown directly.
* Create Scenes: Allow the agent to append to existing scenes using stream-tag interception.
* Testing: Add unit tests for each tool.

---

## Phase 4: Model Configuration & System Prompt Prefixes (Completed)

* Model Configuration UI: Add model configuration UI where the user can configure available OpenRouter models, set parameters like reasoning, and define a system prompt prefix.
* Default Model Configs: Support three default model configuration roles: small, standard, and large.
* Configuration Selector UI: Add a config selector UI where the user can set per-node model config overrides.
* Configuration Selector Logic: Wire up the config selector UI to the actual LangGraph LLM nodes.
* System Prompt Prefixes: Add system prompt prefixes, from model config, to the agent context via the context assembler.
* Testing: Add tests for the model configuration and prompt prefixes.
* Debugging: Add a debug page to view compiled prompts as they are seen by the LLM.

---

## Phase 5: Structured Story Bible (Completed)

* Data Structure: Implement the structured story bible data structures.
* Story Bible UI: Add structured forms for editing characters, locations, and lore.
* ZIP Import/Export: Implement portable world import/export, including Story Bible data and scene Markdown.
* Tools Integration: Add tools to allow the agent to interact with the story bible.
* Multiple Scenes: Add support for multiple scenes including user and agent tools to create, select, and delete scenes.

---

## Phase 6: Advanced Workflows & Sub-Agents (Completed)

Phase 6 introduces the first multi-step LangGraph workflows. The scene writer is built as an
enforced LangGraph workflow graph whose nodes may themselves be tool-enabled, and the compiled
graph is exposed to the main agent as a single tool. The cross-cutting pattern (enforced sequence,
tool-using nodes, per-node model config, write-through persistence, workflow registry) is described
in [architecture_agent_workflows.md](architecture_agent_workflows.md).

### Phase 6a: Scene-Level Stance & Stance/Mood Model Changes (Completed)

Foundational data-model changes that the scene writer (6b) builds on.

* Move Stance: Move `CharacterStance` off `Character` and onto `Scene` as a sparse, per-character
  list (`SceneCharacterStance` carrying `character_id` plus the stance fields). Stance is ephemeral
  scene posture, so it belongs to the scene, not the globally-shared character.
* Mood As Statements: Change stance `mood` from a single string to a list of short statements
  (no strength, unlike intimacies). Keep `intent`, `tactics`, and `stakes` as single string fields.
* Scene Blueprint: Add a `SceneBlueprint` to `Scene` grouping the generated craft scaffolding
  (scene `premise`, `purpose`, outline beats, and the per-character stances) so it can be rendered
  in one place and hidden outside edit mode. `title`, `summary`, `markdown`, and `notes` stay
  top-level on `Scene`.
* Schema Migration: Bump `SCHEMA_VERSION`; discard any legacy `Character.stance` values on load
  (stance is disposable scratch with nowhere meaningful to migrate to).
* Tools: Make `update_character_stance` scene-scoped (target the open/selected scene); update
  `read_character` to drop stance; add reading of a scene's blueprint.
* UI: Remove the Stance card from the character detail form; render the `SceneBlueprint`
  (including stances) in the scene editor, visible only in edit mode (hidden in preview).
* Testing: Update world-model, story-bible-tool, and UI-page tests for the relocated stance and
  list-valued mood.

### Phase 6b: Scene-Writing Workflow (`draft_scene`) (Completed)

* Workflow Graph: Build a LangGraph workflow with an enforced node sequence: formalize essential
  details -> author initial stances -> outline as concise beats -> review outline -> revise
  outline -> draft prose -> generate title and summary. Graph edges enforce the sequence.
* Tool-Enabled Nodes: Give the drafting node (and optionally the stance/outline nodes) read-only
  bible and scene tools so they can pull extra Story Bible detail on demand while staying inside
  the enforced flow.
* Inputs From Main Agent: The main agent passes a brief (premise, purpose, POV, participating
  characters, constraints); the first node formalizes it into the stored essential details.
  `draft_scene` always creates a new scene; a `revise_scene` workflow is deferred.
* Bounded Review Loop: Cap the outline review/revise loop at a configurable maximum (default 1)
  rather than looping until satisfied.
* Write-Through Persistence: Persist each generated piece to the `Scene` as its step completes
  (blueprint fields, then prose, then title/summary) so the UI reflects progress. No token-level
  streaming from the subgraph in this phase.
* Per-Node Model Config: Register the workflow's nodes with the existing per-node model-config
  override system (the Phase 4 `CHAT_NODE_ID` pattern) so cheaper roles can drive outlining and
  review while drafting uses a larger model.
* Workflow Registry: Add a workflow registry in `app/graphs/` to build and look up named
  workflows.
* Expose As Tool: Expose the compiled graph to the main agent as a `draft_scene` tool.
* Testing: Unit tests for the workflow nodes and the `draft_scene` tool.

---

## Related Docs

* Known / open issues and edge-case bugs: see [known_issues.md](known_issues.md).
* Planned enhancements beyond the phased plan: see [future_work.md](future_work.md).
