# Model Configuration

Model configuration is app data that controls which OpenRouter-compatible model each LangGraph node uses and which static system-prompt prefix is composed into that node's prompt.

For an analysis of *which* models fit each node category (requirements per node type, candidate
models, cost/speed/quality/censorship trade-offs, and proposed default bundles), see
[model_selection_analysis.md](model_selection_analysis.md).

These settings are separate from world data. They are persisted locally for the application and are not included in world ZIP import/export.

## Data Model

Each model configuration is represented by a `ModelConfig` value with:

* `id` - stable identifier used by node selections.
* `name` - user-facing label.
* `model` - OpenRouter model id, such as `anthropic/claude-sonnet-5`.
* `temperature` - optional sampling temperature.
* `reasoning_effort` - optional reasoning level: `minimal`, `low`, `medium`, `high`, `xhigh`, or
  `max`. Sent as OpenRouter's unified `reasoning.effort` parameter. On Anthropic models up
  through Claude 4.5 this converts to a thinking token budget derived from `max_tokens`; on
  Claude 4.6+ (adaptive thinking) it maps to Anthropic's `output_config.effort`, where `xhigh`
  and `max` become meaningful (older models fall back to `high`).
* `max_tokens` - optional cap on output tokens per call. For Anthropic models using
  effort-based reasoning, OpenRouter also derives the thinking budget from this value, so it
  must comfortably exceed the expected reasoning share.
* `system_prompt_prefix` - optional text prepended to the base system prompt at agent-build time.

The default configuration set contains four role-oriented configs. Each role captures a
requirement profile rather than a model size, so node defaults encode *why* a model was chosen
and each role carries the reasoning effort appropriate to its work (the rationale, node
categories, and candidate analysis live in
[model_selection_analysis.md](model_selection_analysis.md)):

* `orchestration` - `anthropic/claude-sonnet-5` at `medium` effort. Tool-calling agent work:
  strong tool reliability and instruction following over prose quality.
* `writing` - `openai/gpt-5.6-luna` at `low` effort. Long-form prose drafting: best writing per
  dollar and high throughput; planning already happened upstream, so low effort suffices.
* `judgment` - `anthropic/claude-sonnet-5` at `medium` effort. Critique and targeted revision:
  frontier judgment where outputs are short, so capability is cheap.
* `structure` - `google/gemini-3.5-flash-lite` at `low` effort. Schema-filling and
  summarization: fast, cheap structured output.

Users may add custom configurations, but code should treat the four defaults as always available.

## Node Registry

LangGraph nodes select models through a small registry rather than hard-coded conditionals in the UI. Each registry entry has:

* `node_id` - stable identifier used in persisted selections.
* `label` - user-facing node name.
* `default_config_id` - fallback config for that node.

The first registry entry is:

* `chat` - "Chat Agent", defaulting to `orchestration`.

Scene-writing workflow nodes (`generate_scene`):

* `scene_stances` - "Scene: Author Stances", defaulting to `structure`.
* `scene_outline` - "Scene: Outline", defaulting to `structure`.
* `scene_outline_review` - "Scene: Review Plan", defaulting to `judgment`.
* `scene_outline_revise` - "Scene: Revise Plan", defaulting to `judgment`.
* `scene_gather` - "Scene: Gather Context", defaulting to `orchestration`.
* `scene_draft` - "Scene: Draft Prose", defaulting to `writing`.
* `scene_prose_review` - "Scene: Review Prose", defaulting to `judgment`.
* `scene_character_review` - "Scene: Character Review", defaulting to `judgment`.
* `scene_prose_revise` - "Scene: Revise Prose", defaulting to `judgment`.
* `scene_summary` - "Scene: Summary", defaulting to `structure`.

Intimacy interpretation workflow nodes (`interpret_intimacy`):

* `intimacy_analyze` - "Intimacy: Analyze", defaulting to `judgment`.
* `intimacy_review` - "Intimacy: Review", defaulting to `judgment`.

Both are one-shot structured-output calls whose value is character judgment (signal
fidelity, score discipline, overlap checks), so they share the review role rather than
cheap schema-fill. Context assembly and validation are deterministic and have no model.

