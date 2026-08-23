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
* Parallel prose reviewers (extends the single prose review): The workflow already has a bounded
  plan review/revise loop (stances + outline) and a single prose review/revise loop after drafting.
  Extend the prose review step into multiple parallel reviewers, each producing a critique focused
  on a different aspect, then merge into one revise pass:
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
* Event relationships (remaining): Arc membership and a per-character perspective timeline view
  (events a character signals, in order). Typed ordering relationships
  (`follows`, `directly_follows`, `depends_on`, `during`) are implemented; see
  [story_bible_model.md](story_bible_model.md). Scene-to-event linking exists as scene-local
  blueprint links (`event_ids` / `related_event_ids`); the scene-writing workflow uses those
  links (plus event chronology) to select neighboring scenes for continuity context. A "related"
  link is the interim stand-in for an explicit relevance relation between events.
* Scene workflow blueprint-only continuity: Unwritten neighbors currently fall back to blueprint
  fields when prose or summary is missing. Longer term, improve the workflow so blueprints alone
  can reliably serve as continuity context even after scenes are written.

## Intimacy review workflow (superseded)

The description-based intimacy review workflow formerly designed in this section (originally
Phase 6c of the phased plan) has been **superseded** by the evidence-based intimacy system
decided in the 2026-08-21 project review. The authoritative design now lives in
[story_bible_model.md](story_bible_model.md) ("Evidence-Based Intimacy State" — evidence data
model, derived rank, replay semantics) and
[architecture_agent_workflows.md](architecture_agent_workflows.md) ("Intimacy Interpretation
Workflow"); implementation is tracked in the "Evidence-Based Intimacy System" Linear project.
The pipeline is fully wired: event authoring triggers per-character interpretation jobs
through `JobManager`, reviewed results persist through the deterministic apply stage, and
agents no longer author intimacy effects directly — signals passed to the event tools are
hints to the workflow (see [architecture_agent_workflows.md](architecture_agent_workflows.md)).

A separate maintenance/consolidation workflow (merge, split, archive intimacies using the
stored evidence history) remains future work, out of scope for the interpretation pipeline.

## Plot editor agent

A planned agent that closes the feedback loop between plot planning and the evidence-based
intimacy system. Today the intimacy pipeline is purely interpretive (events in, evidence and
derived rank out); there is no mechanism that answers "what events would produce the character
arc I want?". The plot editor agent would iterate: author or adjust an event, run the
interpretation workflow, inspect the resulting evidence and distance-to-threshold, and tweak
until the arc plays out as intended. This is deliberately a separate project *after* the
evidence-based intimacy system stabilizes; the intimacy work accommodates it cheaply by making
the accumulator a pure what-if oracle that exposes distance-to-threshold, and by keeping the
interpretation run's entry point UI-independent (see
[story_bible_model.md](story_bible_model.md) and
[architecture_agent_workflows.md](architecture_agent_workflows.md)).

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
