from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.dto import ArtifactSet
from src.app.dto.batch_pipeline import BatchPipelineRequest
from src.app.errors import AppExecutionError
from src.app.services.artifact_service import ArtifactService
from src.app.services.batch_pipeline_service import BatchPipelineService
from src.app.services.pipeline_task_orchestrator import PipelineTaskOrchestrator
from src.app.services.task_service import TaskService
from src.core.resources.model_catalog import ModelEntry
from src.core.resources.model_installer import ModelDownloadError, ModelInstaller
from src.core.runtime.profiles import RuntimeProfileResolver
from src.core.runtime.router import RuntimeRouter, RuntimeWorkerError


def _wait_for_state(
    task_service: TaskService,
    task_id: str,
    expected: str,
    *,
    timeout: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if task_service.get_task(task_id).state == expected:
            return
        time.sleep(0.01)
    assert task_service.get_task(task_id).state == expected


def test_sequential_batch_failure_does_not_block_later_items_or_mix_artifacts(tmp_path):
    input_paths = [tmp_path / name for name in ("01.wav", "02.wav", "03.wav")]
    for input_path in input_paths:
        input_path.write_bytes(b"audio")

    task_service = TaskService()
    artifact_service = ArtifactService()
    assets: dict[str, SimpleNamespace] = {}
    sessions: dict[str, SimpleNamespace] = {}
    task_ids_by_input: dict[str, str] = {}

    class InputCatalog:
        def inspect_paths(self, paths):
            resolved = []
            for raw_path in paths:
                path = str(Path(raw_path))
                asset = assets.setdefault(
                    path,
                    SimpleNamespace(
                        asset_id=f"asset-{Path(path).stem}",
                        absolute_path=path,
                        kind="audio",
                    ),
                )
                resolved.append(asset)
            return resolved

        def discover_companions(self, asset_id):
            return []

        def get_asset(self, asset_id):
            return next(asset for asset in assets.values() if asset.asset_id == asset_id)

    catalog = InputCatalog()

    class SessionLookup:
        def get_session(self, session_id):
            return sessions[session_id]

    class Pipeline:
        def create_pipeline_task(self, request, *, task_source):
            asset = catalog.inspect_paths([request.input_path])[0]
            session_id = f"session-{asset.asset_id}"
            sessions[session_id] = SimpleNamespace(
                session_id=session_id,
                resolved_output_dir=str(tmp_path / "output" / Path(request.input_path).stem),
            )
            spec, status = task_service.create_task_spec(
                task_type="pipeline",
                task_source=task_source,
                session_id=session_id,
                input_asset_id=asset.asset_id,
                execution_profile={"version": 1, "stages": {}},
            )
            task_ids_by_input[request.input_path] = spec.task_id
            return status, spec

        def run_pipeline_task(self, task_id, *, cancel_event=None):
            spec = task_service.get_task_spec(task_id)
            input_path = Path(catalog.get_asset(spec.input_asset_id).absolute_path)
            task_service.start_task(task_id, stage="prepare")
            if input_path.name == "02.wav":
                task_service.update_progress(
                    task_id,
                    progress=0.6,
                    message="injected Edge failure",
                    stage="tts",
                )
                task_service.fail_task(
                    task_id,
                    message="tts failed",
                    detail="injected Edge failure",
                    stage="tts",
                )
                raise AppExecutionError("injected Edge failure")

            output_path = tmp_path / "output" / f"{input_path.stem}_mix.wav"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"mix")
            artifact_service.register_artifact(
                task_id=task_id,
                artifact_type="audio.mix",
                path=str(output_path),
                stage="mix",
                is_primary=True,
            )
            task_service.complete_task(
                task_id,
                message="pipeline completed",
                stage="export",
                artifact_set_id=task_id,
            )
            return SimpleNamespace(
                mix_path=str(output_path),
                artifacts=ArtifactSet.from_optional_paths(primary_output=str(output_path)),
            )

    service = BatchPipelineService(
        pipeline_service=Pipeline(),
        task_service=task_service,
        session_service=SessionLookup(),
        input_catalog_service=catalog,
    )
    result = service.run_batch(
        BatchPipelineRequest(
            input_files=[str(path) for path in input_paths],
            skip_existing=False,
            max_workers=1,
        )
    )

    assert [item.status for item in result.items] == ["success", "failed", "success"]
    assert [item.file for item in result.items] == [str(path) for path in input_paths]
    assert (result.success_count, result.failed_count, result.total_count) == (2, 1, 3)

    first_id = task_ids_by_input[str(input_paths[0])]
    failed_id = task_ids_by_input[str(input_paths[1])]
    last_id = task_ids_by_input[str(input_paths[2])]
    assert task_service.get_task(first_id).state == "completed"
    assert task_service.get_task(failed_id).state == "failed"
    assert task_service.get_task(failed_id).error["stage"] == "tts"
    assert task_service.get_task(last_id).state == "completed"
    assert artifact_service.get_task_artifacts(failed_id).entries == []
    for task_id in (first_id, last_id):
        artifacts = artifact_service.get_task_artifacts(task_id)
        assert len(artifacts.entries) == 1
        assert artifacts.entries[0].task_id == task_id
        assert artifacts.entries[0].is_primary is True


