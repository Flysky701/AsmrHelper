"""A workspace restart must neither retarget active work nor admit new work."""
import pytest
from src.app.errors import AppValidationError
from src.app.services.task_service import TaskService


def test_restart_rejects_pending_and_running_tasks_then_reserves_submission_boundary():
    service = TaskService()
    spec, _ = service.create_task_spec(task_type='pipeline', task_source='test', session_id='test')
    assert not service.workspace_switch_ready()
    assert not service.prepare_workspace_switch()
    service.start_task(spec.task_id)
    assert not service.prepare_workspace_switch()
    service.complete_task(spec.task_id)
    assert service.workspace_switch_ready()
    assert service.prepare_workspace_switch()
    with pytest.raises(AppValidationError, match='重启'):
        service.create_task_spec(task_type='pipeline', task_source='test', session_id='test')
    with pytest.raises(AppValidationError, match='重启'):
        service.retry_task(spec.task_id)


def test_runtime_children_ignore_inherited_cache_locations(monkeypatch, tmp_path):
    from src.core.runtime.profiles import RuntimeProfileResolver
    for name in ('PIP_CACHE_DIR', 'UV_CACHE_DIR', 'HF_HOME', 'TORCH_HOME', 'TEMP', 'TMP'):
        monkeypatch.setenv(name, str(tmp_path / 'foreign'))
    root = tmp_path / '中文 workspace'
    monkeypatch.setenv('ASMR_HELPER_TEMP_ROOT', str(root / 'custom temporary'))
    environment = RuntimeProfileResolver(root).subprocess_env()
    for name in ('PIP_CACHE_DIR', 'UV_CACHE_DIR', 'HF_HOME', 'TORCH_HOME', 'TEMP', 'TMP'):
        from pathlib import Path
        assert Path(environment[name]).is_relative_to(root)
