# Architecture Brief: Hybrid AI Document Editor

**Objective:** Implement a "Canvas-like" system for generating and editing large markdown files. The system must bypass JSON parameter limitations for large file generation while minimizing token usage and latency during subsequent edits.

## 1. File Creation: Stream Interception

* **Concept:** Avoid JSON tool calls for whole-file generation.
* **Mechanism:** The system prompt instructs the LLM to wrap new document content in designated tags (e.g., `<document>...</document>`) within its standard text response.
* **Implementation:** The frontend or middleware parses the incoming LLM token stream. Upon detecting the opening tag, it intercepts the subsequent tokens and pipes them directly into the markdown editor UI.

## 2. File Editing: Targeted Patching

* **Concept:** Use a structured tool call to mutate existing files without rewriting the entire document.
* **Mechanism:** Provide the LLM with a `replace_text` tool (or similar patching mechanism) that takes a target section and the new replacement content.
* **Failure Mitigation:** Because LLMs often fail at exact string matching (introducing whitespace or line-break hallucinations), the backend patching logic must not rely on strict equality. Implement fuzzy string matching (e.g., Levenshtein distance) to mitigate this. Also return an error message to the LLM if the patch mathces more than one location.

## Appendix: LangGraph Implementation Strategy

**Framework Role:** LangGraph acts as the state orchestration and backend streaming engine. It handles the concurrent delivery of raw token streams (for creation) and structured state updates (for editing).

### 1. Creation Streaming via `stream_mode="messages"`

* **Implementation:** Execute the graph using LangGraph's multi-stream mode: `graph.stream(inputs, stream_mode=["messages", "updates"])`.
* **Routing:** The `messages` chunk stream delivers individual tokens in real time. Use the LangGraph stream metadata (`metadata={"langgraph_node": "writer_node"}`) to filter out internal agent reasoning or planning nodes.
* **Frontend Action:** Only pass raw tokens from the designated document-generation node to the frontend parser to listen for the `<document>` tag boundary.

### 2. State Syncing via `stream_mode="updates"`

* **Implementation:** When the LLM calls the `replace_text` tool node, the tool mutates the file content stored in the Graph State (e.g., `state["current_document"]`).
* **Routing:** Upon tool completion, LangGraph emits an out-of-band `updates` event containing the newly modified state.
* **Frontend Action:** The UI intercepts this structured update to instantly refresh or hard-sync the editor canvas with the post-patch version of the file, completely bypassing the need to stream the unchanged text.

### 3. Out-of-Band Tool Feedback via `get_stream_writer()`

* **Implementation:** Inside the `replace_text` tool, use LangGraph's native `get_stream_writer()` to emit custom event payloads while the tool is calculating the fuzzy match or line diff.
* **Frontend Action:** The client handles these custom events to display inline UI indicators—such as "Locating target block..." or "Applying line patch..."—directly on the Canvas while the backend file modification is in progress.
