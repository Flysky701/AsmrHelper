"""Task V1 and shared executor-boundary acceptance tests."""

from __future__ import annotations

import threading
import time

import pytest

from src.app.errors import AppValidationError
from src.app.persistence import SqliteStateStore
from src.app.services.task_service import TaskService
from src.core.tasks import ExecutorRegistry, TaskDispatcher


def _create(service: TaskService, task_type: str = "pipeline"):
    return service.create_task_spec(
        task_type=task_type,
        task_source="contract-test",
        session_id="session-1",
    )


def _wait_for(service: TaskService, task_id: str, state: str) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if service.get_task(task_id).state == state:
            return
        time.sleep(0.01)
    assert service.get_task(task_id).state == state


def test_unregistered_task_type_is_rejected_at_submission():
    service = TaskService(executor_registry=ExecutorRegistry())

    with pytest.raises(AppValidationError, match="no executor registered"):
        _create(service, "not.registered")


def test_terminal_status_is_immutable_and_retry_is_a_new_task():
    service = TaskService()
    spec, _ = _create(service)
    service.start_task(spec.task_id)
    service.complete_task(spec.task_id, message="done", stage="export")

    with pytest.raises(AppValidationError, match="terminal task is immutable"):
        service.fail_task(spec.task_id, message="late failure")

    with pytest.raises(AppValidationError, match="terminal task is immutable"):
        service.update_progress(spec.task_id, 0.5, message="late update")

    # Retry is only valid for failure/cancellation, and must not reopen history.
    failed_spec, _ = _create(service)
    service.start_task(failed_spec.task_id)
    service.fail_task(failed_spec.task_id, message="failed", stage="tts")
    retried = service.retry_task(failed_spec.task_id)
    assert retried.task_id != failed_spec.task_id
    assert retried.state == "pending"
    assert retried.retry_of_task_id == failed_spec.task_id
    assert service.get_task(failed_spec.task_id).state == "failed"


def test_dispatcher_starts_one_task_once_and_finalizes_after_executor_exit():
    service = TaskService()
    dispatcher = TaskDispatcher(service.registry, task_service=service)
    started = threading.Event()
    release = threading.Event()
    exited = threading.Event()
    calls = 0

    def execute(_spec, context):
        nonlocal calls
        calls += 1
        started.set()
        try:
            context.cancel_event.wait(timeout=2)
            return {"primary_output": "output.wav"}
        finally:
            exited.set()

    dispatcher.register_executor("pipeline", execute)
    spec, _ = _create(service)
    accepted = dispatcher.submit(spec.task_id)
    assert accepted.state == "running"
    assert started.wait(timeout=1)

    requested = dispatcher.request_cancel(spec.task_id)
    assert requested.state == "running"
    assert requested.message == "cancellation requested"
    assert exited.wait(timeout=1)
    _wait_for(service, spec.task_id, "cancelled")
    assert calls == 1
    assert service.get_task(spec.task_id).finished_at

    with pytest.raises(ValueError, match="cannot be submitted"):
        dispatcher.submit(spec.task_id)


def test_one_failed_task_does_not_block_the_next_task():
    service = TaskService(max_concurrent=1)
    dispatcher = TaskDispatcher(service.registry, task_service=service)
    executed: list[str] = []

    def execute(spec):
        executed.append(spec.task_id)
        if spec.task_id.endswith("-1"):
            raise RuntimeError("injected failure")
        return {"detail": "ok"}

    dispatcher.register_executor("pipeline", execute)
    first, _ = _create(service)
    second, _ = _create(service)
    dispatcher.dispatch_all_pending()

    assert service.get_task(first.task_id).state == "failed"
    assert service.get_task(second.task_id).state == "completed"
    assert executed == [first.task_id, second.task_id]


def test_background_queue_drains_after_a_slot_is_released():
    service = TaskService(max_concurrent=1)
    dispatcher = TaskDispatcher(service.registry, task_service=service)
    release = threading.Event()

    def execute(spec):
        if spec.task_id.endswith("-1"):
            release.wait(timeout=2)
        return {"detail": spec.task_id}

    dispatcher.register_executor("pipeline", execute)
    first, _ = _create(service)
    second, _ = _create(service)
    dispatcher.submit(first.task_id)
    assert dispatcher.submit(second.task_id).state == "pending"
    assert service.get_task(second.task_id).state == "pending"

    release.set()
    _wait_for(service, second.task_id, "completed")
    assert service.get_task(first.task_id).state == "completed"


