"""Process-wide async job tracking with resource claims and a scene queue."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from langchain_core.messages import AIMessageChunk, BaseMessageChunk

from app.graphs.intimacy_interpretation import NO_RELEVANT_CHARACTERS_MESSAGE
from app.persistence import ChatConversation, get_chat_conversation
from app.world.scene import resolve_scene, set_scene_text

JobKind = Literal["scene_generation", "chat_turn", "intimacy_interpretation"]
JobStatus = Literal["running", "finished", "failed"]
QueueStatus = Literal["pending", "running", "finished", "failed", "blocked"]

CHAT_CLAIM = "chat"
MAX_PARALLEL_SCENE_GENERATIONS = 3


def scene_claim_key(scene_id: str) -> str:
    """Return the resource claim key for a scene."""

    return f"scene:{scene_id}"


def intimacy_claim_key(event_id: str, character_id: str) -> str:
    """Return the resource claim key for one character-event interpretation."""

    return f"intimacy:{event_id}:{character_id}"


@dataclass
class ChatLive:
    """Streaming state for an in-flight chat turn."""

    version: int = 0
    assistant_text: str = ""
    run_scene_id: str = ""
    start_scene_id: str = ""
    stream_failed: bool = False
    error: str | None = None
    pending_navigation_scene_id: str = ""

    def bump(self, **updates: Any) -> None:
        for key, value in updates.items():
            setattr(self, key, value)
        self.version += 1


@dataclass
class SceneGenerationLive:
    """Streaming state for scene generation (reserved for future step labels)."""

    version: int = 0
    step: str = ""


@dataclass
class IntimacyInterpretationLive:
    """Streaming state for a per-character intimacy interpretation job."""

    version: int = 0
    event_id: str = ""
    character_id: str = ""


@dataclass
class EventInterpretationStatus:
    """UI-facing status for intimacy jobs on one event."""

    running_character_ids: list[str] = field(default_factory=list)
    last_errors: dict[str, str] = field(default_factory=dict)
    empty_reason: str | None = None
    finished_character_ids: list[str] = field(default_factory=list)


@dataclass
class Job:
    """In-memory record for one background job."""

    id: str
    kind: JobKind
    label: str
    claims: list[str]
    status: JobStatus = "running"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    error: str | None = None
    cancel_requested: bool = False
    live: ChatLive | SceneGenerationLive | IntimacyInterpretationLive = field(
        default_factory=ChatLive
    )


@dataclass
class QueuedScene:
    """One scene generation slot in the dependency-aware work queue."""

    id: str
    scene_id: str
    label: str
    prerequisite_scene_ids: list[str]
    status: QueueStatus = "pending"
    job_id: str | None = None
    error: str | None = None
    max_revisions: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None


_JOB_MANAGER: JobManager | None = None


class JobManager:
    """Thread-safe registry for background jobs, resource claims, and a scene queue."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._claim_index: dict[str, str] = {}
        self._queue: list[QueuedScene] = []
        self._chat_task: asyncio.Task[None] | None = None
        self._event_notes: dict[str, str] = {}

    def start_scene_generation(self, scene_id: str, *, max_revisions: int = 1) -> Job:
        """Start scene generation in a background thread with a scene claim."""

        with self._lock:
            job, thread_args = self._prepare_scene_generation_unlocked(
                scene_id,
                max_revisions=max_revisions,
            )
        thread = threading.Thread(
            target=self._run_scene_generation,
            args=thread_args,
            name=f"scene-gen-{scene_id}",
            daemon=True,
        )
        thread.start()
        return job

    def queue_scene_generations(
        self,
        items: Sequence[tuple[str, str, Sequence[str]]],
        *,
        max_revisions: int = 1,
    ) -> list[QueuedScene]:
        """Enqueue selected scenes with prerequisites filtered to the selection.

        Each item is ``(scene_id, label, prerequisite_scene_ids)``. Prerequisites that
        are not in the selected set are treated as already satisfied.
        """

        selected_ids = {scene_id for scene_id, _label, _prereqs in items}
        queued: list[QueuedScene] = []
        with self._lock:
            for scene_id, label, prerequisite_scene_ids in items:
                filtered = [
                    prereq_id
                    for prereq_id in prerequisite_scene_ids
                    if prereq_id in selected_ids and prereq_id != scene_id
                ]
                item = QueuedScene(
                    id=str(uuid.uuid4()),
                    scene_id=scene_id,
                    label=label,
                    prerequisite_scene_ids=filtered,
                    max_revisions=max_revisions,
                )
                self._queue.append(item)
                queued.append(item)
        self._schedule_queue()
        return queued

    def queued_items(self) -> list[QueuedScene]:
        """Return all queue items (pending through finished/blocked)."""

        with self._lock:
            return list(self._queue)

    def active_queue_items(self) -> list[QueuedScene]:
        """Return queue items that are still waiting or running."""

        with self._lock:
            return [item for item in self._queue if item.status in ("pending", "running")]

    def active_work_count(self) -> int:
        """Return running jobs plus pending queued scenes (for the header badge)."""

        with self._lock:
            running = sum(1 for job in self._jobs.values() if job.status == "running")
            pending = sum(1 for item in self._queue if item.status == "pending")
            return running + pending

    def is_generating(self, scene_id: str) -> bool:
        """Return True when a generation job claims ``scene_id``."""

        return self.claim_for(scene_claim_key(scene_id)) is not None

    def last_error(self, scene_id: str) -> str | None:
        """Return the last failed generation error for ``scene_id``, if any."""

        with self._lock:
            for job in reversed(list(self._jobs.values())):
                if job.kind != "scene_generation":
                    continue
                if scene_claim_key(scene_id) not in job.claims:
                    continue
                if job.status == "failed":
                    return job.error
                if job.status in ("running", "finished"):
                    return None
            return None

    def start_intimacy_interpretation(
        self,
        event_id: str,
        character_id: str,
        *,
        models: dict[str, Any] | None = None,
    ) -> Job:
        """Start a per-character interpretation job with an intimacy claim."""

        with self._lock:
            job, thread_args = self._prepare_intimacy_interpretation_unlocked(
                event_id,
                character_id,
                models=models,
            )
        thread = threading.Thread(
            target=self._run_intimacy_interpretation,
            args=thread_args,
            name=f"intimacy-{event_id}-{character_id}",
            daemon=True,
        )
        thread.start()
        return job

    def start_event_interpretation(
        self,
        event_id: str,
        *,
        character_ids: Sequence[str] | None = None,
        models: dict[str, Any] | None = None,
    ) -> list[Job]:
        """Fan out parallel interpretation jobs for an event's relevant characters.

        When the relevant set is empty, no jobs start and
        ``event_interpretation_status`` exposes ``NO_RELEVANT_CHARACTERS_MESSAGE``.
        A character already being interpreted is skipped rather than raising.
        """

        from app.graphs.intimacy_interpretation import relevant_character_ids
        from app.world.store import get_world

        world = get_world()
        if world.story_bible.get_event(event_id) is None:
            msg = f"Event not found: {event_id}"
            raise ValueError(msg)

        if character_ids is None:
            ids = relevant_character_ids(world, event_id)
        else:
            ids = [
                character_id
                for character_id in character_ids
                if world.story_bible.get_character(character_id) is not None
            ]

        with self._lock:
            if not ids:
                self._event_notes[event_id] = NO_RELEVANT_CHARACTERS_MESSAGE
                return []
            self._event_notes.pop(event_id, None)

        jobs: list[Job] = []
        for character_id in ids:
            try:
                jobs.append(
                    self.start_intimacy_interpretation(event_id, character_id, models=models)
                )
            except RuntimeError:
                continue
        return jobs

    def is_interpreting(self, event_id: str, character_id: str | None = None) -> bool:
        """Return True when an interpretation job claims this event (or pair)."""

        if character_id is not None:
            return self.claim_for(intimacy_claim_key(event_id, character_id)) is not None
        prefix = f"intimacy:{event_id}:"
        with self._lock:
            return any(
                claim.startswith(prefix) and self._jobs.get(job_id) is not None
                for claim, job_id in self._claim_index.items()
            )

    def last_interpretation_error(
        self,
        event_id: str,
        character_id: str | None = None,
    ) -> str | None:
        """Return the latest failed interpretation error for the event or pair."""

        with self._lock:
            for job in reversed(list(self._jobs.values())):
                if job.kind != "intimacy_interpretation":
                    continue
                if not self._job_matches_event(job, event_id, character_id):
                    continue
                if job.status == "failed":
                    return job.error
                if job.status in ("running", "finished"):
                    return None
            return None

    def event_interpretation_status(self, event_id: str) -> EventInterpretationStatus:
        """Summarize running, finished, and failed interpretation jobs for an event."""

        with self._lock:
            running: list[str] = []
            finished: list[str] = []
            errors: dict[str, str] = {}
            latest_by_character: dict[str, Job] = {}
            for job in self._jobs.values():
                if job.kind != "intimacy_interpretation":
                    continue
                character_id = self._character_id_from_job(job, event_id)
                if character_id is None:
                    continue
                previous = latest_by_character.get(character_id)
                if previous is None or job.created_at >= previous.created_at:
                    latest_by_character[character_id] = job
            for character_id, job in latest_by_character.items():
                if job.status == "running":
                    running.append(character_id)
                elif job.status == "failed" and job.error:
                    errors[character_id] = job.error
                elif job.status == "finished":
                    finished.append(character_id)
            empty_reason = (
                None if running or latest_by_character else self._event_notes.get(event_id)
            )
            return EventInterpretationStatus(
                running_character_ids=running,
                last_errors=errors,
                empty_reason=empty_reason,
                finished_character_ids=finished,
            )

    def scene_is_claimed(self, scene_id: str) -> bool:
        """Return True when any running job claims ``scene_id``."""

        return self.claim_for(scene_claim_key(scene_id)) is not None

    def chat_is_claimed(self) -> bool:
        """Return True when a chat turn job is running."""

        return self.claim_for(CHAT_CLAIM) is not None

    def claim_for(self, resource: str) -> Job | None:
        """Return the running job that holds ``resource``, if any."""

        with self._lock:
            job_id = self._claim_index.get(resource)
            if job_id is None:
                return None
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return None
            return job

    def get_job(self, job_id: str) -> Job | None:
        """Return a job by id."""

        with self._lock:
            return self._jobs.get(job_id)

    def active_chat_job(self) -> Job | None:
        """Return the running chat job, if any."""

        return self.claim_for(CHAT_CLAIM)

    def running_jobs(self) -> list[Job]:
        """Return all currently running jobs."""

        with self._lock:
            return [job for job in self._jobs.values() if job.status == "running"]

    def finished_jobs(self) -> list[Job]:
        """Return jobs that have completed (success or failure)."""

        with self._lock:
            return [job for job in self._jobs.values() if job.status in ("finished", "failed")]

    def start_chat_turn(
        self,
        user_text: str,
        conversation: ChatConversation | None = None,
    ) -> Job:
        """Start a chat turn as a manager-owned asyncio task with a chat claim."""

        conversation = conversation or get_chat_conversation()
        with self._lock:
            if CHAT_CLAIM in self._claim_index:
                msg = "A chat response is already in progress"
                raise RuntimeError(msg)

            start_scene = resolve_scene()
            start_scene_id = start_scene.id if start_scene is not None else ""
            live = ChatLive(
                run_scene_id=start_scene_id,
                start_scene_id=start_scene_id,
            )
            job = Job(
                id=str(uuid.uuid4()),
                kind="chat_turn",
                label="Agent reply",
                claims=[CHAT_CLAIM],
                live=live,
            )
            self._register_job(job)

        try:
            conversation.add_user_message(user_text)
            loop = asyncio.get_running_loop()
            self._chat_task = loop.create_task(
                self._run_chat_turn(job.id, conversation),
                name=f"chat-turn-{job.id[:8]}",
            )
        except Exception as exc:
            self._finish_job(job.id, status="failed", error=str(exc))
            raise
        return job

    def _register_job(self, job: Job) -> None:
        self._jobs[job.id] = job
        for claim in job.claims:
            self._claim_index[claim] = job.id

    def _prepare_scene_generation_unlocked(
        self,
        scene_id: str,
        *,
        max_revisions: int = 1,
    ) -> tuple[Job, tuple[str, str, int]]:
        claim = scene_claim_key(scene_id)
        if claim in self._claim_index:
            msg = f"Generation already running for scene {scene_id}"
            raise RuntimeError(msg)

        from app.world.store import get_world

        world = get_world()
        scene = world.get_scene(scene_id)
        scene_title = scene.title if scene is not None else scene_id
        job = Job(
            id=str(uuid.uuid4()),
            kind="scene_generation",
            label=f"Scene '{scene_title or 'Untitled'}'",
            claims=[claim],
            live=SceneGenerationLive(),
        )
        self._register_job(job)
        return job, (job.id, scene_id, max_revisions)

    def _prepare_intimacy_interpretation_unlocked(
        self,
        event_id: str,
        character_id: str,
        *,
        models: dict[str, Any] | None = None,
    ) -> tuple[Job, tuple[str, str, str, dict[str, Any] | None]]:
        claim = intimacy_claim_key(event_id, character_id)
        if claim in self._claim_index:
            msg = f"Interpretation already running for event {event_id} character {character_id}"
            raise RuntimeError(msg)

        from app.world.store import get_world

        world = get_world()
        event = world.story_bible.get_event(event_id)
        character = world.story_bible.get_character(character_id)
        event_title = event.title if event is not None else event_id
        character_name = character.identity.name if character is not None else character_id
        job = Job(
            id=str(uuid.uuid4()),
            kind="intimacy_interpretation",
            label=f"Intimacy: '{event_title or 'Untitled'}' / {character_name or 'Unnamed'}",
            claims=[claim],
            live=IntimacyInterpretationLive(event_id=event_id, character_id=character_id),
        )
        self._register_job(job)
        return job, (job.id, event_id, character_id, models)

    def _run_intimacy_interpretation(
        self,
        job_id: str,
        event_id: str,
        character_id: str,
        models: dict[str, Any] | None,
    ) -> None:
        from app.graphs.intimacy_interpretation import run_and_apply_intimacy_interpretation

        try:
            run_and_apply_intimacy_interpretation(event_id, character_id, models=models)
        except Exception as exc:
            self._finish_job(job_id, status="failed", error=str(exc))
        else:
            self._finish_job(job_id, status="finished")

    def _job_matches_event(
        self,
        job: Job,
        event_id: str,
        character_id: str | None,
    ) -> bool:
        if character_id is not None:
            return intimacy_claim_key(event_id, character_id) in job.claims
        prefix = f"intimacy:{event_id}:"
        return any(claim.startswith(prefix) for claim in job.claims)

    def _character_id_from_job(self, job: Job, event_id: str) -> str | None:
        prefix = f"intimacy:{event_id}:"
        for claim in job.claims:
            if claim.startswith(prefix):
                return claim[len(prefix) :]
        if isinstance(job.live, IntimacyInterpretationLive) and job.live.event_id == event_id:
            return job.live.character_id
        return None

    def _finish_job(self, job_id: str, *, status: JobStatus, error: str | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status
            job.finished_at = datetime.now(timezone.utc)
            job.error = error
            if status != "running":
                for claim in job.claims:
                    if self._claim_index.get(claim) == job_id:
                        self._claim_index.pop(claim, None)
            self._sync_queue_item_unlocked(job)

    def _sync_queue_item_unlocked(self, job: Job) -> None:
        if job.kind != "scene_generation" or job.status == "running":
            return
        now = datetime.now(timezone.utc)
        for item in self._queue:
            if item.job_id != job.id:
                continue
            item.status = "failed" if job.status == "failed" else "finished"
            item.error = job.error
            item.finished_at = now

    def _latest_queue_by_scene_unlocked(self) -> dict[str, QueuedScene]:
        latest: dict[str, QueuedScene] = {}
        for queued in self._queue:
            latest[queued.scene_id] = queued
        return latest

    def _prerequisites_satisfied_unlocked(self, item: QueuedScene) -> bool:
        latest = self._latest_queue_by_scene_unlocked()
        for prereq_id in item.prerequisite_scene_ids:
            prereq = latest.get(prereq_id)
            if prereq is None:
                continue
            if prereq.status != "finished":
                return False
        return True

    def _propagate_blocked_unlocked(self) -> None:
        latest = self._latest_queue_by_scene_unlocked()
        changed = True
        while changed:
            changed = False
            for item in self._queue:
                if item.status != "pending":
                    continue
                for prereq_id in item.prerequisite_scene_ids:
                    prereq = latest.get(prereq_id)
                    if prereq is None:
                        continue
                    if prereq.status in ("failed", "blocked"):
                        item.status = "blocked"
                        item.error = f"Blocked by prerequisite: {prereq.label}"
                        item.finished_at = datetime.now(timezone.utc)
                        changed = True
                        break

    def _schedule_queue(self) -> None:
        """Start every ready pending scene up to the parallel generation cap."""

        while True:
            prepared: list[tuple[str, str, int]] = []
            with self._lock:
                self._propagate_blocked_unlocked()
                running_count = sum(
                    1
                    for job in self._jobs.values()
                    if job.status == "running" and job.kind == "scene_generation"
                )
                slots = MAX_PARALLEL_SCENE_GENERATIONS - running_count
                if slots <= 0:
                    return

                for item in self._queue:
                    if slots <= 0:
                        break
                    if item.status != "pending":
                        continue
                    if not self._prerequisites_satisfied_unlocked(item):
                        continue
                    claim = scene_claim_key(item.scene_id)
                    if claim in self._claim_index:
                        continue
                    try:
                        job, thread_args = self._prepare_scene_generation_unlocked(
                            item.scene_id,
                            max_revisions=item.max_revisions,
                        )
                    except RuntimeError:
                        continue
                    item.status = "running"
                    item.job_id = job.id
                    prepared.append(thread_args)
                    slots -= 1

            if not prepared:
                return

            for job_id, scene_id, max_revisions in prepared:
                thread = threading.Thread(
                    target=self._run_scene_generation,
                    args=(job_id, scene_id, max_revisions),
                    name=f"scene-gen-{scene_id}",
                    daemon=True,
                )
                thread.start()

    def _run_scene_generation(self, job_id: str, scene_id: str, max_revisions: int) -> None:
        from app.graphs.scene_generation import run_scene_generation

        try:
            run_scene_generation(scene_id, max_revisions=max_revisions)
        except Exception as exc:
            self._finish_job(job_id, status="failed", error=str(exc))
        else:
            self._finish_job(job_id, status="finished")
        self._schedule_queue()

    async def _run_chat_turn(self, job_id: str, conversation: ChatConversation) -> None:
        job = self.get_job(job_id)
        if job is None or not isinstance(job.live, ChatLive):
            return

        live = job.live
        assistant_text = ""
        run_scene_id = live.run_scene_id
        stream_failed = False
        try:
            from app.graphs import get_chat_agent

            messages = conversation.agent_messages()
            async for stream_name, payload in get_chat_agent().astream(
                {
                    "messages": messages,
                    "current_scene": _current_scene_markdown(run_scene_id),
                    "current_scene_id": run_scene_id,
                },
                stream_mode=["messages", "updates"],
            ):
                if stream_name == "updates":
                    run_scene_id = _scene_id_from_stream_payload(payload, run_scene_id)
                    live.bump(run_scene_id=run_scene_id)
                    continue
                if stream_name != "messages":
                    continue

                token, _metadata = payload
                content = _token_text(token)
                if not content:
                    continue
                assistant_text = _append_streamed_text(assistant_text, content)
                live.bump(assistant_text=assistant_text)

            if assistant_text and not stream_failed:
                conversation.add_assistant_message(assistant_text)

            pending_navigation = ""
            if run_scene_id and run_scene_id != live.start_scene_id:
                pending_navigation = run_scene_id

            live.bump(pending_navigation_scene_id=pending_navigation)
            self._finish_job(job_id, status="finished")
        except Exception as exc:
            stream_failed = True
            error_text = f"Chat agent error: {exc}"
            live.bump(stream_failed=True, error=error_text, assistant_text=error_text)
            self._finish_job(job_id, status="failed", error=error_text)


def get_job_manager() -> JobManager:
    """Return the process-local job manager singleton."""

    global _JOB_MANAGER
    if _JOB_MANAGER is None:
        _JOB_MANAGER = JobManager()
    return _JOB_MANAGER


def reset_job_manager() -> None:
    """Clear the singleton (for tests)."""

    global _JOB_MANAGER
    _JOB_MANAGER = None


def _current_scene_markdown(scene_id: str) -> str:
    if not scene_id:
        return ""
    from app.world.store import get_world

    scene = get_world().get_scene(scene_id)
    return scene.markdown if scene is not None else ""


def _token_text(token: BaseMessageChunk | Any) -> str:
    if not isinstance(token, AIMessageChunk):
        return ""
    content = getattr(token, "content", "")
    return content if isinstance(content, str) else ""


def _append_streamed_text(assistant_text: str, content: str) -> str:
    if not content:
        return assistant_text
    if not assistant_text:
        content = content.lstrip()
        if not content:
            return assistant_text
    return assistant_text + content


def _scene_id_from_stream_payload(
    payload: Any,
    current_id: str,
    scene_setter: Callable[[str, str], None] = set_scene_text,
) -> str:
    if not isinstance(payload, dict):
        return current_id

    for node_updates in payload.values():
        if not isinstance(node_updates, dict):
            continue
        new_id = node_updates.get("current_scene_id")
        if isinstance(new_id, str) and new_id:
            current_id = new_id
        new_scene = node_updates.get("current_scene")
        if isinstance(new_scene, str):
            scene_setter(current_id, new_scene)
    return current_id
