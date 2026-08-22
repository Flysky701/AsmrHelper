from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import threading
import time

from fastapi.testclient import TestClient

from src.api.http import dependencies
from src.api.http.app import create_app
from src.app.dto import TaskStatus
from src.app.persistence import SqliteStateStore
from src.app.services.batch_run_service import BatchRunService
from src.core.batches import BatchRunItem, BatchRunRecord


def _wait_for(predicate, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("condition was not reached before timeout")


class FakePipelineOrchestrator:
    def __init__(self, outcomes: list[str]) -> None:
        self._outcomes = list(outcomes)
        self._tasks: dict[str, TaskStatus] = {}
        self._lock = threading.Lock()
        self.submissions = []

    def submit_task(self, request, *, task_source: str):
        with self._lock:
            task_id = f"pipeline-{len(self._tasks) + 1}"
            outcome = self._outcomes.pop(0) if self._outcomes else "completed"
            status = TaskStatus(
                task_id=task_id,
                task_type="pipeline",
                task_source=task_source,
                state=outcome,
                progress=1.0 if outcome in {"completed", "failed"} else 0.25,
                message=outcome,
                detail=f"/output/{task_id}.wav" if outcome == "completed" else "",
                error=(
                    {
                        "code": "TEST_FAILURE",
                        "stage": "tts",
                        "message": "planned failure",
                        "retryable": True,
                    }
                    if outcome == "failed"
                    else None
                ),
            )
            self._tasks[task_id] = status
            self.submissions.append((deepcopy(request), task_source))
            return deepcopy(status)

    def get_task(self, task_id: str):
        with self._lock:
            return deepcopy(self._tasks[task_id])

    def request_cancel(self, task_id: str):
        with self._lock:
            status = self._tasks[task_id]
            status.state = "cancelled"
            status.progress = 1.0
            status.message = "cancelled by user"
            return deepcopy(status)


def _profile() -> dict:
    stage = {
        "enabled": True,
        "provider": "test",
        "model": None,
        "options": {},
        "provider_options": {},
    }
    return {
        "version": 1,
        "source_lang": "ja",
        "target_lang": "zh",
        "skip_existing": False,
        "stages": {
            name: deepcopy(stage)
            for name in ("separate", "asr", "translate", "tts", "mix", "export")
        },
    }


def _input(path: Path) -> dict:
    path.write_bytes(b"audio")
    return {"path": str(path), "companion_paths": []}


def test_discover_audio_files_is_recursive_and_finds_companion(tmp_path):
    nested = tmp_path / "nested"
    nested.mkdir()
    audio = nested / "sample.wav"
    audio.write_bytes(b"audio")
    subtitle = nested / "sample.srt"
    subtitle.write_text("subtitle", encoding="utf-8")
    (nested / "ignore.txt").write_text("ignore", encoding="utf-8")

    service = BatchRunService(
        pipeline_orchestrator=FakePipelineOrchestrator([]),
        state_store=SqliteStateStore(tmp_path / "state.sqlite3"),
    )

    assert service.discover_audio_files(str(tmp_path), recursive=False) == []
    files = service.discover_audio_files(str(tmp_path), recursive=True)
    assert [item["path"] for item in files] == [str(audio.resolve())]
    assert files[0]["companion_paths"] == [str(subtitle.resolve())]


def test_batch_run_has_stable_id_children_and_persists(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    orchestrator = FakePipelineOrchestrator(["completed", "completed"])
    service = BatchRunService(orchestrator, store)

    created = service.create_batch(
        name="nightly",
        inputs=[_input(tmp_path / "a.wav"), _input(tmp_path / "b.wav")],
        output_dir=str(tmp_path / "output"),
        execution_profile=_profile(),
        max_parallel=1,
    )
    completed = _wait_for(
        lambda: (
            batch
            if (batch := service.get_batch(created.batch_id)).state == "completed"
            else None
        )
    )

    assert completed.batch_id.startswith("batch-")
    assert completed.progress == 1.0
    assert [item.task_ids for item in completed.items] == [
        ["pipeline-1"],
        ["pipeline-2"],
    ]
    assert all(source == f"batch-run:{completed.batch_id}" for _, source in orchestrator.submissions)

    restored = BatchRunService(FakePipelineOrchestrator([]), store)
    restored_record = restored.get_batch(completed.batch_id)
    assert restored_record.state == "completed"
    assert [item.current_task_id for item in restored_record.items] == [
        "pipeline-1",
        "pipeline-2",
    ]


def test_batch_cancel_stops_running_and_unsubmitted_items(tmp_path):
    service = BatchRunService(
        FakePipelineOrchestrator(["running", "running"]),
        SqliteStateStore(tmp_path / "state.sqlite3"),
    )
    created = service.create_batch(
        name="cancel-me",
        inputs=[_input(tmp_path / "a.wav"), _input(tmp_path / "b.wav")],
        output_dir="",
        execution_profile=_profile(),
        max_parallel=1,
    )
    _wait_for(lambda: service.get_batch(created.batch_id).items[0].current_task_id)
    service.request_cancel(created.batch_id)
    cancelled = _wait_for(
        lambda: (
            batch
            if (batch := service.get_batch(created.batch_id)).state == "cancelled"
            else None
        )
    )

    assert [item.state for item in cancelled.items] == ["cancelled", "cancelled"]
    assert cancelled.items[1].current_task_id is None


def test_retry_failed_resubmits_only_failed_items(tmp_path):
    orchestrator = FakePipelineOrchestrator(["failed", "completed", "completed"])
    service = BatchRunService(
        orchestrator,
        SqliteStateStore(tmp_path / "state.sqlite3"),
    )
    created = service.create_batch(
        name="retry",
        inputs=[_input(tmp_path / "a.wav"), _input(tmp_path / "b.wav")],
        output_dir="",
        execution_profile=_profile(),
        max_parallel=2,
    )
    failed = _wait_for(
        lambda: (
            batch
            if (batch := service.get_batch(created.batch_id)).state
            == "completed_with_errors"
            else None
        )
    )
    assert [item.state for item in failed.items] == ["failed", "completed"]

    service.retry_failed(created.batch_id)
    retried = _wait_for(
        lambda: (
            batch
            if (batch := service.get_batch(created.batch_id)).state == "completed"
            else None
        )
    )
    assert retried.items[0].task_ids == ["pipeline-1", "pipeline-3"]
    assert retried.items[1].task_ids == ["pipeline-2"]


def test_unfinished_batch_is_marked_interrupted_after_restart(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    record = BatchRunRecord(
        batch_id="batch-old",
        name="old",
        state="running",
        progress=0.25,
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
        finished_at=None,
        output_dir="",
        execution_profile=_profile(),
        max_parallel=1,
        items=[BatchRunItem(item_id="item-1", input_path="old.wav", state="running")],
    )
    store.save_batch_run(record)

    restored = BatchRunService(FakePipelineOrchestrator([]), store).get_batch("batch-old")
    assert restored.state == "interrupted"
    assert restored.items[0].state == "failed"
    assert restored.items[0].error["code"] == "BATCH_INTERRUPTED"


def test_batch_run_http_contract():
    record = BatchRunRecord(
        batch_id="batch-api",
        name="api batch",
        state="pending",
        progress=0.0,
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
        finished_at=None,
        output_dir="/output",
        execution_profile=_profile(),
        max_parallel=1,
        items=[BatchRunItem(item_id="item-1", input_path="/input.wav")],
    )

    class FakeBatchService:
        def discover_audio_files(self, directory, *, recursive=True):
            return [{"path": "/input.wav", "name": "input.wav", "size_bytes": 5, "companion_paths": []}]

        def create_batch(self, **kwargs):
            self.created = kwargs
            return record

        def list_batches(self):
            return [record]

        def get_batch(self, batch_id):
            return record

        def request_cancel(self, batch_id):
            return record

        def retry_failed(self, batch_id):
            return record

    service = FakeBatchService()
    app = create_app()
    app.dependency_overrides[dependencies.batch_run_service] = lambda: service
    client = TestClient(app)

    discovered = client.post(
        "/api/v1/batch-runs/discover",
        json={"directory": "/input", "recursive": True},
    )
    assert discovered.status_code == 200
    assert discovered.json()["files"][0]["name"] == "input.wav"

    created = client.post(
        "/api/v1/batch-runs",
        json={
            "name": "api batch",
            "inputs": [{"path": "/input.wav"}],
            "output": {"directory": "/output"},
            "execution_profile": _profile(),
            "max_parallel": 1,
        },
    )
    assert created.status_code == 202
    assert created.json()["batch_id"] == "batch-api"
    assert service.created["execution_profile"] == _profile()
    assert client.get("/api/v1/batch-runs").json()["batches"][0]["total_count"] == 1
    assert client.post("/api/v1/batch-runs/batch-api/cancel").status_code == 200
    assert client.post("/api/v1/batch-runs/batch-api/retry-failed").status_code == 200
