from __future__ import annotations

import pytest

from src.app.errors import AppValidationError
from src.app.persistence import SqliteStateStore
from src.app.services.artifact_service import ArtifactService
from src.app.services.task_service import TaskService


def test_restart_keeps_terminal_history_and_removes_unfinished_tasks(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    first_store = SqliteStateStore(db_path)
    first_tasks = TaskService(state_store=first_store)
    first_artifacts = ArtifactService(state_store=first_store)

    completed_spec, _ = first_tasks.create_task_spec(
        task_type="tool.convert",
        task_source="test",
        session_id="session-completed",
        input_asset_id="input-completed",
        execution_profile={"format": "wav"},
    )
    first_tasks.start_task(completed_spec.task_id, stage="asr")
    first_artifacts.register_artifact(
        task_id=completed_spec.task_id,
        artifact_type="audio.mix",
        path="C:/output/completed.wav",
        stage="export",
        is_primary=True,
    )
    first_tasks.complete_task(
        completed_spec.task_id,
        stage="export",
        artifact_set_id=completed_spec.task_id,
    )

    running_spec, _ = first_tasks.create_task_spec(
        task_type="tool.convert",
        task_source="test",
        session_id="session-running",
        input_asset_id="input-running",
    )
    first_tasks.start_task(running_spec.task_id, stage="tts")
    first_artifacts.register_artifact(
        task_id=running_spec.task_id,
        artifact_type="audio.tts",
        path="C:/output/incomplete.wav",
        stage="tts",
    )

    restarted_store = SqliteStateStore(db_path)
    restarted_tasks = TaskService(state_store=restarted_store)
    restarted_artifacts = ArtifactService(state_store=restarted_store)

    history = restarted_tasks.list_tasks()
    assert [task.task_id for task in history] == [completed_spec.task_id]
    assert history[0].state == "completed"
    assert restarted_tasks.get_task_spec(completed_spec.task_id).execution_profile == {
        "format": "wav"
    }
    with pytest.raises(AppValidationError, match="unknown task id"):
        restarted_tasks.get_task(running_spec.task_id)

    completed_artifacts = restarted_artifacts.get_task_artifacts(completed_spec.task_id)
    assert completed_artifacts.primary_output == "C:/output/completed.wav"
    assert len(completed_artifacts.entries) == 1
    assert restarted_artifacts.get_task_artifacts(running_spec.task_id).entries == []


def test_restored_task_counter_avoids_terminal_id_collision(tmp_path):
    db_path = tmp_path / "state.sqlite3"
    first = TaskService(state_store=SqliteStateStore(db_path))
    first_spec, _ = first.create_task_spec(
        task_type="tool.convert",
        task_source="test",
        session_id="session-1",
    )
    first.skip_task(first_spec.task_id)

    restarted = TaskService(state_store=SqliteStateStore(db_path))
    next_spec, _ = restarted.create_task_spec(
        task_type="tool.convert",
        task_source="test",
        session_id="session-2",
    )

    assert first_spec.task_id == "tool.convert-1"
    assert next_spec.task_id == "tool.convert-2"