The revise nodes default to `judgment`, not `writing`: they are output-small precision work that
shares economics with the reviews, and keeping them off the `writing` config lets that config
point at a writing specialist. After the gather/write split, `scene_draft` is tool-free, so the
`writing` config no longer needs tool calling. Context gathering lives on `scene_gather` (default
`orchestration`).

Future graph nodes should be classified into one of the role categories in
[model_selection_analysis.md](model_selection_analysis.md) and added to the registry with that
default before the UI exposes selectors for them.

## Resolution Order

Model resolution is centralized in the repository facade. For a given `node_id`, `resolve_model_config(node_id)` returns:

1. The user's persisted selection for that node, when it points to an existing config.
2. The node registry default, when it points to an existing config.
3. The `orchestration` default config as a final fallback.

Callers should resolve once for the node they are building, then pass the resolved config to `get_chat_model_for_config`. The returned model carries the prefix; node-specific base prompts (where needed) are supplied separately by each graph node.

## Persistence

Model configuration is stored in `data/model_configs.json`, following the JSON-file store pattern used for chat history. Writes should be atomic: serialize the full document to a temporary file, then replace the target file.

The persisted JSON shape is:

```json
{
  "configs": [
    {
      "id": "orchestration",
      "name": "Orchestration",
      "model": "anthropic/claude-sonnet-5",
      "temperature": null,
      "reasoning_effort": "medium",
      "max_tokens": null,
      "system_prompt_prefix": ""
    }
  ],
  "selections": {
    "chat": "orchestration"
  }
}
```

The repository facade owns list, get, save, delete, select, resolve, and import/export operations. UI code should call the facade rather than reading or writing this file directly.

## Import/Export

The header overflow menu offers **Export Model Configs** and **Import Model Configs** so model configuration can be moved between installations independently of world data.

- **Format**: a plain JSON file (`model_configs.json` download) containing the persisted document shape above (`configs` + `selections`). There is no ZIP wrapper; model configuration has no per-item files or assets.
- **Export**: serializes the current repository state. The exported document is defaults-normalized, so the three built-in configs are always present.
- **Import replaces the current configuration entirely** (same semantics as Import World). The built-in `small`, `standard`, and `large` configs are always re-added if missing from the imported file.
- **Validation**: import parses and validates the JSON against the stored document schema and fails with a clear error on malformed input (bad encoding, invalid JSON, non-object payload, or schema violations). Selections referencing unknown graph nodes or configs that do not exist after import are dropped, mirroring the cleanup performed on config deletion, so no dangling references are persisted.
- The file contains no API keys or other secrets; `OPENROUTER_API_KEY` lives only in the environment/`.env`.

## Live OpenRouter Catalog

The `/models` UI fetches available models from:

```text
GET https://openrouter.ai/api/v1/models
```

The catalog parser only needs the model `id` and display `name`. Results may be cached in process and refreshed manually from the UI.

Catalog fetch failure should not block editing saved configs. When the live list is unavailable, the UI should fall back to free-text model id entry so users can keep or enter model ids manually.

## Prompt Prefixes

`system_prompt_prefix` is static prompt text for a resolved config. It is bound to the model returned by `get_chat_model_for_config` (`PrefixedChatOpenAI`) and injected on every LLM call for that config: chat agent, workflow structured nodes, and workflow drafting nodes all receive it automatically when they resolve a model through the repository.

When a node also supplies a base system prompt (for example the chat agent's `DEFAULT_SYSTEM_PROMPT`, a scene-workflow structured node passing `STORY_BIBLE_PRIMER` plus usage instructions, or the scene draft node's prose instructions), the prefix is merged into that leading system message. Nodes that send only a user message get a standalone system message containing the prefix. The merged prompt is observable in `data/llm_call_logs.json` (`prompt` / `prompt_messages` on each record).

Do not inject these prefixes through message-channel middleware. The prompt assembly details and rationale are documented in [architecture_prompt_assembly.md](architecture_prompt_assembly.md).
