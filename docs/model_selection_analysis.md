# Model Selection Analysis

Analysis of which OpenRouter models should back each category of LangGraph node, based on real
call logs (`data/llm_call_logs.json`), live OpenRouter catalog pricing, and public benchmarks
(July 2026). This doc informs the defaults in [model_configuration.md](model_configuration.md);
the mechanism for assigning models to nodes is unchanged (per-node configs via the `/models` UI).

Everything here is a recommendation, not a binding architecture decision. When a default actually
changes, update [model_configuration.md](model_configuration.md) and `app/models/config.py`.

## What the real call logs show

The current log file covers two full `generate_scene` runs plus a chat session, all on the
default Anthropic configs (haiku-4.5 / sonnet-4.5 / opus-4.5, all at `reasoning_effort: high`).
Key numbers:

| Observation | Data |
| --- | --- |
| Total logged spend | ~$1.38 across 32 calls (~$0.45–0.55 per scene generation) |
| Chat (sonnet) cost shape | Input-dominated: 107k input vs 16k output tokens |
| Draft (opus) cost shape | Output-dominated: ~2.7–3.0k output tokens per draft at 39–67 tok/s (~70 s) |
| Review nodes (haiku, high effort) | 3.8k–7.6k output tokens, 38–86 s per review |
| Revise nodes (opus) | Small outputs (~100–600 tokens per call); cost negligible |
| Throughput | haiku ~85–120 tok/s, opus ~40–67 tok/s |

Two conclusions that shape everything below:

1. **The "cheap" review nodes are neither cheap nor fast.** With `reasoning_effort: high`, haiku
   burns thousands of hidden reasoning tokens: a single prose review took **longer than the opus
   draft itself** (86 s vs 70 s) and cost a comparable amount ($5/M output on haiku). The visible
   critique is only ~2k characters; nearly all the tokens are reasoning. A stronger model at
   medium effort would cost about the same, run faster, and judge conceptual consistency far
   better. This confirms the intuition that critique steps should get a *larger* model — critique
   output is inherently short, so per-call cost stays modest even at frontier prices.
2. **Chat and draft have opposite cost profiles.** Chat spend is driven by input tokens
   (system prompt + tools + history replayed every turn), so input price and prompt caching matter
   most there. Draft spend is driven by output tokens and throughput, so output price and tok/s
   matter most. One "standard" model is not optimal for both.

## Node categories and their requirements

The registry has nine nodes, but they collapse into five requirement profiles. New nodes should
be classified into one of these categories before picking a default.

### 1. Orchestrator (tool-calling agent) — `chat`

Runs the ReAct loop against the full `WRITING_TOOLS` set: multi-step tool selection, argument
construction against validated schemas (ids, enums), and long multi-turn context. Writing quality
matters only for conversational tone; the agent rarely produces long prose itself.

- **Must have:** top-tier tool calling reliability, strong instruction following, long context,
  low time-to-first-token (it is interactive).
- **Nice to have:** prompt caching discounts (input-heavy cost shape).
- **Doesn't need:** best-in-class prose.

### 2. Long-form prose drafting — `scene_draft`

The single most expensive and latency-visible step. Produces ~10k+ characters of scene prose.
Currently also tool-enabled (read-only context pulls), which forces the drafter to be a competent
tool caller *and* the best writer — the most expensive intersection there is.

- **Must have:** best available prose quality per dollar, high output throughput (tok/s), enough
  context for continuity block + blueprint + pulled details.
- **Nice to have:** low refusal rate on dark/mature fiction themes.
- **Doesn't need (if the pipeline is split, see below):** tool calling.

### 3. Targeted revision (edit-tool ReAct) — `scene_outline_revise`, `scene_prose_revise`

Applies text-anchored `edit_prose` / `edit_outline` / `update_stance` ops. This is precision
work: the model must quote existing text *exactly* (unique-substring matching) and write short
replacement passages in the established voice. Output volume is tiny (logs show ~100–600 tokens
per call), so **even the most expensive model is cheap here** — this is the cheapest place in the
whole pipeline to buy frontier capability.

- **Must have:** precise tool calling, exact-quoting discipline, prose quality matching the
  drafter (replacement text sits inline with drafted prose).
- **Cost shape:** input-moderate, output-trivial.

### 4. Structured critique/review — `scene_outline_review`, `scene_prose_review`

One-shot `with_structured_output` calls whose value is *judgment*: catching conceptual
inconsistencies, continuity breaks, and flat writing. A small model can fill the schema but
cannot reliably notice that a character's motivation contradicts the previous scene. Output is
short by design.

- **Must have:** strong reasoning/literary judgment, reliable structured output (requires tool
  support on OpenRouter), enough context for prose + continuity block.
