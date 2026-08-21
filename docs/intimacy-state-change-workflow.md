# Intimacy State Change Workflow

> **Status: superseded handoff spec (kept for reference).** This is the original desired-state
> handoff for the evidence-based intimacy system. The binding architecture decisions now live in
> the authoritative docs — [story_bible_model.md](story_bible_model.md) (evidence data model,
> derived rank, replay semantics) and
> [architecture_agent_workflows.md](architecture_agent_workflows.md) (the planned intimacy
> interpretation workflow) — with implementation tracked in the "Evidence-Based Intimacy System"
> Linear project. Where this document conflicts with those docs, the docs win. Notable
> supersessions decided in the 2026-08-21 project review:
>
> - **No dual-path rollout** (§9's feature-flag/back-compat clause): the agent's direct
>   intimacy-effect authoring is removed when the pipeline lands, not kept alongside it.
> - **No conditional routing in v1** (§3.1, §7): context assembly is deterministic and the
>   reviewer runs on every character-event analysis.
> - **No candidate/incubating intimacies in v1** (§3.4, §5): approved proposals create
>   canonically at `minor`.
> - **Direction enum is `supports` | `contradicts` only** (§3.3): mixed evidence is represented
>   as separate entries.
> - **Evaluation and observability (§8) are deferred entirely** until the project builds eval
>   infrastructure.
>
> This file should eventually be folded into the architecture docs and removed.

**Audience:** Coding agent integrating the workflow into the existing repository  
**Purpose:** Describe the intended behavior, responsibilities, and model-routing options without prescribing a specific implementation.

## 1. Objective

The intimacy system should represent gradual, evidence-based character change over the course of a story.

Events should not directly mutate intimacy state. Instead, each event should produce a character-specific interpretation, called a **signal**. The system should determine how that signal relates to the character's existing intimacies, preserve that evidence, and apply state changes only after enough relevant evidence has accumulated.

The workflow should prioritize:

- character-specific interpretation rather than a single event-level interpretation;
- preservation of the reasons an intimacy has developed;
- conservative, consistent intimacy creation, strengthening, weakening, and reframing;
- resistance to rapid escalation from isolated scenes;
- structured outputs that can be inspected, reviewed, tested, and applied deterministically;
- parallel execution for each character involved in a scene;
- model routing that reserves expensive reasoning for consequential or ambiguous decisions.

The coding agent should inspect the existing repository and fit this behavior into its current domain model, orchestration, storage, and tool abstractions. The stages below describe conceptual responsibilities and do not necessarily require one agent or model call per stage.

## 2. Core Concepts

### Primary identity

A character has a relatively stable primary identity that provides broad continuity. This workflow is mainly concerned with intimacies rather than directly changing primary identity, although sufficiently important intimacy development may eventually inform a separate identity-level process.

### Intimacy

An intimacy is a durable belief, feeling, commitment, value, attachment, aversion, or relationship that influences a character's choices.

Intimacies use the Exalted-inspired ranks:

- **Minor:** meaningful but contextual, limited, or relatively easy to challenge;
- **Major:** strongly held and regularly influential;
- **Defining:** central to the character and reflected across much of their behaviour.

Higher-ranked intimacies should be progressively harder to create, strengthen, weaken, replace, or reframe. A single ordinary event should almost never change a defining intimacy's rank.

### Event blueprint

The event blueprint describes what happens in the story and may identify the characters involved. It should not be treated as authoritative about what the event means to every character.

Any signals currently proposed in the event blueprint should be treated as hints or hypotheses unless the repository has a strong reason to preserve them as inputs.

### Signal

A signal is one character's interpretation or internalized meaning of an event.

A signal is not simply:

- a summary of the event;
- the objective lesson the author intends;
- the character's momentary emotion;
- or an intimacy mutation.

It should capture what the event appears to demonstrate, confirm, threaten, or call into question from that character's perspective.

Different characters should normally receive different signals from the same event.

### Signal–intimacy relationship

A signal may support, contradict, complicate, or be unrelated to an intimacy. The strength belongs to the **relationship between a particular signal and a particular intimacy**, not necessarily to the event or signal globally.

The same signal may strongly contradict one intimacy while weakly supporting another.

## 3. Desired Workflow

### 3.1 Run once per relevant character

After an event blueprint is available, run the intimacy interpretation workflow independently and, where practical, in parallel for each relevant character.

Each character-level run should have access to enough context to interpret the event faithfully, such as:

- the event blueprint;
- the character sheet and primary identity;
- current intimacies and their ranks;
- recent signals connected to relevant intimacies;
- selected prior scenes or searchable story context when needed.

Context retrieval should be bounded. Most scenes should not require loading the character's entire history. Deeper retrieval is most useful when the event is ambiguous, conflicts with prior evidence, proposes a strong effect, or approaches a state-change threshold.

### 3.2 Generate the character-specific signal

Derive the signal from the event and the character sheet rather than accepting an event-level signal as canonical.

The result should be concise enough to reuse later but specific enough to preserve the meaningful interpretation. It may include a brief rationale or evidence from the event.

The signal generator should distinguish between:

- what happened;
- how the character emotionally reacted;
- what the character inferred from it;
- and what durable belief or expectation the event may bear upon.

Temporary feelings can be recorded as context, but they should not automatically become signals with lasting intimacy effects.

### 3.3 Match the signal against existing intimacies

Evaluate the signal against the character's existing intimacies and identify only the relationships that are meaningfully supported by the event.

For each affected intimacy, return at least:

- a stable intimacy identifier;
- a direction;
- a strength;
- brief evidence or rationale;
- optionally, confidence or ambiguity.

Prefer separate `direction` and `strength` fields over a single signed number. A signed value can be derived later.

Possible directions may include:

- `supports`;
- `contradicts`;
- `mixed` or `complicates`, when the effect genuinely cannot be represented as a single direction;
- `unrelated`, usually represented by omitting the intimacy rather than emitting a zero-value relationship.

If a mixed relationship is actually two separable interpretations, representing them explicitly may be clearer than using a generic mixed score.

### 3.4 Propose new or reframed intimacies

The analysis may suggest:

- a genuinely new intimacy;
- a refinement of an existing intimacy's wording;
- a narrower or broader interpretation of an existing intimacy;
- or no canonical intimacy change.

A new intimacy should be proposed only when the signal suggests something that is:

- potentially persistent rather than a temporary reaction;
- distinct from existing intimacies;
- likely to affect future choices;
- meaningful enough to track as character state.

A proposal is not the same as canonical creation. The implementation may support candidate or incubating intimacies that accumulate evidence before becoming active, but the exact mechanism should fit the existing repository.

Rewording should be treated separately from rank changes. An intimacy can become more specific, nuanced, or contextually accurate without becoming stronger or weaker.

### 3.5 Review the complete proposal

A review stage should consider the character-level result as a whole:

- the signal;
- the interpretation of the event;
- every proposed signal–intimacy relationship;
- direction and strength ratings;
- proposed new intimacies;
- proposed rewordings;
- relevant recent history.

The reviewer may approve, revise, reject, or request deeper context.

The reviewer should specifically check for:

- event-summary language masquerading as a signal;
- interpretations that do not fit the character;
- omitted existing intimacies;
- spurious or overly broad intimacy matches;
- inflated strength ratings;
- temporary emotions presented as durable state;
- new intimacies that duplicate or substantially overlap existing ones;
- a proposed new intimacy that should instead reinforce or reframe an existing intimacy;
- rank-changing evidence based on repeated versions of essentially the same event;
- conclusions unsupported by the available scene evidence.

This review is intentionally focused on one event and one character. It should not be responsible for globally reorganizing the character's full intimacy set.

### 3.6 Persist the approved evidence

Store the approved signal and its relationships even when no intimacy changes rank.

The history should make it possible to understand:

- why an intimacy exists;
- what has recently reinforced or challenged it;
- whether evidence is broad or repetitive;
- how its wording and meaning have evolved;
- what context may be relevant to future scene writing.

Useful stored information may include:

- event or scene identifier;
- character identifier;
- signal text;
- affected intimacy identifiers;
- direction and strength;
- evidence or rationale;
- reviewer decision or corrections;
- ordering or story-time metadata;
- schema/model/prompt version where useful for debugging.

Writers should usually receive a selected recent or relevant subset of this history rather than the full log.

### 3.7 Calculate state changes deterministically

The language model should assess meaning and evidence. Application logic should determine whether the accumulated evidence changes canonical state.

The exact formula is an architectural decision for the coding agent, but the resulting behaviour should satisfy these principles:

- one ordinary event does not directly promote or demote an intimacy;
- higher ranks require progressively stronger and broader evidence;
- defining intimacies are highly resistant to change;
- repeated near-duplicate signals should have diminishing value;
- multiple distinct events should normally matter more than repeated evidence from one situation;
- recent momentum may be tracked separately from long-term accumulated evidence;
- exceptional, identity-shaking events may count more heavily, but should remain rare;
- promotion and demotion thresholds need not be symmetrical;
- the system should support reinforcement without forcing a rank change;
- the system should preserve contradictory evidence rather than immediately cancelling it into a context-free total.

A rolling average alone may discard useful long-term development or allow one extreme scene to dominate. A combination of long-term evidence and recent momentum may better represent gradual change, but the repository's existing state model should guide the final design.

Any deterministic update should be inspectable: it should be possible to explain which approved signals contributed to a threshold decision.

### 3.8 Apply approved mutations separately

Canonical mutations should be applied only after semantic review and deterministic calculation.

Prefer ordinary application code for:

- appending signals;
- linking signals to intimacies;
- updating accumulated state;
- creating approved candidate or canonical intimacies;
- changing ranks;
- applying wording revisions.

If the existing architecture requires an LLM to call repository tools, use a separate execution stage with no authority to reinterpret the plan. It should receive stable identifiers and explicit operations, and it should not:

- change a score or direction;
- add or remove an intimacy relationship;
- rewrite an intimacy;
- resolve ambiguity;
- substitute a different character or intimacy;
- proceed when expected versions or identifiers no longer match.

Server-side validation and transactional or version-aware updates should remain authoritative.

## 4. Suggested Scoring Semantics

A five-level ordinal scale is likely easier to use consistently than unconstrained num eric scoring.

A possible rubric is:

1. **Incidental:** The signal is relevant, but is weak evidence and should have little effect by itself.
2. **Noticeable:** The signal clearly supports or challenges the intimacy, but remains modest.
3. **Meaningful:** The event plausibly changes the character's expectation, commitment, or interpretation in a durable way.
4. **Pivotal:** The event is likely to remain salient and substantially reinforce or challenge the intimacy.
5. **Identity-shaking:** An exceptional event that plausibly bears on even a defining intimacy.

These labels are guidance rather than a required schema.

Important distinctions:

- **Strength is not dramaticness.** A loud or dangerous scene may have little relevance to a particular intimacy.
- **Strength is not emotional intensity.** A character can feel intense anger without changing a durable belief.
- **Confidence is not strength.** The evaluator may be highly confident that an effect is weak, or uncertain that an effect is strong.
- **Zero is not an affected intimacy.** Unrelated intimacies should normally be excluded from the result.
- **Scores are relationship-specific.** Do not assign one global signal strength and reuse it across all intimacies.

The prompt and evaluation suite should anchor the scale with examples from this story system. Model consistency will depend more on clear project-specific examples than on the choice between mathematically equivalent numeric representations.

## 5. New Intimacy and Rewording Behaviour

New intimacy creation is likely to remain the least deterministic part of the workflow.

The system should bias toward preserving evidence before expanding canonical state. Before proposing a new intimacy, it should ask:

1. Is this a durable interpretation or merely a current emotion?
2. Would it predict future choices?
3. Is it meaningfully distinct from every existing intimacy?
4. Could it instead be evidence for an existing intimacy?
5. Would a small wording refinement capture the development more accurately?
6. Is this better represented as a contextual qualifier, relationship-specific expression, or subordinate idea?

A new intimacy should generally begin at a conservative rank unless the event is extraordinary and the story context supports immediate formation.

Intimacy rewording should preserve continuity. The history should make clear that the wording evolved rather than making the previous intimacy appear to have vanished.

## 6. Separate Maintenance Workflow

Do not overload the per-event reviewer with global intimacy consolidation.

A separate maintenance workflow may be triggered when a character's intimacy set becomes suspiciously large or internally redundant, for example:

- too many total intimacies;
- too many major or defining intimacies;
- several intimacies with substantial semantic overlap;
- stale intimacies with no recent relevance;
- parent/child intimacies that may need clearer structure;
- repeated wording revisions that have produced conceptual drift.

That workflow may merge, split, archive, reframe, or reorganize intimacies. It should use the stored signal history so that consolidation does not erase important character-development evidence.

The exact trigger conditions and consolidation rules are outside the scope of the initial event-processing workflow.

## 7. Suggested Model Routing

Model selection should remain configurable and should be validated against a project-specific evaluation set. The following are starting candidates, not mandatory dependencies.

### Signal generation and first-pass analysis

**GLM-4.7** and **Kimi K2.6** are reasonable candidates for the per-character signal and initial matching step.

This stage needs:

- character fidelity;
- interpersonal and emotional interpretation;
- resistance to generic story conclusions;
- consistent structured output;
- enough reasoning to compare the event with existing intimacies.

It may be efficient to combine signal generation, intimacy matching, scoring, and candidate proposals in one call because they require mostly the same context. They should remain conceptually distinct in the output even if they are not separate calls.

### Structured or context-heavy evaluation

**GLM-5.2** is a candidate for systematic matching, rubric application, or context-heavy review, particularly where long character histories or many intimacy records must be considered.

It may be used as:

- the main evaluator after another model generates the signal;
- a higher-effort route for ambiguous cases;
- or a replacement for the combined first-pass model if evaluations show better end-to-end consistency.

### Consequential review

**Kimi K3** is a strong candidate for reviewing cases that could materially change canonical state, such as:

- new intimacy proposals;
- intimacy rewording;
- strength-four or strength-five effects;
- threshold crossings;
- conflicting recent evidence;
- low-confidence interpretations;
- disagreement between stages.

Running the most expensive reviewer for every routine reinforcement is probably unnecessary. Conditional routing should preserve quality where it matters without multiplying cost by every character in every scene.

### Independent arbiter

**Grok 4.5** may be useful as an optional, different-family arbiter when the primary analyzer and reviewer disagree or when a particularly consequential change needs a second perspective.

It should not be assumed to be better or worse at emotional interpretation without project-specific testing. Its value here is partly model diversity.

### Execution

Prefer deterministic application code.

If a model-based tool caller is required by the existing framework, use a lower-cost GLM or Kimi model that reliably follows strict schemas. The executor should translate an approved plan into tool calls and have no discretion over character psychology or state semantics.

### Routing principle

A likely routing shape is:

```text
Event blueprint
    ↓
Parallel per-character analysis
    ↓
Signal + affected intimacies + scored relationships + candidates
    ↓
Schema/rule validation
    ↓
Conditional high-quality review
    ↓
Deterministic accumulation and threshold evaluation
    ↓
Application code or constrained executor
    ↓
Persist signal history and approved state changes
```

The implementation may collapse or expand stages based on latency, cost, existing abstractions, and evaluation results.

## 8. Evaluation and Observability

Before committing to a model stack, create a small representative evaluation set from actual or synthetic story examples.

Include cases such as:

- a routine event that should produce no intimacy relationship;
- weak reinforcement of a minor intimacy;
- one signal affecting two intimacies in different directions;
- a dramatic event with little durable intimacy relevance;
- a temporary emotional reaction that should not create an intimacy;
- a proposed new intimacy that duplicates an existing one;
- a legitimate intimacy rewording without a rank change;
- repeated similar events that should receive diminishing weight;
- a sustained pattern that should eventually change a rank;
- an exceptional event that may challenge a defining intimacy;
- two characters interpreting the same event very differently.

Useful measures include:

- signal fidelity to the character sheet;
- distinction between characters' signals;
- missed relevant intimacies;
- spurious intimacy matches;
- score inflation;
- unnecessary new-intimacy proposals;
- reviewer correction rate;
- repeat-run consistency;
- rank-change frequency;
- frequency of defining-intimacy changes;
- latency and cost per scene and per character.

Log intermediate structured outputs in a way that supports debugging and prompt/model comparison. Avoid relying only on the final intimacy state, since many failures will originate in a reasonable-looking but incorrect signal or relationship judgment.

## 9. Integration Guidance

The coding agent should inspect the repository before choosing:

- whether this is one workflow with internal stages or several workflows;
- whether model calls are implemented as agents, jobs, nodes, or services;
- how character context and scene history are retrieved;
- where signal history belongs in the current data model;
- how state transition logic fits existing intimacy strength representations;
- whether candidate intimacies require a new state;
- how parallel character runs are synchronized and committed;
- how retries, model failures, schema failures, and partial scene results are handled;
- how existing event-blueprint signals should be migrated or retained;
- how the workflow is feature-flagged or rolled out safely.

Prefer reuse of existing IDs, persistence patterns, schemas, tool abstractions, and orchestration conventions over introducing a parallel architecture solely to match this document.

Where possible, preserve backward compatibility long enough to compare the new workflow with the current direct-mutation behaviour.

## 10. Desired Behavioural Outcome

When complete, the system should behave as though it is asking:

> What did this event mean to this particular character, what durable beliefs did that meaning bear upon, and has enough distinct evidence accumulated to justify changing canonical character state?

It should not behave as though it is asking:

> Which intimacy should this scene change?

Most scenes should produce useful evidence without changing an intimacy's rank. Over time, the stored signal history should make character development more gradual, explainable, distinctive, and available to future writing agents.
