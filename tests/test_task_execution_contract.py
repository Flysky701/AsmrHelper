"""Task V1 and shared executor-boundary acceptance tests."""

from __future__ import annotations

import threading
import time

import pytest

from src.app.errors import AppExecutionError, AppValidationError
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


def test_start_persistence_failure_cannot_be_drained_as_ghost_work():
    class SelectiveFailStore:
        def __init__(self):
            self.fail_running = True

        def purge_unfinished(self):
            return None

        def load_terminal_tasks(self):
            return []

        def save_task(self, _spec, status):
            if self.fail_running and status.state == "running":
                raise OSError("disk full")

    store = SelectiveFailStore()
    service = TaskService(state_store=store)
    dispatcher = TaskDispatcher(service.registry, task_service=service)
    executed: list[str] = []
    dispatcher.register_executor("pipeline", lambda spec: executed.append(spec.task_id))
    failed_start, _ = _create(service)

    with pytest.raises(AppExecutionError, match="failed to persist task state"):
        dispatcher.submit(failed_start.task_id)

    assert service.get_task(failed_start.task_id).state == "failed"
    store.fail_running = False
    healthy, _ = _create(service)
    dispatcher.dispatch_all_pending()

    assert executed == [healthy.task_id]
    assert service.get_task(healthy.task_id).state == "completed"


def test_provider_error_containing_cancel_is_not_user_cancellation():
    service = TaskService()
    dispatcher = TaskDispatcher(service.registry, task_service=service)

    def execute(_spec):
        raise RuntimeError("provider request cancelled upstream")

    dispatcher.register_executor("pipeline", execute)
    spec, _ = _create(service)

    dispatcher.dispatch_all_pending()

    status = service.get_task(spec.task_id)
    assert status.state == "failed"
    assert status.error["code"] == "TASK_EXECUTION_FAILED"
    assert "cancelled upstream" in status.error["detail"]


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


def test_concurrent_submit_reserves_only_one_execution_slot(monkeypatch):
    service = TaskService(max_concurrent=1)
    dispatcher = TaskDispatcher(service.registry, task_service=service)
    release = threading.Event()
    started = threading.Event()
    submit_gate = threading.Barrier(3)
    counter_lock = threading.Lock()
    active = 0
    max_active = 0
    executed: list[str] = []
    submit_errors: list[BaseException] = []
    can_start_gate = threading.Barrier(2)
    original_can_start = service.can_start
    can_start_calls = 0

    def synchronize_initial_capacity_checks() -> bool:
        # Make legacy check-then-start implementations expose the race reliably.
        nonlocal can_start_calls
        result = original_can_start()
        if not threading.current_thread().name.startswith("submit-"):
            return result
        with counter_lock:
            can_start_calls += 1
            should_wait = can_start_calls <= 2
        if should_wait:
            can_start_gate.wait(timeout=1)
        return result

    monkeypatch.setattr(service, "can_start", synchronize_initial_capacity_checks)

    def execute(spec):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
            executed.append(spec.task_id)
        started.set()
        try:
            release.wait(timeout=2)
            return {"detail": spec.task_id}
        finally:
            with counter_lock:
                active -= 1

    dispatcher.register_executor("pipeline", execute)
    first, _ = _create(service)
    second, _ = _create(service)

    def submit(task_id: str) -> None:
        try:
            submit_gate.wait(timeout=1)
            dispatcher.submit(task_id)
        except BaseException as exc:
            submit_errors.append(exc)

    submitters = [
        threading.Thread(target=submit, args=(first.task_id,), name="submit-first"),
        threading.Thread(target=submit, args=(second.task_id,), name="submit-second"),
    ]
    for submitter in submitters:
        submitter.start()
    submit_gate.wait(timeout=1)
    for submitter in submitters:
        submitter.join(timeout=1)

    assert not submit_errors
    assert all(not submitter.is_alive() for submitter in submitters)
    assert started.wait(timeout=1)
    states = {
        service.get_task(first.task_id).state,
        service.get_task(second.task_id).state,
    }
    assert states == {"pending", "running"}
    assert service.running_count() == 1
    assert max_active == 1

    release.set()
    _wait_for(service, first.task_id, "completed")
    _wait_for(service, second.task_id, "completed")
    assert set(executed) == {first.task_id, second.task_id}
    assert max_active == 1


