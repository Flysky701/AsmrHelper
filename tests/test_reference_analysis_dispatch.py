"""Reference analysis must not require visiting a speech page first."""
from unittest.mock import Mock

import pytest

from src.app.errors import AppValidationError
from src.app.persistence import SqliteStateStore
from src.app.services import speech_service, task_service


def test_fresh_dispatcher_retries_analysis_without_initializing_speech(monkeypatch):
    service = task_service.TaskService()
    monkeypatch.setattr(task_service, "_service", service)
    monkeypatch.setattr(task_service, "_dispatcher", None)
    monkeypatch.setattr(task_service, "_dispatcher_service", None)
    analysis = Mock()
    analysis._execute_reference_analysis.return_value = {"segments": []}
    factory = Mock(return_value=analysis)
    monkeypatch.setattr(speech_service, "get_speech_service", factory)

    dispatcher = task_service.get_task_dispatcher()
    factory.assert_not_called()
    spec, _ = service.create_task_spec(
        task_type="speech.reference_analyze", task_source="test", session_id="test",
        execution_profile={"reference_analysis": {"path": "fixture.wav"}},
    )
    service.start_task(spec.task_id)
    service.fail_task(spec.task_id, message="temporary failure")
    retry = service.retry_task(spec.task_id)
    assert dispatcher.run(retry.task_id) == {"segments": []}
    assert service.get_task(retry.task_id).state == "completed"
    assert service.get_task(spec.task_id).state == "failed"
    factory.assert_called_once()
    executed_spec, _ = analysis._execute_reference_analysis.call_args.args
    assert executed_spec.execution_profile == spec.execution_profile


def test_analysis_registration_does_not_expand_historical_retry(tmp_path):
    store = SqliteStateStore(tmp_path / "tasks.db")
    service = task_service.TaskService(state_store=store)
    spec, _ = service.create_task_spec(
        task_type="speech.reference_analyze", task_source="test", session_id="test",
    )
    service.start_task(spec.task_id)
    service.fail_task(spec.task_id, message="failed")
    restored = task_service.TaskService(state_store=store)
    with pytest.raises(AppValidationError, match="historical tasks"):
        restored.retry_task(spec.task_id)
