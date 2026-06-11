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

## Phase 5: Structured Story Bible

* Data Structure: Implement the structured story bible data structures.
* Story Bible UI: Add structured forms for editing characters, locations, and lore.
* ZIP Import/Export: Implement portable world import/export, including Story Bible data and scene Markdown.
* Tools Integration: Add tools to allow the agent to interact with the story bible.
* Multiple Scenes: Add support for multiple scenes including user and agent tools to create, select, and delete scenes.

---

## Phase 6: User Context Notes

* Current Page Context: Add a note to each user message describing the user's currently open page or focused content.
* Initial Story Bible Summary: Include an initial Story Bible summary in the user message note so the agent starts with basic world context.
* Context Tests: Add tests for user message note generation.

---

## Phase 7: Advanced Workflows & Sub-Agents

* Sub-Agent: Create a scene writer sub-agent.
* Sub-Agent Tools: Expose the scene writer sub-agent to the main agent as a tool.

---

## Phase 8: Chat & Tool UX Polish

* Tool-Call Display: Render tool calls clearly in the chat history.
* Tool Confirmations: Add tool confirmations to the chat window, including diffs where agent tools edit scene Markdown or Story Bible data.
* Stop/Cancel: Add controls to stop or cancel in-flight agent and sub-agent runs.

---

## Related Docs

* Known / open issues and edge-case bugs: see [known_issues.md](known_issues.md).
* Planned enhancements beyond the phased plan: see [future_work.md](future_work.md).
