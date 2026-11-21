"""Batch acceptance through the V2 API and real SQLite/task services."""

from pathlib import Path
import threading
import time
import wave

from fastapi.testclient import TestClient
import pytest

from src.api.http import dependencies
from src.api.http.app import create_app
from src.app.persistence import SqliteStateStore
from src.app.services.artifact_service import ArtifactService
from src.app.services.batch_run_service import BatchRunService
from src.app.services.input_catalog_service import InputCatalogService
from src.app.services.pipeline_service import PipelineService
from src.app.services.pipeline_task_orchestrator import PipelineTaskOrchestrator
from src.app.services.session_service import SessionService
from src.app.services.task_service import TaskService
from src.core.orchestration.pipeline.graph_adapters import GraphStageRunner


def _wait_for(fetch, predicate):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        record = fetch()
        if predicate(record):
            return record
        time.sleep(0.02)
    pytest.fail(f"batch did not reach its expected state: {record}")


def _wav(path, sample):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(sample.to_bytes(2, "little", signed=True) * 800)


@pytest.fixture
def batch(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    tasks = TaskService(state_store=store)
    catalog = InputCatalogService()
    pipeline = PipelineService(
        task_service=tasks,
        input_catalog_service=catalog,
        session_service=SessionService(input_catalog_service=catalog),
        artifact_service=ArtifactService(state_store=store),
    )
    orchestrator = PipelineTaskOrchestrator(pipeline, tasks)
    service = BatchRunService(orchestrator, store)
    app = create_app()
    app.dependency_overrides[dependencies.batch_run_service] = lambda: service
    client = TestClient(app)
    groups = []
    for index, name in enumerate(("first", "second"), start=1):
        path = tmp_path / f"{name}.wav"
        _wav(path, index)
        groups.append({"group_id": name, "label": name, "bindings": {"source": {"path": str(path)}}})
    body = {
        "name": "Audio export",
        "client_request_id": "local-batch-1",
        "output": {"directory": str(tmp_path / "out")},
        "execution_profile": {
            "version": 2,
            "graph": {
                "version": 2,
                "nodes": [{"id": "export", "kind": "audio_export", "provider": "local"}],
                "input_slots": [{"id": "source", "type": "audio", "label": "Source"}],
                "edges": [{"source": {"kind": "slot", "slot_id": "source"},
                           "target": {"node_id": "export", "port": "audio"}}],
                "outputs": [{"node_id": "export", "port": "audio"}],
            },
        },
        "groups": groups,
    }
    return client, body, orchestrator, store


def test_batch_failure_preserves_other_group_results_and_retry_history(batch, monkeypatch):
    client, body, orchestrator, store = batch
    run = GraphStageRunner.run
    failed = False

    def fail_first_export(self, node, inputs, plan, directory, **kwargs):
        nonlocal failed
        if Path(inputs["audio"].path).stem == "first" and not failed:
            failed = True
            raise RuntimeError("temporary export failure")
        return run(self, node, inputs, plan, directory, **kwargs)

    monkeypatch.setattr(GraphStageRunner, "run", fail_first_export)
    accepted = client.post("/api/v1/batch-runs", json=body)
    assert accepted.status_code == 202, accepted.text
    batch_id = accepted.json()["batch_id"]
    url = f"/api/v1/batch-runs/{batch_id}"

    def fetch():
        return client.get(url).json()

    partial = _wait_for(fetch, lambda record: record["state"] == "completed_with_errors")
    first, second = partial["items"]
    assert first["state"] == "failed"
    assert second["state"] == "completed"
    assert Path(second["output_path"]).is_file()
    assert first["current_task_id"] != second["current_task_id"]

    duplicate = client.post("/api/v1/batch-runs", json=body)
    assert duplicate.status_code == 202, duplicate.text
    assert duplicate.json()["batch_id"] == batch_id
    retried = client.post(f"{url}/retry-failed")
    assert retried.status_code == 200, retried.text
    complete = _wait_for(fetch, lambda record: record["state"] == "completed")
    retried_first, untouched_second = complete["items"]
    assert retried_first["task_ids"][0] == first["current_task_id"]
    assert len(retried_first["task_ids"]) == 2
    assert untouched_second["task_ids"] == second["task_ids"]
    assert Path(retried_first["output_path"]).is_file()
    assert retried_first["output_path"] != untouched_second["output_path"]
    assert orchestrator.get_task(first["current_task_id"]).state == "failed"

    restored = BatchRunService(orchestrator, SqliteStateStore(store.db_path)).get_batch(batch_id)
    assert restored.state == "completed"
    assert [item.task_ids for item in restored.items] == [item["task_ids"] for item in complete["items"]]


def test_cancel_stops_the_running_group_without_starting_the_next_group(batch, monkeypatch):
    client, body, _, _ = batch
    started = threading.Event()

    def block_until_cancelled(self, node, inputs, plan, directory, *, cancel_event):
        started.set()
        assert cancel_event.wait(timeout=10)
        raise RuntimeError("execution stopped after cancellation")

    monkeypatch.setattr(GraphStageRunner, "run", block_until_cancelled)
    accepted = client.post("/api/v1/batch-runs", json=body)
    assert accepted.status_code == 202, accepted.text
    url = f'/api/v1/batch-runs/{accepted.json()["batch_id"]}'
    assert started.wait(timeout=8)
    cancelled = client.post(f"{url}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    result = _wait_for(lambda: client.get(url).json(), lambda record: record["state"] == "cancelled")
    running, queued = result["items"]
    assert running["state"] == queued["state"] == "cancelled"
    assert len(running["task_ids"]) == 1
    assert queued["task_ids"] == []
