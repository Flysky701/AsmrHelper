from click.testing import CliRunner
import pytest


def test_app_package_re_exports_new_dto_and_error_contract():
    from src.app import (
        ArtifactSet,
        ResourceStatus,
        ResourceValidationError,
        TaskService,
        SynthesisResult,
        TaskStatus,
        TranslationResult,
        get_task_service,
    )
    from src.app import dto

    assert ArtifactSet.__name__ == "ArtifactSet"
    assert TaskService.__name__ == "TaskService"
    assert TaskStatus.__name__ == "TaskStatus"
    assert TranslationResult.__name__ == "TranslationResult"
    assert SynthesisResult.__name__ == "SynthesisResult"
    assert ResourceStatus.__name__ == "ResourceStatus"
    assert issubclass(ResourceValidationError, Exception)
    assert callable(get_task_service)
    assert dto.__all__ == [
        "SubtitleSegment",
        "SubtitleDocument",
        "PipelineRequest",
        "PipelineResult",
        "ArtifactSet",
        "TaskStatus",
        "TranslationResult",
        "SynthesisResult",
        "ResourceStatus",
        "ModelSummary",
        "ModelStatusView",
    ]


def test_new_application_dtos_expose_expected_fields():
    from src.app.dto import (
        ArtifactSet,
        ResourceStatus,
        SynthesisResult,
        TaskStatus,
        TranslationResult,
    )

    task = TaskStatus(task_id="task-1", state="pending", progress=0.0, message="queued")
    artifact = ArtifactSet(files={"mix": "out/final_mix.wav"}, primary_output="out/final_mix.wav")
    translation = TranslationResult(
        items=["你好"],
        provider="deepseek",
        source_lang="ja",
        target_lang="zh",
    )
    synthesis = SynthesisResult(
        engine="edge",
        voice="zh-CN-XiaoxiaoNeural",
        output_path="out/final.wav",
    )
    resource = ResourceStatus(name="model_root", available=True, detail="ready")

    assert task.task_id == "task-1"
    assert artifact.files["mix"] == "out/final_mix.wav"
    assert translation.provider == "deepseek"
    assert synthesis.output_path.endswith("final.wav")
    assert resource.available is True


def test_new_resource_validation_error_is_an_app_error():
    from src.app.errors import AppError, ResourceValidationError

    error = ResourceValidationError("missing workspace")

    assert isinstance(error, AppError)
    assert str(error) == "missing workspace"


def test_task_service_tracks_lifecycle_transitions():
    from src.app.errors import AppValidationError
    from src.app.services.task_service import TaskService

    service = TaskService()

    created = service.create_task("pipeline")

    assert created.task_id == "pipeline-1"
    assert created.state == "pending"
    assert created.progress == 0.0
    assert created.message == ""
    assert service.get_task("pipeline-1") == created

    started = service.start("pipeline-1", message="running")
    assert started.state == "running"
    assert started.progress == 0.0
    assert started.message == "running"

    updated = service.update_progress("pipeline-1", progress=0.5, message="halfway")
    assert updated.state == "running"
    assert updated.progress == 0.5
    assert updated.message == "halfway"

    completed = service.complete("pipeline-1", message="done", detail="out/final_mix.wav")
    assert completed.state == "completed"
    assert completed.progress == 1.0
    assert completed.message == "done"
    assert completed.detail == "out/final_mix.wav"

    failed = service.fail("pipeline-1", message="retrying", detail="temporary issue")
    assert failed.state == "failed"
    assert failed.progress == 1.0
    assert failed.message == "retrying"
    assert failed.detail == "temporary issue"

    with pytest.raises(AppValidationError, match="unknown task id: missing-1"):
        service.get_task("missing-1")


def test_task_service_singleton_getter_reuses_instance():
    from src.app.services import TaskService, get_task_service

    service = get_task_service()

    assert isinstance(service, TaskService)
    assert service is get_task_service()