def test_cancelled_task_can_be_resubmitted_as_new_task_with_new_artifacts(tmp_path):
    task_service = TaskService()
    artifact_service = ArtifactService()
    first_started = threading.Event()
    first_cancelled = threading.Event()
    run_count = 0

    class Pipeline:
        def create_pipeline_task(self, request, *, task_source):
            spec, status = task_service.create_task_spec(
                task_type="pipeline",
                task_source=task_source,
                session_id="session-1",
                input_asset_id="asset-1",
                execution_profile={"version": 1, "stages": {}},
            )
            return status, spec

        def run_pipeline_task(self, task_id, *, cancel_event=None):
            nonlocal run_count
            run_count += 1
            if run_count == 1:
                first_started.set()
                assert cancel_event is not None
                assert cancel_event.wait(timeout=2)
                task_service.cancel_task(task_id)
                first_cancelled.set()
                raise AppExecutionError("cancelled by user")

            output_path = tmp_path / f"{task_id}.wav"
            output_path.write_bytes(b"mix")
            artifact_service.register_artifact(
                task_id=task_id,
                artifact_type="audio.mix",
                path=str(output_path),
                stage="mix",
                is_primary=True,
            )
            task_service.complete_task(
                task_id,
                message="pipeline completed",
                stage="export",
                artifact_set_id=task_id,
            )
            return SimpleNamespace(task_id=task_id)

    orchestrator = PipelineTaskOrchestrator(
        pipeline_service=Pipeline(),
        task_service=task_service,
        artifact_service=artifact_service,
    )
    from src.app.dto import PipelineRequest

    original = orchestrator.submit_task(PipelineRequest(input_path="input.wav"))
    assert first_started.wait(timeout=1)
    orchestrator.request_cancel(original.task_id)
    assert first_cancelled.wait(timeout=1)
    _wait_for_state(task_service, original.task_id, "cancelled")

    retried = orchestrator.retry_task(original.task_id)
    _wait_for_state(task_service, retried.task_id, "completed")

    assert retried.task_id != original.task_id
    assert task_service.get_task(original.task_id).state == "cancelled"
    assert artifact_service.get_task_artifacts(original.task_id).entries == []
    retry_artifacts = artifact_service.get_task_artifacts(retried.task_id)
    assert retry_artifacts.primary_output == str(tmp_path / f"{retried.task_id}.wav")
    assert all(record.task_id == retried.task_id for record in retry_artifacts.entries)


def test_worker_abnormal_exit_is_reported_and_exchange_files_are_cleaned(
    tmp_path,
    monkeypatch,
):
    resolver = RuntimeProfileResolver(project_root=tmp_path)
    profile = resolver.resolve("qwen_tts")
    profile.python_executable.parent.mkdir(parents=True)
    profile.python_executable.write_bytes(b"python")
    router = RuntimeRouter(resolver=resolver, project_root=tmp_path)

    monkeypatch.setattr(
        "src.core.runtime.router.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=23,
            stdout="",
            stderr="worker process terminated unexpectedly",
        ),
    )

    with pytest.raises(RuntimeWorkerError, match="terminated unexpectedly"):
        router.synthesize_text(
            {
                "text": "hello",
                "output_path": str(tmp_path / "result.wav"),
                "profile": {"provider": "qwen3"},
            }
        )

    exchange_dir = tmp_path / ".tmp" / "runtime-workers"
    assert list(exchange_dir.iterdir()) == []


def test_interrupted_model_download_preserves_partial_files_for_retry(
    tmp_path,
    monkeypatch,
):
    entry = ModelEntry(
        id="sample-model",
        kind="local",
        category="tts",
        provider="sample",
        display_name="Sample",
        description="acceptance fixture",
        install_root=str(tmp_path / "models"),
        install_path="sample",
        required_files=["model.safetensors"],
        supports_install=True,
        install_strategy="huggingface_snapshot",
        upstream_name="sample/model",
    )
    installer = ModelInstaller(project_root=tmp_path)
    attempts = 0
    partial_path = entry.resolved_install_dir() / ".cache" / "model.safetensors.incomplete"

    def interrupted_then_resumed(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            partial_path.parent.mkdir(parents=True, exist_ok=True)
            partial_path.write_bytes(b"partial")
            raise ModelDownloadError("connection interrupted")
        assert partial_path.read_bytes() == b"partial"
        (entry.resolved_install_dir() / "model.safetensors").write_bytes(b"complete")
        return True

    monkeypatch.setattr(installer, "_run_with_progress", interrupted_then_resumed)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    assert installer.install_with_progress(entry) is True
    assert attempts == 2


def test_verify_env_script_resolves_project_when_started_outside_repository(tmp_path):
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(project_root / "scripts" / "verify_env.py")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert str(project_root / "config" / "config.json") in result.stdout
    assert "Startup environment is ready." in result.stdout