def test_restored_non_pipeline_history_is_read_only(tmp_path):
    store = SqliteStateStore(tmp_path / "state.sqlite3")
    first = TaskService(state_store=store)
    spec, _ = _create(first, "model_install")
    first.start_task(spec.task_id, stage="install")
    first.fail_task(spec.task_id, message="download failed", stage="install")

    restarted = TaskService(state_store=SqliteStateStore(tmp_path / "state.sqlite3"))

    with pytest.raises(AppValidationError, match="historical tasks cannot be retried"):
        restarted.retry_task(spec.task_id)


def test_tool_registry_executes_through_dispatcher_with_stage_and_result():
    from src.app.services.tool_registry import ToolRegistry

    service = TaskService()

    class AudioTools:
        def run_tool_task_spec(self, spec, *, manage_lifecycle, cancel_event):
            assert manage_lifecycle is False
            assert cancel_event is not None
            return {
                "primary_output": f"{spec.task_id}.wav",
                "artifact_set_id": spec.task_id,
            }

    tools = ToolRegistry(
        audio_tool_service=AudioTools(),
        task_service=service,
    )
    spec, _ = service.create_task_spec(
        task_type="tool.separate",
        task_source="contract-test",
        session_id="session-1",
    )

    result = tools.run_task(spec.task_id)

    task = service.get_task(spec.task_id)
    assert result["primary_output"] == f"{spec.task_id}.wav"
    assert task.state == "completed"
    assert task.stage == "separate"
    assert task.artifact_set_id == spec.task_id


def test_model_install_uses_dispatcher_and_reports_install_stage():
    from types import SimpleNamespace

    from src.app.services.model_service import ModelService

    service = TaskService()

    class Models:
        def get_model(self, model_id):
            return SimpleNamespace(id=model_id)

        def install(self, model_id, **kwargs):
            kwargs["on_progress"](0.5, "downloading")
            return True

    models = ModelService(core_service=Models(), task_service=service)
    task_id = models.install_model_async("model-a")
    _wait_for(service, task_id, "completed")

    task = service.get_task(task_id)
    assert task.stage == "install"
    assert task.progress == 1.0
    assert task.error is None


def test_model_install_honors_cancellation_at_progress_boundary():
    from types import SimpleNamespace

    from src.app.services.model_service import ModelService

    service = TaskService()
    installer_started = threading.Event()
    release_installer = threading.Event()

    class Models:
        def get_model(self, model_id):
            return SimpleNamespace(id=model_id)

        def install(self, model_id, **kwargs):
            installer_started.set()
            release_installer.wait(timeout=2)
            kwargs["on_progress"](0.5, "downloading")
            return True

    models = ModelService(core_service=Models(), task_service=service)
    task_id = models.install_model_async("model-a")
    assert installer_started.wait(timeout=1)

    requested = models._dispatcher.request_cancel(task_id)
    assert requested.state == "running"
    release_installer.set()
    _wait_for(service, task_id, "cancelled")

    assert service.get_task(task_id).finished_at is not None


def test_voice_preview_uses_runtime_router_and_registers_task_artifact(tmp_path):
    from types import SimpleNamespace

    from src.app.dto import VoicePreviewRequest
    from src.app.services.artifact_service import ArtifactService
    from src.app.services.voice_service import VoiceService

    service = TaskService()
    artifacts = ArtifactService()

    class VoiceRuntime:
        def preview_voice(self, payload):
            output = tmp_path / "preview.wav"
            output.write_bytes(b"RIFF")
            assert payload["profile_id"] == "voice-1"
            return str(output)

    voices = VoiceService(
        task_service=service,
        artifact_service=artifacts,
        runtime_router=VoiceRuntime(),
    )
    voices._get_profile_or_raise = lambda _profile_id: SimpleNamespace(id="voice-1")

    result = voices.preview_voice(
        VoicePreviewRequest(profile_id="voice-1", text="hello", speed=1.0)
    )

    task = service.get_task(result.task_id)
    task_artifacts = artifacts.get_task_artifacts(result.task_id)
    assert task.state == "completed"
    assert task.stage == "preview"
    assert task.artifact_set_id == result.task_id
    assert task_artifacts.primary_output == result.audio_path
    assert all(item.task_id == result.task_id for item in task_artifacts.entries)
