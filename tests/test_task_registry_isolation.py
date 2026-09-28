"""Task facts must survive mutation of callers' nested snapshots."""

from src.core.tasks.service import TaskRegistry


def test_submission_and_returned_specs_do_not_share_nested_rules():
    registry = TaskRegistry()
    profile = {"speech": {"rules": [{"text": "original"}]}}
    spec, _ = registry.create_task_spec(
        task_type="pipeline", task_source="test", session_id="test",
        execution_profile=profile,
    )
    profile["speech"]["rules"][0]["text"] = "caller changed"
    spec.execution_profile["speech"]["rules"].append({"text": "returned changed"})
    fetched = registry.get_task_spec(spec.task_id)
    assert fetched.execution_profile == {"speech": {"rules": [{"text": "original"}]}}
    fetched.execution_profile["speech"]["rules"].clear()
    assert registry.get_task_spec(spec.task_id).execution_profile["speech"]["rules"]


def test_errors_events_and_rollback_snapshots_are_independent():
    registry = TaskRegistry()
    spec, _ = registry.create_task_spec(task_type="pipeline", task_source="test", session_id="test")
    error = {"details": {"attempts": [1]}}
    failed = registry.fail_task(spec.task_id, "failed", error=error)
    error["details"]["attempts"].append(2)
    failed.error["details"]["attempts"].append(3)
    events = registry.list_events(spec.task_id)
    events[-1].data["error"]["details"]["attempts"].append(4)
    snapshot = registry.snapshot_task_state(spec.task_id)
    snapshot[0].error["details"]["attempts"].append(5)
    snapshot[1][-1].data["error"]["details"]["attempts"].append(6)
    assert registry.get_task(spec.task_id).error == {"details": {"attempts": [1]}}
    assert registry.list_events(spec.task_id)[-1].data["error"] == {"details": {"attempts": [1]}}

    snapshot = registry.snapshot_task_state(spec.task_id)
    registry.restore_task_state(*snapshot)
    snapshot[0].error["details"]["attempts"].clear()
    snapshot[1][-1].data["error"]["details"]["attempts"].clear()
    assert registry.get_task(spec.task_id).error == {"details": {"attempts": [1]}}
    assert registry.list_events(spec.task_id)[-1].data["error"] == {"details": {"attempts": [1]}}


def test_restored_history_and_retry_preserve_original_rules():
    registry = TaskRegistry()
    spec, _ = registry.create_task_spec(
        task_type="pipeline", task_source="test", session_id="test",
        execution_profile={"rules": [{"text": "original"}]},
    )
    failed = registry.fail_task(spec.task_id, "failed", error={"detail": {"values": [1]}})
    restored = TaskRegistry()
    restored.restore_task(spec, failed)
    spec.execution_profile["rules"].clear()
    failed.error["detail"]["values"].clear()
    retried = restored.retry_task(spec.task_id)
    retry_spec = restored.get_task_spec(retried.task_id)
    assert retry_spec.execution_profile == {"rules": [{"text": "original"}]}
    retry_spec.execution_profile["rules"].clear()
    assert restored.get_task_spec(spec.task_id).execution_profile == {"rules": [{"text": "original"}]}
    assert restored.get_task(spec.task_id).error == {"detail": {"values": [1]}}