- **Cost shape:** output-small — same argument as category 3: buy a big model, cap the effort.
- **Anti-pattern (current default):** small model + `reasoning_effort: high`, which spends
  frontier-level token counts to get small-model judgment.

### 5. Structured generation and summarization — `scene_stances`, `scene_outline`, `scene_summary`

One-shot schema-filling with moderate creativity. Stances and outline benefit from decent story
sense but are heavily constrained by the blueprint; summary is nearly mechanical. These are the
only nodes where a genuinely small/fast model is the right call.

- **Must have:** reliable structured output, schema discipline.
- **Nice to have:** speed (they gate the start of the pipeline).

## Evaluation axes

For each candidate we care about:

- **Writing quality** — EQ-Bench Creative Writing v3 Elo and Longform leaderboard (LLM-judged;
  treat as directional, not gospel).
- **Tool calling / agentic reliability** — agentic benchmarks (BFCL, MCP Atlas, τ-bench family)
  and practitioner reputation.
- **Cost** — OpenRouter list price, split by input vs output because the node categories differ.
- **Speed** — output tok/s and TTFT (provider-dependent on OpenRouter; verify per provider).
- **Context** — must fit continuity block + blueprint (+ history for chat).
- **Censorship / refusal behavior** — over-refusal on legitimate dark or mature fiction. Lighter
  alignment generally correlates with fewer interruptions and often livelier prose. We do not
  need uncensored output, just a model that treats fiction as fiction.

## Candidate models (July 2026, OpenRouter list prices per 1M tokens)

### Writing tier (drafting, prose revision)

