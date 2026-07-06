"""Tests for JobManager lifecycle, claims, and chat job behavior."""

from __future__ import annotations

import asyncio
import importlib
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
