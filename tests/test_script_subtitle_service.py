from __future__ import annotations

import time
from pathlib import Path

import pytest

from src.app.dto.script_subtitle import ScriptSubtitleRequest
from src.app.errors import AppValidationError
from src.app.services.script_subtitle_service import ScriptSubtitleService
from src.app.services.artifact_service import ArtifactService
from src.app.services.task_service import TaskService
from src.core.tasks import TaskDispatcher
from src.core.subtitles.script_review import script_fingerprint


class _DummyPipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def run(self, **kwargs):
        self.calls.append(("full", kwargs))
        return kwargs["output_path"]

    def run_from_existing_vtt(self, **kwargs):
        self.calls.append(("from_vtt", kwargs))
        return kwargs["output_path"]

    def run_text_only(self, **kwargs):
        self.calls.append(("text_only", kwargs))
        return "line one\n\nline two\n"


def _patch_pipeline(monkeypatch, pipeline: _DummyPipeline) -> None:
    monkeypatch.setattr(
        ScriptSubtitleService,
        "_build_pipeline",
        lambda self: pipeline,
    )


def test_run_text_only_returns_line_count(monkeypatch, tmp_path):
    script_path = tmp_path / "script.txt"
    script_path.write_text("hello", encoding="utf-8")

    pipeline = _DummyPipeline()
    _patch_pipeline(monkeypatch, pipeline)

    service = ScriptSubtitleService()
    result = service.run_text_only(
        ScriptSubtitleRequest(
            script_path=str(script_path),
            output_path=str(tmp_path / "out.txt"),
        )
    )

    assert result.mode == "text_only"
    assert result.line_count == 2
    assert result.text.startswith("line one")
    assert pipeline.calls[0][0] == "text_only"


def test_task_submission_generates_output_and_registers_artifact(monkeypatch, tmp_path):
    script_path = tmp_path / "script.txt"
    script_path.write_text("hello", encoding="utf-8")
    pipeline = _DummyPipeline()
    _patch_pipeline(monkeypatch, pipeline)
    task_service = TaskService()
    dispatcher = TaskDispatcher(task_service.registry, task_service=task_service)
    artifact_service = ArtifactService()
    service = ScriptSubtitleService(
        task_service=task_service,
        dispatcher=dispatcher,
        artifact_service=artifact_service,
    )

    accepted = service.create_task(
        ScriptSubtitleRequest(
            script_path=str(script_path),
            use_llm_clean=False,
        )
    )

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        task = task_service.get_task(accepted.task_id)
        if task.state == "completed":
            break
        time.sleep(0.01)
    assert task.state == "completed"
    assert task.stage == "script_to_subtitle"
    artifacts = artifact_service.get_task_artifacts(task.task_id)
    assert len(artifacts.entries) == 1
    assert Path(artifacts.entries[0].path).name == "script_cleaned.txt"
    assert Path(artifacts.entries[0].path).parent.parent == tmp_path / ".asmr-script"
    assert artifacts.entries[0].artifact_type == "subtitle.txt"


def test_value_error_from_core_is_mapped_to_validation_error(monkeypatch, tmp_path):
    script_path = tmp_path / "script.txt"
    audio_path = tmp_path / "audio.wav"
    script_path.write_text("hello", encoding="utf-8")
    audio_path.write_bytes(b"audio")

    class _ValueErrorPipeline(_DummyPipeline):
        def run(self, **kwargs):
            raise ValueError("bad format")

    _patch_pipeline(monkeypatch, _ValueErrorPipeline())
    service = ScriptSubtitleService()

    with pytest.raises(AppValidationError, match="bad format"):
        service.run_full(
            ScriptSubtitleRequest(
                script_path=str(script_path),
                audio_path=str(audio_path),
                confirmed_text="hello",
                fingerprint=script_fingerprint(script_path),
                output_path=str(tmp_path / "out.vtt"),
            )
        )