| Model | In / Out $ | CW v3 Elo | Speed | Censorship | Notes |
| --- | --- | --- | --- | --- | --- |
| `openai/gpt-5.6-sol` | 5.00 / 30.00 | **2208 (#1)** | moderate | moderate | Best measured prose; expensive, verbose (long outputs) |
| `anthropic/claude-fable-5` | 10.00 / 50.00 | 2156 (#2) | moderate | **most restrictive** | Purpose-built fiction model, Longform #1 — but ships a safety classifier that can refuse or reroute; risky for dark themes |
| `anthropic/claude-opus-4.7` | 5.00 / 25.00 | 2083 | ~40 tok/s | restrictive | Best Anthropic value at the top; users report fewer refusals than 4.8/Fable |
| `openai/gpt-5.6-luna` | **1.00 / 6.00** | 1932 | fast | moderate | Standout value: outscores opus-4.5 by ~170 Elo at ~1/5 the price |
| `openai/gpt-5.6-terra` | 2.50 / 15.00 | 1928 | fast | moderate | Slightly stronger sibling of luna at 2.5x the price |
| `anthropic/claude-sonnet-4.6` | 3.00 / 15.00 | 1895 | moderate | restrictive | Outwrites opus-4.5 at sonnet prices |
| `z-ai/glm-5.2` | **0.80 / 2.50** | 1746 | **~168 tok/s** | permissive-ish | Matches opus-4.5's writing Elo at ~1/10 cost and 3–4x speed; open weights (MIT) |
| `moonshotai/kimi-k2.6` | 0.68 / 3.42 | 1716 | moderate | moderate | Cheapest "frontier-adjacent" writer |
| `x-ai/grok-4.5` | 2.00 / 6.00 | 1590 | fast | **most permissive** | Weakest prose in this tier but the least refusal friction; good fallback when Claude/GPT balk |
| *(current)* `anthropic/claude-opus-4.5` | 5.00 / 25.00 | 1759 | ~40–67 tok/s | restrictive | Mid-table on writing now; paying top price for no-longer-top prose |

Community fiction fine-tunes (TheDrummer's Cydonia/Skyfall, etc.) are maximally permissive and
cheap but have **no tool support**, small contexts, and weak long-form coherence — unusable for
any node in this codebase except possibly a future no-tools pure-drafting node, and even there
coherence is the concern.

### Orchestrator / tool-calling tier (chat, plan revise)

| Model | In / Out $ | Agentic strength | Speed | Notes |
| --- | --- | --- | --- | --- |
| `anthropic/claude-sonnet-5` | 2.00 / 10.00 | excellent | moderate | Drop-in upgrade: better and cheaper than sonnet-4.5 |
| `google/gemini-3.5-flash` | 1.50 / 9.00 (0.15 cached) | excellent (leads MCP Atlas) | **~289 tok/s** | 90% cache discount is huge for the input-heavy chat shape |
| `moonshotai/kimi-k3` | 3.00 / 15.00 | **top of agentic benchmarks** | ~62 tok/s | Strongest measured agentic model; no cost advantage over sonnet-5 |
| `openai/gpt-5.4-mini` | 0.75 / 4.50 | good | fast | Budget orchestrator; CW Elo 1684 so chat prose stays decent |
| `deepseek/deepseek-v4-pro` | 0.43 / 0.87 | good | ~62 tok/s | Extreme value; tool-call serialization reliability is the thing to verify |
| `minimax/minimax-m3` | 0.30 / 1.20 | good | fast | Best agentic-per-dollar in the budget tier |

### Judgment tier (plan review, prose review)

Same shortlist as the writing/orchestrator tiers — the point is to use a *strong* model with
capped reasoning effort. Good fits: `anthropic/claude-sonnet-5` or `google/gemini-3.1-pro-preview`
(2.00 / 12.00, strong long-context judgment) at `medium` effort; `openai/gpt-5.6-terra` if
staying in the GPT family. Avoid small models here regardless of price.

### Cheap structured tier (stances, outline, summary)

| Model | In / Out $ | Notes |
| --- | --- | --- |
| `google/gemini-3.5-flash-lite` | 0.30 / 2.50 | Fastest option with reliable structured output |
| `openai/gpt-5.4-mini` | 0.75 / 4.50 | Safe default; nano (0.20 / 1.25) for summary only |
| `deepseek/deepseek-v4-flash` | 0.09 / 0.19 | Cheapest credible option; 1M context |
| `qwen/qwen3.6-flash` | 0.19 / 1.12 | Strong schema discipline for the price |
| *(current)* `anthropic/claude-haiku-4.5` | 1.00 / 5.00 | 2–10x the price of the options above |

## Pipeline restructuring options

These interact with model choice; each can be adopted independently.

### Split drafting into "gather" + "write"

Today `scene_draft` is a tool-enabled ReAct loop, so the drafter must be both the best writer and
a reliable tool caller. The logs show the loop making 1–3 small tool-selection calls (each
replaying the growing context at opus input prices) before the big generation. Splitting it:

1. **Gather node** (new, category 1/5 hybrid): a strong cheap tool caller (e.g. gemini-3.5-flash
   or sonnet-5) reads the blueprint + continuity block, pulls whatever Story Bible detail it
   needs via the existing read-only tools, and emits a consolidated context dossier.
2. **Write node** (`scene_draft`, now tool-free single-shot): the best writer-per-dollar gets one
   prompt with everything it needs and streams prose.

Benefits: the writer pool expands to models with weak or no tool calling (several of the best
writing values — glm-5.2, gpt-5.6-luna — are much better writers than tool agents); the expensive
model sees exactly one input instead of a replayed ReAct transcript; the gather step is faster on
a flash-class model. Cost: one extra node, and the dossier must be good — a weak gatherer starves
the writer. Keep the gather node on at least sonnet/flash class.

### Draft small, revise large — or draft large, revise cheap?

The idea of letting a smaller model draft and opus-class revise is directionally right about
*where revision is cheap* (revise output is tiny), but backwards about *what revision can fix*.
The revise nodes apply targeted search/replace edits bounded at one pass; they repair
inconsistencies and weak lines, they do not transform voice or pacing. The drafter sets the
prose ceiling. So:

- **Keep the strongest affordable writer on `scene_draft`.** That no longer implies Opus prices —
  see the writing tier table.
- **Put frontier judgment on the *review* nodes** (which decide what to fix) and a
  precise, strong model on `scene_prose_revise` (which must quote text exactly and write inline
  replacements). Both are output-small, so frontier pricing costs cents there.
- The economical version of the user-facing goal ("get Opus-quality benefit without Opus token
  volume") is exactly this: big model where outputs are short (review/revise), value-tier writing
  specialist where outputs are long (draft).

### Tune reasoning effort per node, not globally

All three default configs ship `reasoning_effort: high`, which is the main reason the review
nodes are slow (thousands of hidden reasoning tokens). Suggested shape:

- `high` only where judgment is the product: plan review, prose review.
- `medium`/`low` for drafting — reasoning tokens buy planning, but the outline node already did
  the planning; most writing specialists do fine at low effort.
- `minimal`/`low` for stances, outline, summary, and revision mechanics.

This is a pure config change (the `/models` UI already exposes effort per config) and is likely
the single biggest latency win available, independent of any model swap.

## Recommended default mapping (proposal)

Three coherent bundles rather than one prescription, since writing taste is personal and refusal
tolerance depends on the project's content:

| Node category | Balanced (recommended) | Quality-max | Budget / permissive |
| --- | --- | --- | --- |
| Chat orchestrator | `anthropic/claude-sonnet-5` | `anthropic/claude-sonnet-5` | `google/gemini-3.5-flash` |
| Stances / outline / summary | `google/gemini-3.5-flash-lite` | `openai/gpt-5.4-mini` | `deepseek/deepseek-v4-flash` |
| Plan + prose review | `anthropic/claude-sonnet-5` (medium effort) | `google/gemini-3.1-pro-preview` (high) | `z-ai/glm-5.2` (medium) |
| Draft prose | `openai/gpt-5.6-luna` | `openai/gpt-5.6-sol` or `anthropic/claude-opus-4.7` | `z-ai/glm-5.2` or `x-ai/grok-4.5` |
| Plan / prose revise | `anthropic/claude-sonnet-5` | `anthropic/claude-opus-4.7` | `z-ai/glm-5.2` |

### Role-based default configs (replace the size ladder)

The `small` / `standard` / `large` default configs force node assignment onto a single
capability-vs-price axis, which is how the review nodes ended up on a small model: they were
classified "cheap" when their actual requirement (conceptual judgment) is what small models lack.
The defaults should instead be four role-oriented configs matching the requirement profiles above:

| Role config | Serves node categories | Nodes | Effort default |
| --- | --- | --- | --- |
| `orchestration` | 1 (tool-calling agent) | `chat` | medium |
| `writing` | 2 (long-form prose) | `scene_draft` | low–medium |
| `judgment` | 3 + 4 (critique and targeted revision) | `scene_outline_review`, `scene_prose_review`, `scene_outline_revise`, `scene_prose_revise` | high (reviews are the one place reasoning is the product) |
| `structure` | 5 (schema-filling) | `scene_stances`, `scene_outline`, `scene_summary` | minimal–low |

Notes on the mapping:

- The revise nodes live under `judgment`, not `writing`: they are output-tiny frontier work that
  needs exact quoting and shares a model with the reviews in both recommended bundles. This also
  keeps revision functional if a future gather/write split assigns a weak- or no-tool writing
  specialist to the `writing` config.
- Each role carries its own `reasoning_effort` default, which fixes the
  small-model-at-high-effort pathology structurally instead of as one-time tuning.
- Swapping one role's model updates every node of that role without disturbing the others —
  the main practical benefit for experimentation.

Implementation notes (when adopted): the built-in ids live in `app/models/config.py`
(`*_CONFIG_ID`, `DEFAULT_MODEL_CONFIGS`, `GRAPH_NODES`) and `_default_selections()` in
`app/persistence/model_configs.py`. Persisted `data/model_configs.json` documents already contain
the size-based ids and selections pointing at them, and `_with_defaults()` re-injects built-ins on
every load — so renaming requires a load-time migration (alias `small`/`standard`/`large`
selections to their nearest role id, and drop or convert the stale built-in configs) plus updating
`DEFAULT_MODEL_CONFIG_IDS`-driven behavior (delete-resets-built-ins, UI ordering) and the tests
that reference the old ids. Update [model_configuration.md](model_configuration.md) alongside the
code.

Estimated effect of the balanced bundle vs today's defaults, using the logged token volumes:
per-scene LLM cost drops from roughly $0.50 to roughly $0.10–0.15, and wall-clock generation time
roughly halves (draft on a faster writer, reviews no longer burning 40–90 s of haiku reasoning).
Chat cost drops ~30–50% depending on caching.

On `claude-fable-5`: it is the best pure fiction model on the boards, but it is *more* expensive
than Opus and ships the most aggressive safety layer Anthropic has (classifier-based refusal and
rerouting, with user reports of friction on ordinary fiction). For a workspace whose stories may
go dark, it is a "try it on one scene" candidate, not a default.

## Caveats and how to validate

- **Benchmarks are LLM-judged** (EQ-Bench uses a Claude judge) and reshuffle monthly. Treat Elo
  gaps under ~50 as noise; re-check before committing.
- **OpenRouter throughput varies by provider.** The tok/s figures are best-provider numbers; pin
  or verify providers for latency-sensitive nodes.
- **Structured output requires tool support** on the chosen model/provider (all main candidates
  above have it; community fine-tunes do not).
- **Validation is cheap with existing plumbing:** assign a candidate to a node in `/models`,
  regenerate the same scene, and compare prose plus `data/llm_call_logs.json` timing/token
  numbers side by side. The blueprint fingerprint / regenerate flow makes A/B runs repeatable.
- **Edit-tool fragility is model-sensitive:** `edit_prose`/`edit_outline` require exact quoting;
  before adopting a non-Claude model for revise nodes, run a scene through revision and check the
  per-op error reports in the logs (see the known quoting fragility in
  [known_issues.md](known_issues.md)).
