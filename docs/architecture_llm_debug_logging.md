# LLM Debug Logging

LLM debug logging captures every chat model invocation at the shared LangChain model factory, persists a bounded local call log, and exposes those records through the NiceGUI Debug page.

## Tap Point

All OpenRouter chat models are created through `get_chat_model_for_config()` in `app/models/client.py`. The factory attaches a singleton `LLMDebugCallbackHandler` to each `ChatOpenAI` instance via LangChain callbacks.

This keeps logging independent of individual graph nodes or agents. Current and future LangGraph workflows get the same logging behavior as long as they use the shared model factory.

The callback captures:

* `on_chat_model_start` - model invocation params, LangGraph node metadata, and serialized prompt messages.
* `on_llm_end` - response text, the tool calls requested by the model, plus LLM response metadata such as token usage or finish details when available.
* `on_llm_error` - the exception message and terminal error state.

Secret-like invocation keys such as API keys, authorization headers, tokens, and secrets are redacted before persistence.

## Persistence

LLM call logs are app-local debug data stored in `data/llm_call_logs.json`. They are separate from world content and should not be included in world ZIP import/export.

Each record is represented by `LLMCallRecord` with:

* `run_id` - LangChain run id for the model call.
* `status` - `running`, `success`, or `error`.
* `started_at` and `finished_at` - ISO timestamps for the call lifecycle.
* `node` - LangGraph node metadata when present.
* `model` and `params` - the model id plus scrubbed invocation params.
* `prompt` - serialized compiled prompt messages as a single text fallback.
* `prompt_messages` - structured per-message records (`role`, `content`, normalized `tool_calls`, `name`, `tool_call_id`) used to render the prompt by section.
* `response_text` and `response_metadata` - captured successful output details, including token usage when the provider returns it.
* `response_tool_calls` - normalized tool calls (`name`, `args`, `id`) the model requested in its response, so attempted calls are debuggable even when the tool later fails.
* `error` - captured failure details.
* `duration_ms` - elapsed wall-clock duration when the start event was observed.

`JsonFileLLMCallLogStore` follows the existing JSON-file persistence pattern: load the full document, write a temporary file, then atomically replace the target file. The store keeps only the newest records up to its `max_records` cap, defaulting to 200.

Because parallel workflow nodes (for example the scene review fan-out) fire callbacks concurrently, every store operation runs its full read-modify-write cycle under a blocking `threading.Lock`: concurrent writers queue and wait rather than colliding on the shared file (which previously caused Windows `PermissionError`s and torn-write corruption). If the log file is ever found corrupted on load, the store logs a warning and discards it — call logs are disposable debug data, and recovering beats failing on every subsequent call.

## Debug Page

The `/debug` page reads from `get_llm_call_log_store()`.

The sidebar lists calls newest-first and includes successful, failed, and still-running calls. A timer refreshes the sidebar so calls started from the workspace can appear without a manual reload.

The detail route `/debug/calls/{run_id}` shows a subheader with the status, timestamp, duration, and input/output/reasoning/total token counts when available, followed by collapsible sections:

* scrubbed invocation params (collapsed by default);
* the compiled prompt, split into separate bordered blocks per component (system prompt, user messages, assistant messages, tool calls, and tool responses) where tool calls render as JSON and the other components render as Markdown;
* the response, rendered as Markdown, for successful calls, followed by one JSON block per tool call the model requested;
* response metadata (collapsed by default) for successful calls;
* error text for failed calls.

Markdown-rendered content is HTML-escaped before display so prompt markup such as `<canvas>` tags is shown literally rather than being interpreted by the Markdown renderer. Each top-level section is a bordered, collapsible block with a header-styled label.

Token counts are derived from `response_metadata`, preferring LangChain `usage_metadata` and falling back to provider `token_usage`.

The Debug page is a diagnostic surface only. It should not mutate records except by reading whatever the callback handler has already persisted.
