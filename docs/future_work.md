# Future Enhancements

Planned enhancements that are out of scope for the current phased implementation plan but
worth preserving. These are not committed to a specific phase yet.

* Modify Chat History: Delete/modify messages in the chat history.
* Multiple Conversations: Persist more than the current conversation and allow switching between them.
* CI Pipeline: Once the repo has a remote (e.g. GitHub), add a CI workflow that runs
  `poetry run ruff check .` and `poetry run pytest` on every push/PR so verification no longer
  depends on local discipline alone.

## Scene workflow rework

* Copy scene before regenerate: When regenerating a stale scene, offer an option to duplicate the
  existing scene (blueprint, generated artifacts, and prose) to a new scene before discarding content
  on regenerate.
* Scene review (replaces the outline review): Replace the current `review_outline` /
  `revise_outline` step with a review of the *finished* scene. After the user kicks off the
  workflow from a proposed scene, the final scene is reviewed in parallel by multiple reviewers,
  each producing a critique focused on a different aspect:
  * Continuity reviewer: flags significant details the scene added that are not already in the
    story bible (these should be removed, or — eventually — proposed as additions to the world),
    and inconsistencies between the scene and the story bible.
  * Quality reviewer: suggests improvements.
  * Reviewers can see the scene card, the outline, and the scene, and should point out the
    *earliest* stage where an issue was introduced. If the scene card contradicts the story
    bible, that gets surfaced in the UI rather than triggering a rewrite; if a continuity error
    is present in the outline as well as the scene, the reviewer suggests fixing the outline and
    the scene so earlier stages are corrected when the scene is rewritten.

## Relationship tracking

* Character relationships: Track relationships between characters (e.g. "know each other",
  "husband and wife", "work together"). Open question: model these as fields on character
  identities or as a separate relationships table. A separate table would be easier to migrate
  to a graph database if relationships grow complex, though that is not needed yet.
* Event relationships (remaining): Causality edges (`causes`), arc membership, and a per-character
  perspective timeline view (events a character signals, in order). Typed ordering relationships
  (`follows`, `directly_follows`, `during`) are implemented; see
  [story_bible_model.md](story_bible_model.md). Scene-to-event linking now exists as scene-local
  blueprint links (`event_ids` / `related_event_ids`); making workflows select relevant neighboring
  scenes by those links (rather than list adjacency) is the remaining follow-up. A "related" link is
  the interim stand-in for an explicit relevance relation between events.

## Intimacy review workflow

Originally Phase 6c of the phased plan. Build the intimacy reviewer as an enforced LangGraph
workflow exposed to the main agent as a single tool, following the cross-cutting workflow pattern
in [architecture_agent_workflows.md](architecture_agent_workflows.md). This section is the
authoritative design for the workflow until it is built; until then, agents author intimacy effects
through the direct structured operations described in
[story_bible_model.md](story_bible_model.md).

Gates every agent-driven intimacy change behind a retrieval-and-review pipeline so new intimacies
stay well-formed and continuity-safe. This is the highest-leverage continuity guard: intimacy
edits are where a careless change silently corrupts a character.

### Why a workflow, not a subagent

The Story Bible is small, so retrieval is a direct lookup (the character's current intimacies at
the relevant timeline position plus relevant world facts) rather than a vector store, and review
is a single deterministic LLM step. A focused workflow graph is cheaper and more predictable than
a full subagent, and it composes with the existing per-call transaction.

### Description-based tool surface

The agent does not author intimacy effects directly. It describes the intended change in natural
language; the workflow produces the concrete structured effects. This flips the failure mode from
"I asked for X but the agent emitted effects Y" to "I asked for X, and here is the diff (Y) that
implements it."

- **Event signals** (mid-story changes): the agent supplies an interpretation plus a change
  description for the signal; the workflow fills in that signal's effects.
- **Baseline intimacies**: the agent describes the desired baseline; the workflow authors/edits
  the baseline intimacy list.
- The structured effect operations (`add_intimacy`, `set_intimacy_strength`, `update_intimacy`,
  `remove_intimacy`) remain the underlying data model and stay directly editable in the Story
  Bible forms. Only the agent's authoring path changes. World-state effects keep their direct CRUD
  authoring.

### Nodes (enforced order)

1. **Retrieve** — gather the character's current intimacies at the relevant timeline position plus
   relevant world facts, to ground the proposal and review.
2. **Propose** — convert the natural-language change description into specific structured effects.
3. **Review** — enforce simple first-person statements, merge duplicates, prefer strengthening an
   existing intimacy over adding a near-duplicate, and prefer small cumulative changes. Review may
   rewrite a proposed effect (for example, turn a duplicate `add_intimacy` into a
   `set_intimacy_strength` or drop it), so the applied effects can differ from the literal
   proposal.
4. **Apply** — write the reviewed effects to their target (a signal's effects or the baseline
   list) and return a human-readable diff.

### Approval

The workflow auto-applies reviewed changes and returns the diff. Human approval of the diff depends
on the tool-confirmations item under "Chat & tool UX polish" below, which layers a
confirmation/diff step on top without changing this workflow.

### Testing

Unit tests for the workflow nodes and the description-based intimacy tool(s).

## User context notes

Originally Phase 7 of the phased plan.

* Current Page Context: Add a note to each user message describing the user's currently open page
  or focused content.
* Initial Story Bible Summary: Include an initial Story Bible summary in the user message note so
  the agent starts with basic world context.
* Context Tests: Add tests for user message note generation.

## Chat & tool UX polish

Originally Phase 8 of the phased plan.

* Tool-Call Display: Render tool calls clearly in the chat history.
* Tool Confirmations: Add tool confirmations to the chat window, including diffs where agent tools
  edit scene Markdown or Story Bible data.
* Stop/Cancel: Add controls to stop or cancel in-flight agent and sub-agent runs. `JobManager`
  records a `cancel_requested` flag on each job; wiring cancellation into the scene workflow
  (between nodes) and chat stream (between chunks) is deferred — see
  [architecture_async_jobs.md](architecture_async_jobs.md).
* Jobs page: A top-level page listing all jobs with status and cancel becomes trivial once
  `JobManager` exists; the header running-jobs indicator covers visibility for now.
