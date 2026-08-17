"""Persistence facade for LLM debug call logs."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from app.persistence.paths import get_data_dir

LOGGER = logging.getLogger("app.persistence.llm_call_logs")

DEFAULT_LLM_CALL_LOG_PATH = get_data_dir() / "llm_call_logs.json"
DEFAULT_MAX_LLM_CALL_LOG_RECORDS = 200

LLMCallStatus = Literal["running", "success", "error"]

_LLM_CALL_LOG_STORE: LLMCallLogStore | None = None


class LLMCallRecord(BaseModel):
    """Serializable record for one chat model invocation."""

    run_id: str
    status: LLMCallStatus
    started_at: str
    finished_at: str | None = None
    node: str | None = None
    model: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    prompt: str = ""
    prompt_messages: list[dict[str, Any]] = Field(default_factory=list)
    response_text: str | None = None
    response_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    response_metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int | None = None


class LLMCallLogStore(Protocol):
    """Minimal persistence API for LLM debug call logs."""

    def list(self) -> list[LLMCallRecord]:
        """Return persisted records newest-first."""

    def get(self, run_id: str) -> LLMCallRecord | None:
        """Return one persisted record by run id."""

    def start(self, record: LLMCallRecord) -> None:
        """Create or replace a running record."""

    def finish(
        self,
        run_id: str,
        *,
        status: Literal["success", "error"],
        finished_at: str,
        response_text: str | None = None,
        response_tool_calls: list[dict[str, Any]] | None = None,
        response_metadata: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Finalize a record, creating a minimal one if needed."""


class JsonFileLLMCallLogStore:
    """JSON-file-backed LLM call log store with bounded retention.

    Parallel workflow nodes (e.g. the scene review fan-out) invoke the debug
    callback concurrently, so every read-modify-write cycle runs under a
    blocking lock: concurrent writers wait for each other instead of failing
    or corrupting the file.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_records: int = DEFAULT_MAX_LLM_CALL_LOG_RECORDS,
    ) -> None:
        self.path = path or DEFAULT_LLM_CALL_LOG_PATH
        self.max_records = max_records
        self._lock = threading.Lock()

    def list(self) -> list[LLMCallRecord]:
        """Return call records newest-first for display."""

        with self._lock:
            return list(reversed(self._load()))

    def get(self, run_id: str) -> LLMCallRecord | None:
        """Return one call record by run id."""

        with self._lock:
            return next((record for record in self._load() if record.run_id == run_id), None)

    def start(self, record: LLMCallRecord) -> None:
        """Persist a running call record."""

        with self._lock:
            records = _upsert_record(self._load(), record)
            self._write(records)

    def finish(
        self,
        run_id: str,
        *,
        status: Literal["success", "error"],
        finished_at: str,
        response_text: str | None = None,
        response_tool_calls: list[dict[str, Any]] | None = None,
        response_metadata: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Persist the terminal state for a call record."""

        with self._lock:
            records = self._load()
            existing = next((record for record in records if record.run_id == run_id), None)
            if existing is None:
                existing = LLMCallRecord(
                    run_id=run_id,
                    status=status,
                    started_at=finished_at,
                )
            updated = existing.model_copy(
                update={
                    "status": status,
                    "finished_at": finished_at,
                    "response_text": response_text,
                    "response_tool_calls": response_tool_calls or [],
                    "response_metadata": response_metadata or {},
                    "error": error,
                    "duration_ms": duration_ms,
                }
            )
            self._write(_upsert_record(records, updated))

    def _load(self) -> list[LLMCallRecord]:
        if not self.path.exists():
            return []

        raw = self.path.read_text(encoding="utf-8")
        if not raw.strip():
            return []

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # A corrupted log (e.g. from a torn write before locking existed) is
            # debug-only data; discard it so logging recovers instead of failing
            # on every subsequent call.
            LOGGER.warning(
                "Discarding corrupted LLM call log at %s; starting a fresh log.", self.path
            )
            return []
        if not isinstance(data, list):
            msg = f"Expected LLM call log JSON list at {self.path}"
            raise ValueError(msg)
        return [LLMCallRecord.model_validate(record) for record in data]

    def _write(self, records: Sequence[LLMCallRecord]) -> None:
        bounded_records = list(records)[-self.max_records :]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(
                [record.model_dump(mode="json") for record in bounded_records],
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_path, self.path)


def get_llm_call_log_store() -> LLMCallLogStore:
    """Return the process-local LLM call log store singleton."""

    global _LLM_CALL_LOG_STORE

    if _LLM_CALL_LOG_STORE is None:
        _LLM_CALL_LOG_STORE = JsonFileLLMCallLogStore()
    return _LLM_CALL_LOG_STORE


def _upsert_record(
    records: Sequence[LLMCallRecord],
    record: LLMCallRecord,
) -> list[LLMCallRecord]:
    updated = list(records)
    for index, existing in enumerate(updated):
        if existing.run_id == record.run_id:
            updated[index] = record
            return updated
    updated.append(record)
    return updated
