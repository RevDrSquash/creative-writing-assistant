"""Unit tests for LLM debug call-log persistence."""

from app.persistence import JsonFileLLMCallLogStore, LLMCallRecord


def _record(run_id: str, started_at: str) -> LLMCallRecord:
    return LLMCallRecord(
        run_id=run_id,
        status="running",
        started_at=started_at,
        model=f"model-{run_id}",
    )


def test_start_then_list_round_trips_from_fresh_instance(tmp_path) -> None:
    path = tmp_path / "llm_call_logs.json"
    store = JsonFileLLMCallLogStore(path)

    store.start(_record("run-1", "2026-05-30T10:00:00+00:00"))

    loaded = JsonFileLLMCallLogStore(path).list()
    assert len(loaded) == 1
    assert loaded[0].run_id == "run-1"
    assert loaded[0].model == "model-run-1"


def test_list_returns_newest_first(tmp_path) -> None:
    store = JsonFileLLMCallLogStore(tmp_path / "llm_call_logs.json")

    store.start(_record("old", "2026-05-30T10:00:00+00:00"))
    store.start(_record("new", "2026-05-30T10:01:00+00:00"))

    assert [record.run_id for record in store.list()] == ["new", "old"]


def test_ring_buffer_trims_oldest_records(tmp_path) -> None:
    store = JsonFileLLMCallLogStore(tmp_path / "llm_call_logs.json", max_records=2)

    store.start(_record("run-1", "2026-05-30T10:00:00+00:00"))
    store.start(_record("run-2", "2026-05-30T10:01:00+00:00"))
    store.start(_record("run-3", "2026-05-30T10:02:00+00:00"))

    assert [record.run_id for record in store.list()] == ["run-3", "run-2"]
    assert store.get("run-1") is None


def test_finish_upserts_existing_record_by_run_id(tmp_path) -> None:
    store = JsonFileLLMCallLogStore(tmp_path / "llm_call_logs.json")
    store.start(_record("run-1", "2026-05-30T10:00:00+00:00"))

    store.finish(
        "run-1",
        status="success",
        finished_at="2026-05-30T10:00:01+00:00",
        response_text="Done.",
        response_metadata={"model_name": "example/model"},
        duration_ms=1000,
    )

    records = store.list()
    assert len(records) == 1
    assert records[0].status == "success"
    assert records[0].response_text == "Done."
    assert records[0].response_metadata == {"model_name": "example/model"}
    assert records[0].duration_ms == 1000