def test_thread_start_failure_releases_slot_and_drains_next_task(monkeypatch):
    service = TaskService(max_concurrent=1)
    dispatcher = TaskDispatcher(service.registry, task_service=service)
    executed: list[str] = []
    dispatcher.register_executor("pipeline", lambda spec: executed.append(spec.task_id))
    failed_start, _ = _create(service)
    healthy, _ = _create(service)
    original_start = threading.Thread.start
    start_attempts = 0

    def fail_first_start(thread):
        nonlocal start_attempts
        start_attempts += 1
        if start_attempts == 1:
            raise RuntimeError("injected thread start failure")
        return original_start(thread)

    monkeypatch.setattr(threading.Thread, "start", fail_first_start)

    with pytest.raises(RuntimeError, match="injected thread start failure"):
        dispatcher.submit(failed_start.task_id)

    assert service.get_task(failed_start.task_id).state == "failed"
    assert dispatcher._records[failed_start.task_id].thread is None
    _wait_for(service, healthy.task_id, "completed")
    assert executed == [healthy.task_id]
    assert service.running_count() == 0


def test_start_persistence_failure_does_not_fail_the_remaining_queue():
    class RunningWriteFailureStore:
        def purge_unfinished(self):
            return None

        def load_terminal_tasks(self):
            return []

        def save_task(self, _spec, status):
            if status.state == "running":
                raise OSError("injected disk full")

    service = TaskService(
        max_concurrent=1,
        state_store=RunningWriteFailureStore(),
    )
    dispatcher = TaskDispatcher(service.registry, task_service=service)
    first, _ = _create(service)
    second, _ = _create(service)

    with pytest.raises(AppExecutionError, match="failed to persist task state"):
        dispatcher.submit(first.task_id)

    assert service.get_task(first.task_id).state == "failed"
    assert service.get_task(second.task_id).state == "pending"
    assert service.running_count() == 0


def test_queue_drain_stops_after_start_persistence_failure():
    class RunningWriteFailureStore:
        def purge_unfinished(self):
            return None

        def load_terminal_tasks(self):
            return []

        def save_task(self, _spec, status):
            if status.state == "running":
                raise OSError("injected disk full")

    service = TaskService(
        max_concurrent=1,
        state_store=RunningWriteFailureStore(),
    )
    dispatcher = TaskDispatcher(service.registry, task_service=service)
    first, _ = _create(service)
    second, _ = _create(service)

    dispatcher._drain_pending()

    assert service.get_task(first.task_id).state == "failed"
    assert service.get_task(second.task_id).state == "pending"
    assert service.running_count() == 0


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


def test_tool_registry_create_task_submits_background_execution():
    from src.app.services.tool_registry import ToolRegistry

    service = TaskService()

    class AudioTools:
        def create_tool_task_spec(self, *, task_type, input_path, execution_profile, companion_paths, task_source):
            spec, _ = service.create_task_spec(
                task_type=task_type,
                task_source=task_source,
                session_id="session-1",
                input_asset_id=input_path,
                companion_asset_ids=list(companion_paths or []),
                execution_profile=execution_profile,
            )
            return spec

        def run_tool_task_spec(self, spec, *, manage_lifecycle, cancel_event):
            assert manage_lifecycle is False
            return {
                "primary_output": f"{spec.task_id}.wav",
                "artifact_set_id": spec.task_id,
            }

    tools = ToolRegistry(audio_tool_service=AudioTools(), task_service=service)

    accepted = tools.create_task(
        task_type="tool.convert",
        input_path="input.wav",
        execution_profile={"target_format": "wav"},
        companion_paths=[],
    )

    assert accepted.state in {"running", "completed"}
    _wait_for(service, accepted.task_id, "completed")
    assert service.get_task(accepted.task_id).stage == "convert"


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
    accepted = models.install_model_async("model-a")
    _wait_for(service, accepted.task_id, "completed")

    task = service.get_task(accepted.task_id)
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
    accepted = models.install_model_async("model-a")
    assert installer_started.wait(timeout=1)

    requested = models._dispatcher.request_cancel(accepted.task_id)
    assert requested.state == "running"
    release_installer.set()
    _wait_for(service, accepted.task_id, "cancelled")

    assert service.get_task(accepted.task_id).finished_at is not None


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


def test_voice_preview_submission_returns_before_result_is_consumed(tmp_path):
    from types import SimpleNamespace

    from src.app.dto import VoicePreviewRequest
    from src.app.services.artifact_service import ArtifactService
    from src.app.services.voice_service import VoiceService

    service = TaskService()

    class VoiceRuntime:
        def preview_voice(self, _payload):
            output = tmp_path / "submitted-preview.wav"
            output.write_bytes(b"RIFF")
            return str(output)

    voices = VoiceService(
        task_service=service,
        artifact_service=ArtifactService(),
        runtime_router=VoiceRuntime(),
    )
    voices._get_profile_or_raise = lambda _profile_id: SimpleNamespace(id="voice-1")

    accepted = voices.submit_preview_voice(
        VoicePreviewRequest(profile_id="voice-1", text="hello", speed=1.0)
    )

    assert accepted.state in {"running", "completed"}
    _wait_for(service, accepted.task_id, "completed")
    completed = service.get_task(accepted.task_id)
    assert completed.stage == "preview"
