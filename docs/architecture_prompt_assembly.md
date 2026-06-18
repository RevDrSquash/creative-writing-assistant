# Architecture Brief: Chat Prompt Assembly

**Objective:** Document how the chat agent's prompt is built today and how Phase 4 (system prompt prefixes) and Phase 6 (user context notes) should plug in without re-introducing the design mistakes from Phase 2.

## 1. Decision: use `create_agent(system_prompt=...)`, not a `before_model` middleware

The Phase 2 chat agent originally injected the system prompt via a custom `ContextAssemblyMiddleware.before_model` that wrote `[RemoveMessage(REMOVE_ALL_MESSAGES), SystemMessage(...), *history]` to the graph's `messages` channel. That was overbuilt for the actual requirement (static system prompt) and produced a real bug. We replaced it with `create_agent(model=..., system_prompt=assembler.system_prompt)`.

## 2. Why - state channel vs. model request

LangChain's `create_agent` exposes two ways to put a system prompt in front of the model, and they live at different layers:

* **`system_prompt=` parameter:** modifies the *model request*. The SystemMessage is prepended only when the model node constructs the LLM call; it is never written to graph state. The final `state["messages"]` and the `stream_mode="messages"` stream contain only the user/assistant/tool messages that actually belong to the conversation.
* **`before_model` middleware writing to `messages`:** modifies the *messages channel*. Anything written there is part of graph state and is emitted by `stream_mode="messages"` tagged with `langgraph_node="<MiddlewareName>.before_model"`. Consumers see the SystemMessage as a chunk in the stream.

We were doing the second when we only needed the first. The observable symptom was the system prompt being concatenated onto the front of every assistant reply in the UI, because the UI's stream consumer accepted any chunk's `.content`. The deeper cost was conceptual: the agent's persisted message list was contaminated with a SystemMessage that didn't belong there.

## 3. What stays and what goes

* **Removed:** `ContextAssemblyMiddleware`, the `RemoveMessage` / `REMOVE_ALL_MESSAGES` dance, and `ContextAssembler.assemble`'s system-message stripping/prepending logic. None of these are needed once `system_prompt=` does the work.
* **Kept:** `ContextAssembler` as a thin holder/builder for the system prompt string. It's the home for composition logic that Phase 4 will need.
* **Kept:** the UI's `isinstance(token, AIMessageChunk)` filter in `_token_text`. With `system_prompt=` it is no longer plugging an active leak, but it stays as belt-and-suspenders for Phase 3 `ToolMessage` chunks.

## 4. Phase 4: system prompt prefixes

Per-node model configs carry a `system_prompt_prefix`. The prefix is bound to the resolved model at construction time and injected on every LLM call, so it is impossible to use a config without also applying its prefix.

* `get_chat_model_for_config` in `app/models/client.py` returns a `PrefixedChatOpenAI` that stores `system_prompt_prefix` from the resolved `ModelConfig`.
* Prefix injection runs in the public `generate` / `agenerate` / `stream` / `astream` entry points (before `on_chat_model_start`), so the merged prompt is what both the model API and the local debug log see. If the request already has a leading `SystemMessage` (for example from `create_agent(system_prompt=...)`), the prefix is merged into it; otherwise a new leading `SystemMessage` is inserted (structured-output workflow nodes that send only a `HumanMessage`). `_apply_prefix` is idempotent so the `stream` -> `invoke` fallback cannot double-apply the prefix.
* `ContextAssembler` holds only the node-specific base prompt (for the chat agent, `DEFAULT_SYSTEM_PROMPT`). It does not compose prefixes.
* `build_chat_agent` passes `assembler.system_prompt` to `create_agent(system_prompt=...)` and resolves the model through `get_chat_model_for_config`, which applies the prefix transparently.
* The cached agent (`_CHAT_AGENT` in `app/graphs/chat_agent.py`) cache key includes `system_prompt_prefix` so a config change triggers a rebuild.

This stays out of message-channel middleware. If we later need per-call dynamism (e.g., the prefix depends on per-invocation runtime config), we can extend `PrefixedChatOpenAI` or use `create_agent`'s callable `system_prompt=` form.

## 5. Phase 6: user context notes

User context notes are a *different problem*. They annotate the latest `HumanMessage` with a description of the user's currently open page or focused content. They do not belong in the system prompt and do not change per model-call config - they change per user turn.

This is where middleware is the right tool:

* Add a `UserContextMiddleware` with `before_model` (or `before_agent`) that inspects `state["messages"]`, finds the most recent `HumanMessage`, and replaces it with a copy whose content has the context note appended.
* The middleware writes to the `messages` channel deliberately - because the note is part of the user's turn for that run.
* Use the same `RemoveMessage(REMOVE_ALL_MESSAGES)` + rebuilt list idiom to preserve message ordering through the `add_messages` reducer.
* The UI's `AIMessageChunk` filter already prevents the modified `HumanMessage` from leaking into the assistant bubble during streaming.

Critically, this middleware is **orthogonal to the system prompt**. Phase 6 should not touch `ContextAssembler` or `create_agent(system_prompt=...)`. Keeping the two concerns separate is what avoids the conflation that produced the Phase 2 bug.

## 6. Rules of thumb

* If a piece of context is **static for the duration of an agent run and lives in front of the conversation**, it belongs in `system_prompt=`.
* If a piece of context **annotates a specific message in the conversation**, it belongs in middleware that writes to the `messages` channel.
* Anything written to the `messages` channel is observable via `stream_mode="messages"`. UI consumers must filter by message type (and, if needed, `metadata["langgraph_node"]`) - never blindly forward `.content`.
