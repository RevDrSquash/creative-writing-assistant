# Model Configuration

Model configuration is app data that controls which OpenRouter-compatible model each LangGraph node uses and which static system-prompt prefix is composed into that node's prompt.

These settings are separate from world data. They are persisted locally for the application and are not included in world ZIP import/export.

## Data Model

Each model configuration is represented by a `ModelConfig` value with:

* `id` - stable identifier used by node selections.
* `name` - user-facing label.
* `model` - OpenRouter model id, such as `moonshotai/kimi-k2.6`.
* `temperature` - optional sampling temperature.
* `reasoning_effort` - optional reasoning level: `low`, `medium`, or `high`.
* `system_prompt_prefix` - optional text prepended to the base system prompt at agent-build time.

The default configuration set contains three role-oriented configs:

* `small` - fast, lower-cost tasks.
* `standard` - default chat behavior; this keeps the current `moonshotai/kimi-k2.6` model.
* `large` - higher-capability tasks where latency or cost is less important.

Users may add custom configurations, but code should treat the three defaults as always available.

## Node Registry

LangGraph nodes select models through a small registry rather than hard-coded conditionals in the UI. Each registry entry has:

* `node_id` - stable identifier used in persisted selections.
* `label` - user-facing node name.
* `default_config_id` - fallback config for that node.

The first registry entry is:

* `chat` - "Chat Agent", defaulting to `standard`.

Future graph nodes should be added to the registry with their own defaults before the UI exposes selectors for them.

## Resolution Order

Model resolution is centralized in the repository facade. For a given `node_id`, `resolve_model_config(node_id)` returns:

1. The user's persisted selection for that node, when it points to an existing config.
2. The node registry default, when it points to an existing config.
3. The `standard` default config as a final fallback.

Callers should resolve once for the node they are building, then pass the resolved config to the LLM client and context assembler.

## Persistence

Model configuration is stored in `data/model_configs.json`, following the JSON-file store pattern used for chat history. Writes should be atomic: serialize the full document to a temporary file, then replace the target file.

The persisted JSON shape is:

```json
{
  "configs": [
    {
      "id": "standard",
      "name": "Standard",
      "model": "moonshotai/kimi-k2.6",
      "temperature": null,
      "reasoning_effort": null,
      "system_prompt_prefix": ""
    }
  ],
  "selections": {
    "chat": "standard"
  }
}
```

The repository facade owns list, get, save, delete, select, and resolve operations. UI code should call the facade rather than reading or writing this file directly.

## Live OpenRouter Catalog

The `/models` UI fetches available models from:

```text
GET https://openrouter.ai/api/v1/models
```

The catalog parser only needs the model `id` and display `name`. Results may be cached in process and refreshed manually from the UI.

Catalog fetch failure should not block editing saved configs. When the live list is unavailable, the UI should fall back to free-text model id entry so users can keep or enter model ids manually.

## Prompt Prefixes

`system_prompt_prefix` is static prompt text for a resolved config. It is composed with the base writing-assistant prompt by the context assembler and passed to `create_agent(system_prompt=...)` when the agent is built.

Do not inject these prefixes through message-channel middleware. The prompt assembly details and rationale are documented in [architecture_prompt_assembly.md](architecture_prompt_assembly.md).
