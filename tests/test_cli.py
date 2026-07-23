"""CLI regression tests for canonical task-result output."""

from __future__ import annotations

from unittest.mock import MagicMock

from click.testing import CliRunner

from src.app.dto import PipelineResult, TaskStatus
from src.cli import cli


def test_pipeline_cli_reads_artifacts_from_canonical_task_result(monkeypatch):
    import src.cli as cli_module

    pipeline_service = MagicMock()
    pipeline_service.run_audio_pipeline.return_value = PipelineResult(
        success=True,
        input_path="/test/input.wav",
        task=TaskStatus(task_id="pipeline-1", state="completed"),
        task_id="pipeline-1",
        task_state="completed",
    )
    artifact_service = MagicMock()
    artifact_service.get_task_result_view.return_value = {
        "task_id": "pipeline-1",
        "primary_artifact_id": "artifact-mix",
        "artifacts": [
            {
                "artifact_id": "artifact-mix",
                "type": "audio.mix",
                "path": "/test/output/mix.wav",
            },
            {
                "artifact_id": "artifact-subtitle",
                "type": "subtitle.srt",
                "path": "/test/output/subtitle.srt",
            },
        ],
        "warnings": [],
    }
    monkeypatch.setattr(cli_module, "get_pipeline_service", lambda: pipeline_service)
    monkeypatch.setattr(cli_module, "get_artifact_service", lambda: artifact_service)

    result = CliRunner().invoke(cli, ["pipeline", "run", "--input", "/test/input.wav"])

    assert result.exit_code == 0, result.output
    assert "Saved: /test/output/mix.wav" in result.output
    assert "Mix: /test/output/mix.wav" in result.output
    assert "Subtitle: /test/output/subtitle.srt" in result.output
    artifact_service.get_task_result_view.assert_called_once_with("pipeline-1")