def test_subtitle_service_round_trip_preserves_timestamp_entries():
    from src.app.services.subtitle_service import SubtitleService

    entries = [
        {"start": 0.0, "end": 1.25, "text": "hello"},
        {"start": 1.25, "end": 2.5, "text": "world"},
    ]

    service = SubtitleService()
    document = service.from_timestamp_entries(entries)

    assert document.segments[0].text == "hello"
    assert document.segments[1].end == 2.5

    restored = service.to_timestamp_entries(document)
    assert restored == entries


def test_pipeline_service_maps_request_and_result(monkeypatch):
    from src.app.dto import PipelineRequest
    from src.app.services.pipeline_service import PipelineService

    captured = {}

    class DummyPipeline:
        def __init__(self, config):
            captured["config"] = config

        def run(self, preset=None, progress_callback=None):
            captured["preset"] = preset
            return {
                "input": "demo.wav",
                "mix_path": "out/demo_mix.wav",
                "exported_subtitle": "out/demo_subtitle.srt",
                "steps": {"asr": {"segments": 2}},
                "total_duration": 3.5,
            }

    monkeypatch.setattr("src.app.services.pipeline_service.Pipeline", DummyPipeline)

    request = PipelineRequest(
        input_path="demo.wav",
        output_dir="out",
        source_lang="ja",
        target_lang="zh",
        tts_engine="edge",
        tts_voice="zh-CN-XiaoxiaoNeural",
        vocal_model="htdemucs",
        asr_model="base",
        translate_provider="deepseek",
        tts_delay=0.0,
        skip_existing=False,
    )

    service = PipelineService()
    result = service.run_audio_pipeline(request)

    assert captured["config"].input_path == "demo.wav"
    assert captured["config"].translate_provider == "deepseek"
    assert captured["preset"] == "asmr_bilingual"
    assert result.success is True
    assert result.mix_path == "out/demo_mix.wav"
    assert result.exported_subtitle == "out/demo_subtitle.srt"


def test_pipeline_service_wraps_execution_errors(monkeypatch):
    import pytest

    from src.app.dto import PipelineRequest
    from src.app.errors import AppExecutionError
    from src.app.services.pipeline_service import PipelineService

    class DummyPipeline:
        def __init__(self, config):
            pass

        def run(self, preset=None, progress_callback=None):
            raise RuntimeError("boom")

    monkeypatch.setattr("src.app.services.pipeline_service.Pipeline", DummyPipeline)

    request = PipelineRequest(
        input_path="demo.wav",
        output_dir="out",
        source_lang="ja",
        target_lang="zh",
        tts_engine="edge",
        tts_voice="zh-CN-XiaoxiaoNeural",
        vocal_model="htdemucs",
        asr_model="base",
        translate_provider="deepseek",
        tts_delay=0.0,
        skip_existing=False,
    )

    service = PipelineService()

    with pytest.raises(AppExecutionError):
        service.run_audio_pipeline(request)


def test_cli_pipeline_run_uses_pipeline_service(monkeypatch):
    from src.app.dto import PipelineResult
    from src.cli import cli

    captured = {}

    class DummyPipelineService:
        def run_audio_pipeline(self, request):
            captured["request"] = request
            return PipelineResult(
                success=True,
                input_path=request.input_path,
                mix_path="out/final_mix.wav",
                exported_subtitle="out/final_subtitle.srt",
                steps={"asr": {"segments": 2}},
                total_duration=1.0,
                error_message=None,
            )

    monkeypatch.setattr("src.cli.get_pipeline_service", lambda: DummyPipelineService())

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "pipeline",
            "run",
            "--input",
            "demo.wav",
            "--output",
            "out",
            "--source-lang",
            "ja",
            "--target-lang",
            "zh",
            "--tts-engine",
            "edge",
            "--tts-voice",
            "zh-CN-XiaoxiaoNeural",
            "--vocal-model",
            "htdemucs",
            "--asr-model",
            "base",
            "--translate-provider",
            "deepseek",
        ],
    )

    assert result.exit_code == 0
    assert captured["request"].input_path == "demo.wav"
    assert captured["request"].output_dir == "out"
    assert "out/final_mix.wav" in result.output


def test_cli_pipeline_presets_still_lists_available_presets():
    from src.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["pipeline", "presets"])

    assert result.exit_code == 0
    assert "asmr_bilingual" in result.output
