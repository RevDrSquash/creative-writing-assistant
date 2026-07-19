"""Tests for JobManager lifecycle, claims, and chat job behavior."""

from __future__ import annotations

import asyncio
import importlib
import threading
import time
from typing import Any

import pytest
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import ToolException

from app.graphs.jobs import (
    CHAT_CLAIM,
    JobManager,
    reset_job_manager,
    scene_claim_key,
)
from app.persistence import ChatConversation, JsonFileChatMessageStore
from app.tools.scene import update_scene_blueprint


def _graphs_module():
    return importlib.import_module("app.graphs")


def _scene_generation_module():
    return importlib.import_module("app.graphs.scene_generation")


@pytest.fixture(autouse=True)
def _reset_jobs() -> None:
    reset_job_manager()
    yield
    reset_job_manager()


def test_scene_claim_key_format() -> None:
    assert scene_claim_key("scene_a") == "scene:scene_a"


def test_start_scene_generation_claims_scene(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()
    started: list[str] = []

    def slow_run(scene_id: str, *, max_revisions: int = 1) -> None:
        started.append(scene_id)
        time.sleep(0.05)

    monkeypatch.setattr(_scene_generation_module(), "run_scene_generation", slow_run)
    job = manager.start_scene_generation("scene_a")
    assert job.kind == "scene_generation"
    assert scene_claim_key("scene_a") in job.claims
    assert manager.is_generating("scene_a")
    assert manager.claim_for(scene_claim_key("scene_a")) is job
    assert started == ["scene_a"]

    deadline = time.time() + 2
    while manager.is_generating("scene_a") and time.time() < deadline:
        time.sleep(0.01)
    assert manager.is_generating("scene_a") is False


def test_start_scene_generation_rejects_concurrent(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()

    def slow_run(scene_id: str, *, max_revisions: int = 1) -> None:
        time.sleep(0.05)

    monkeypatch.setattr(_scene_generation_module(), "run_scene_generation", slow_run)
    manager.start_scene_generation("scene_a")
    with pytest.raises(RuntimeError, match="already running"):
        manager.start_scene_generation("scene_a")


def test_last_error_clears_after_successful_regeneration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = JobManager()
    outcomes = iter([RuntimeError("first failure"), None])

    def alternating_run(scene_id: str, *, max_revisions: int = 1) -> None:
        exc = next(outcomes)
        if exc is not None:
            raise exc

    monkeypatch.setattr(_scene_generation_module(), "run_scene_generation", alternating_run)
    manager.start_scene_generation("scene_c")

    deadline = time.time() + 2
    while manager.is_generating("scene_c") and time.time() < deadline:
        time.sleep(0.01)
    assert manager.last_error("scene_c") == "first failure"

    manager.start_scene_generation("scene_c")
    deadline = time.time() + 2
    while manager.is_generating("scene_c") and time.time() < deadline:
        time.sleep(0.01)
    assert manager.last_error("scene_c") is None


def test_scene_generation_captures_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()

    def failing_run(scene_id: str, *, max_revisions: int = 1) -> None:
        msg = "workflow exploded"
        raise RuntimeError(msg)

    monkeypatch.setattr(_scene_generation_module(), "run_scene_generation", failing_run)
    manager.start_scene_generation("scene_b")

    deadline = time.time() + 2
    while manager.is_generating("scene_b") and time.time() < deadline:
        time.sleep(0.01)

    assert manager.last_error("scene_b") == "workflow exploded"
    finished = manager.finished_jobs()
    assert any(
        job.claims == [scene_claim_key("scene_b")] and job.status == "failed" for job in finished
    )


def test_chat_claim_blocks_second_start(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    async def run() -> None:
        manager = JobManager()
        conversation = ChatConversation(JsonFileChatMessageStore(tmp_path / "chat_history.json"))

        async def fake_astream(*args: Any, **kwargs: Any):
            yield "messages", (AIMessageChunk(content="Hi"), {})
            await asyncio.sleep(0.05)

        class FakeAgent:
            astream = staticmethod(fake_astream)

        monkeypatch.setattr(_graphs_module(), "get_chat_agent", lambda: FakeAgent())
        job = manager.start_chat_turn("Hello", conversation)
        assert manager.chat_is_claimed()
        assert manager.claim_for(CHAT_CLAIM) is job

        with pytest.raises(RuntimeError, match="already in progress"):
            manager.start_chat_turn("Again", conversation)

    asyncio.run(run())


async def test_chat_turn_persists_assistant_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    manager = JobManager()
    conversation = ChatConversation(JsonFileChatMessageStore(tmp_path / "chat_history.json"))

    async def fake_astream(*args: Any, **kwargs: Any):
        yield "messages", (AIMessageChunk(content="Reply text"), {})

    class FakeAgent:
        astream = staticmethod(fake_astream)

    monkeypatch.setattr(_graphs_module(), "get_chat_agent", lambda: FakeAgent())
    manager.start_chat_turn("Question", conversation)

    deadline = time.time() + 2
    while manager.chat_is_claimed() and time.time() < deadline:
        await asyncio.sleep(0.01)

    history = conversation.history()
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Reply text"


async def test_chat_turn_releases_claim_when_assistant_persist_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    manager = JobManager()
    conversation = ChatConversation(JsonFileChatMessageStore(tmp_path / "chat_history.json"))

    async def fake_astream(*args: Any, **kwargs: Any):
        yield "messages", (AIMessageChunk(content="Reply text"), {})

    class FakeAgent:
        astream = staticmethod(fake_astream)

    def failing_add_assistant(text: str):
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(_graphs_module(), "get_chat_agent", lambda: FakeAgent())
    monkeypatch.setattr(conversation, "add_assistant_message", failing_add_assistant)
    manager.start_chat_turn("Question", conversation)

    deadline = time.time() + 2
    while manager.chat_is_claimed() and time.time() < deadline:
        await asyncio.sleep(0.01)

    assert manager.chat_is_claimed() is False
    finished = manager.finished_jobs()
    assert any(job.kind == "chat_turn" and job.status == "failed" for job in finished)


def test_start_chat_turn_releases_claim_when_user_persist_fails(tmp_path) -> None:
    async def run() -> None:
        manager = JobManager()
        conversation = ChatConversation(JsonFileChatMessageStore(tmp_path / "chat_history.json"))

        def failing_add_user(text: str):
            msg = "disk full"
            raise OSError(msg)

        conversation.add_user_message = failing_add_user  # type: ignore[method-assign]

        with pytest.raises(OSError, match="disk full"):
            manager.start_chat_turn("Hello", conversation)

        assert manager.chat_is_claimed() is False
        finished = manager.finished_jobs()
        assert any(job.kind == "chat_turn" and job.status == "failed" for job in finished)

    asyncio.run(run())


def test_update_scene_blueprint_rejects_claimed_scene(
    world_with_scene,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs_module = importlib.import_module("app.graphs.jobs")
    jobs_module.reset_job_manager()
    manager = jobs_module.JobManager()
    scene_id = world_with_scene.scenes[0].id

    def slow_run(sid: str, *, max_revisions: int = 1) -> None:
        time.sleep(0.2)

    monkeypatch.setattr(jobs_module, "get_job_manager", lambda: manager)
    monkeypatch.setattr(_scene_generation_module(), "run_scene_generation", slow_run)
    manager.start_scene_generation(scene_id)

    state = {"current_scene_id": scene_id, "current_scene": world_with_scene.scenes[0].markdown}
    with pytest.raises(ToolException, match="currently being generated"):
        update_scene_blueprint.invoke({"state": state, "premise": "Blocked"})

    deadline = time.time() + 2
    while manager.is_generating(scene_id) and time.time() < deadline:
        time.sleep(0.01)


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met before timeout")


def test_queue_waits_for_prerequisites(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()
    started: list[str] = []
    release_a = threading.Event()

    def controlled_run(scene_id: str, *, max_revisions: int = 1) -> None:
        started.append(scene_id)
        if scene_id == "scene_a":
            release_a.wait(timeout=2)
        time.sleep(0.02)

    monkeypatch.setattr(_scene_generation_module(), "run_scene_generation", controlled_run)
    manager.queue_scene_generations(
        [
            ("scene_a", "Generate 'A'", ()),
            ("scene_b", "Generate 'B'", ("scene_a",)),
        ]
    )

    _wait_until(lambda: "scene_a" in started)
    assert "scene_b" not in started
    by_scene = {item.scene_id: item for item in manager.queued_items()}
    assert by_scene["scene_a"].status == "running"
    assert by_scene["scene_b"].status == "pending"

    release_a.set()
    _wait_until(lambda: "scene_b" in started)
    _wait_until(lambda: all(item.status == "finished" for item in manager.queued_items()))
    assert started == ["scene_a", "scene_b"]


def test_queue_starts_independent_scenes_in_parallel(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()
    started: list[str] = []
    barrier = threading.Barrier(2, timeout=2)

    def parallel_run(scene_id: str, *, max_revisions: int = 1) -> None:
        started.append(scene_id)
        barrier.wait()

    monkeypatch.setattr(_scene_generation_module(), "run_scene_generation", parallel_run)
    manager.queue_scene_generations(
        [
            ("scene_a", "Generate 'A'", ()),
            ("scene_b", "Generate 'B'", ()),
        ]
    )

    _wait_until(lambda: all(item.status == "finished" for item in manager.queued_items()))
    assert set(started) == {"scene_a", "scene_b"}


def test_queue_blocks_dependents_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()

    def failing_a(scene_id: str, *, max_revisions: int = 1) -> None:
        if scene_id == "scene_a":
            raise RuntimeError("boom")

    monkeypatch.setattr(_scene_generation_module(), "run_scene_generation", failing_a)
    manager.queue_scene_generations(
        [
            ("scene_a", "Generate 'A'", ()),
            ("scene_b", "Generate 'B'", ("scene_a",)),
        ]
    )

    _wait_until(
        lambda: (
            {item.scene_id: item.status for item in manager.queued_items()}
            == {"scene_a": "failed", "scene_b": "blocked"}
        )
    )
    by_scene = {item.scene_id: item for item in manager.queued_items()}
    assert "Blocked by prerequisite" in (by_scene["scene_b"].error or "")


def test_queue_respects_max_parallel_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.graphs.jobs as jobs_module

    manager = JobManager()
    monkeypatch.setattr(jobs_module, "MAX_PARALLEL_SCENE_GENERATIONS", 1)
    started: list[str] = []
    release_first = threading.Event()

    def capped_run(scene_id: str, *, max_revisions: int = 1) -> None:
        started.append(scene_id)
        if len(started) == 1:
            release_first.wait(timeout=2)
        time.sleep(0.01)

    monkeypatch.setattr(_scene_generation_module(), "run_scene_generation", capped_run)
    manager.queue_scene_generations(
        [
            ("scene_a", "Generate 'A'", ()),
            ("scene_b", "Generate 'B'", ()),
            ("scene_c", "Generate 'C'", ()),
        ]
    )

    _wait_until(lambda: len(started) == 1)
    assert len([item for item in manager.queued_items() if item.status == "running"]) == 1
    assert len([item for item in manager.queued_items() if item.status == "pending"]) == 2

    release_first.set()
    _wait_until(lambda: all(item.status == "finished" for item in manager.queued_items()))
    assert set(started) == {"scene_a", "scene_b", "scene_c"}


def test_unselected_prerequisite_treated_as_satisfied(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()
    started: list[str] = []

    def quick_run(scene_id: str, *, max_revisions: int = 1) -> None:
        started.append(scene_id)

    monkeypatch.setattr(_scene_generation_module(), "run_scene_generation", quick_run)
    # scene_a is a prerequisite in the plan but not selected for this batch.
    manager.queue_scene_generations(
        [
            ("scene_b", "Generate 'B'", ("scene_a",)),
        ]
    )

    _wait_until(lambda: all(item.status == "finished" for item in manager.queued_items()))
    assert started == ["scene_b"]
    assert manager.queued_items()[0].prerequisite_scene_ids == []


def test_active_work_count_includes_pending_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = JobManager()
    release_a = threading.Event()

    def controlled_run(scene_id: str, *, max_revisions: int = 1) -> None:
        if scene_id == "scene_a":
            release_a.wait(timeout=2)

    monkeypatch.setattr(_scene_generation_module(), "run_scene_generation", controlled_run)
    manager.queue_scene_generations(
        [
            ("scene_a", "Generate 'A'", ()),
            ("scene_b", "Generate 'B'", ("scene_a",)),
        ]
    )

    _wait_until(lambda: manager.active_work_count() >= 2)
    assert manager.active_work_count() == 2  # one running + one pending
    release_a.set()
    _wait_until(lambda: manager.active_work_count() == 0)
