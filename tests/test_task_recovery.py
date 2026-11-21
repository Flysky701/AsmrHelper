"""V2 graph checkpoints survive restart and resume into a new task."""

from dataclasses import asdict
from pathlib import Path
import time
import wave

import pytest

from src.app.dto import PipelineRequest
from src.app.errors import AppExecutionError
from src.app.persistence import SqliteStateStore
from src.app.services.artifact_service import ArtifactService
from src.app.services.input_catalog_service import InputCatalogService
from src.app.services.pipeline_service import PipelineService
from src.app.services.pipeline_task_orchestrator import PipelineTaskOrchestrator
from src.app.services.session_service import SessionService
from src.app.services.task_service import TaskService
from src.core.orchestration.pipeline.graph_adapters import GraphStageRunner


def _services(database):
    store = SqliteStateStore(database)
    tasks = TaskService(state_store=store)
    catalog = InputCatalogService()
    artifacts = ArtifactService(state_store=store)
    pipeline = PipelineService(
        task_service=tasks,
        input_catalog_service=catalog,
        session_service=SessionService(input_catalog_service=catalog),
        artifact_service=artifacts,
    )
    return tasks, pipeline, artifacts


def test_restart_retains_interrupted_graph_and_explicit_resume_reuses_export(tmp_path, monkeypatch):
    source = tmp_path / "source.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * 800)

    request = PipelineRequest(input_path=str(source), output_dir=str(tmp_path / "out"), execution_profile={
        "version": 2,
        "graph": {
            "version": 2,
            "nodes": [{"id": name, "kind": "audio_export", "provider": "local"}
                      for name in ("first", "second")],
            "input_slots": [{"id": "source", "type": "audio", "label": "Source"}],
            "edges": [
                {"source": {"kind": "slot", "slot_id": "source"},
                 "target": {"node_id": "first", "port": "audio"}},
                {"source": {"kind": "node", "node_id": "first", "port": "audio"},
                 "target": {"node_id": "second", "port": "audio"}},
            ],
            "outputs": [{"node_id": "second", "port": "audio"}],
        },
        "bindings": {"source": {"path": str(source)}},
    })
    database = tmp_path / "state.sqlite3"
    tasks, pipeline, _ = _services(database)
    _, spec = pipeline.create_pipeline_task(request)
    tasks.start_task(spec.task_id, stage="prepare")
    run = GraphStageRunner.run
    executed = []

    def observe_export(self, node, inputs, plan, directory, **kwargs):
        executed.append(node["id"])
        if executed == ["first", "second"]:
            raise RuntimeError("simulated interruption after first checkpoint")
        return run(self, node, inputs, plan, directory, **kwargs)

    monkeypatch.setattr(GraphStageRunner, "run", observe_export)
    with pytest.raises(AppExecutionError, match="simulated interruption"):
        pipeline.run_pipeline_task_spec(spec, manage_lifecycle=False)
    assert tasks.recovery_store.checkpoint(spec.task_id, "first") is not None
    assert tasks.recovery_store.checkpoint(spec.task_id, "second") is None
    assert tasks.get_task(spec.task_id).state == "running"

    restored, restarted_pipeline, artifacts = _services(database)
    old_status = asdict(restored.get_task(spec.task_id))
    assert old_status["state"] == "failed"
    assert old_status["error"]["code"] == "TASK_INTERRUPTED"
    assert restored.running_count() == 0
    assert restored.recovery_info(spec.task_id) == {
        "can_resume": True, "reason": "", "completed_stages": ["first"],
    }

    original_file = Path(restored.recovery_store.checkpoint(spec.task_id, "first")["files"][0]["original"])
    original_file.unlink()
    orchestrator = PipelineTaskOrchestrator(restarted_pipeline, restored)
    attempt = orchestrator.resume_task(spec.task_id)
    assert attempt.task_id != spec.task_id
    assert attempt.retry_of_task_id == spec.task_id
    deadline = time.monotonic() + 8
    while restored.get_task(attempt.task_id).state in {"pending", "running"} and time.monotonic() < deadline:
        time.sleep(0.02)
    completed = restored.get_task(attempt.task_id)
    assert completed.state == "completed", completed.error
    assert executed == ["first", "second", "second"]
    assert asdict(restored.get_task(spec.task_id)) == old_status
    assert restored.recovery_store.manifest(attempt.task_id)["resume_of_task_id"] == spec.task_id
    output = artifacts.get_task_artifacts(attempt.task_id).primary_output
    assert output == completed.detail
    with wave.open(output, "rb") as audio:
        assert audio.readframes(800) == b"\x01\x00" * 800
