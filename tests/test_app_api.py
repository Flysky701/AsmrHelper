import importlib
import sys
from pathlib import Path

from click.testing import CliRunner
import pytest
import threading


def _purge_modules(*module_prefixes: str) -> None:
    for module_name in list(sys.modules):
        if any(
            module_name == prefix or module_name.startswith(f"{prefix}.")
            for prefix in module_prefixes
        ):
            sys.modules.pop(module_name, None)


class _DummyPipelineConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _patch_pipeline_runtime(monkeypatch, pipeline_cls) -> None:
    import src.app.services.pipeline_service as pipeline_service_module

    monkeypatch.setattr(
        pipeline_service_module,
        "PipelineConfig",
        _DummyPipelineConfig,
        raising=False,
    )
    monkeypatch.setattr(
        pipeline_service_module,
        "Pipeline",
        pipeline_cls,
        raising=False,
    )


def test_app_package_dto_and_error_exports_do_not_import_core_runtime():
    _purge_modules("src.app")

    importlib.import_module("src")
    baseline_core_modules = {
        module_name
        for module_name in sys.modules
        if module_name == "src.core" or module_name.startswith("src.core.")
    }

    app_module = importlib.import_module("src.app")

    assert "src.app.services" not in sys.modules

    assert app_module.ArtifactSet.__name__ == "ArtifactSet"
    assert app_module.AppValidationError.__name__ == "AppValidationError"
    assert "src.app.dto" in sys.modules
    assert "src.app.errors" in sys.modules
    assert "src.app.services" not in sys.modules
    assert {
        module_name
        for module_name in sys.modules
        if module_name == "src.core" or module_name.startswith("src.core.")
    } == baseline_core_modules


def test_services_package_import_is_lazy_until_service_exports_are_requested():
    _purge_modules("src.app", "src.core")

    services_module = importlib.import_module("src.app.services")

    assert "src.core" not in sys.modules
    assert "src.app.services.model_service" not in sys.modules
    assert "src.app.services.pipeline_service" not in sys.modules
    assert "src.app.services.resource_service" not in sys.modules

    resource_service = services_module.ResourceService

    assert resource_service.__name__ == "ResourceService"
    assert "src.app.services.resource_service" in sys.modules
    assert "src.app.services.model_service" not in sys.modules
    assert "src.app.services.pipeline_service" not in sys.modules
    assert "src.core" not in sys.modules


def test_app_package_re_exports_phase1_contract():
    import src.app as app_module
    from src.app import dto
    from src.app.dto import (
        ArtifactSet,
        BatchItemResult,
        Job,
        BatchPipelineRequest,
        BatchPipelineResult,
        ModelOperationResult,
        ModelStatusView,
        ModelSummary,
        PipelineRequest,
        PipelineResult,
        ResourceStatus,
        ScriptSubtitleRequest,
        ScriptSubtitleResult,
        SubtitleDocument,
        SubtitleSegment,
        SynthesisResult,
        TaskStatus,
        TranscriptionResult,
        TranslationResult,
        ModelVerificationResult,
    )
    from src.app.errors import (
        AppError,
        AppExecutionError,
        AppValidationError,
        ResourceUnavailableError,
        ResourceValidationError,
    )
    from src.app.services.asr_service import AsrService, get_asr_service
    from src.app.services.batch_pipeline_service import (
        BatchPipelineService,
        get_batch_pipeline_service,
    )
    from src.app.services.model_service import ModelService, get_model_service
    from src.app.services.pipeline_service import PipelineService, get_pipeline_service
    from src.app.services.resource_service import ResourceService, get_resource_service
    from src.app.services.script_subtitle_service import (
        ScriptSubtitleService,
        get_script_subtitle_service,
    )
    from src.app.services.subtitle_service import SubtitleService, get_subtitle_service
    from src.app.services.task_service import TaskService, get_task_service
    from src.app.services.translation_service import TranslationService, get_translation_service
    from src.app.services.tts_service import TtsService, get_tts_service
    from src.app.services.audio_tool_service import AudioToolService, get_audio_tool_service
    from src.app.services.voice_service import VoiceService, get_voice_service
    from src.app.services.job_service import JobService, get_job_service
    from src.app.services.queue_runner import QueueRunner, get_queue_runner

    expected_dto_exports = {
        "Job",
        "SubtitleSegment",
        "SubtitleDocument",
        "PipelineRequest",
        "PipelineResult",
        "ArtifactSet",
        "BatchPipelineRequest",
        "BatchItemResult",
        "BatchPipelineResult",
        "ScriptSubtitleRequest",
        "ScriptSubtitleResult",
        "ConvertRequest",
        "ConvertResult",
        "SeparationRequest",
        "SeparationResult",
        "SplitRequest",
        "SplitResult",
        "SplitSegment",
        "SubtitleTranslationRequest",
        "SubtitleTranslationResult",
        "VolumePreviewRequest",
        "VolumePreviewResult",
        "SegmentAnalyzeRequest",
        "SegmentAnalyzeResult",
        "SegmentInfo",
        "VoiceCloneRequest",
        "VoiceCloneResult",
        "VoiceDesignRequest",
        "VoiceDesignResult",
        "VoiceProfileSummary",
        "VoiceProfileView",
        "VoicePreviewRequest",
        "VoicePreviewResult",
        "TaskStatus",
        "TranslationResult",
        "SynthesisResult",
        "ResourceStatus",
        "ModelSummary",
        "ModelStatusView",
        "ModelOperationResult",
        "ModelVerificationResult",
        "TranscriptionResult",
    }
    expected_app_bindings = {
        "AsrService": AsrService,
        "AudioToolService": AudioToolService,
        "Job": Job,
        "JobService": JobService,
        "VoiceService": VoiceService,
        "ArtifactSet": ArtifactSet,
        "BatchItemResult": BatchItemResult,
        "BatchPipelineRequest": BatchPipelineRequest,
        "BatchPipelineResult": BatchPipelineResult,
        "BatchPipelineService": BatchPipelineService,
        "ModelService": ModelService,
        "ModelOperationResult": ModelOperationResult,
        "ModelStatusView": ModelStatusView,
        "ModelSummary": ModelSummary,
        "PipelineRequest": PipelineRequest,
        "PipelineResult": PipelineResult,
        "PipelineService": PipelineService,
        "QueueRunner": QueueRunner,
        "ResourceService": ResourceService,
        "ResourceStatus": ResourceStatus,
        "ResourceUnavailableError": ResourceUnavailableError,
        "ResourceValidationError": ResourceValidationError,
        "ScriptSubtitleRequest": ScriptSubtitleRequest,
        "ScriptSubtitleResult": ScriptSubtitleResult,
        "ScriptSubtitleService": ScriptSubtitleService,
        "SubtitleDocument": SubtitleDocument,
        "SubtitleSegment": SubtitleSegment,
        "SubtitleService": SubtitleService,
        "SynthesisResult": SynthesisResult,
        "TaskService": TaskService,
        "TaskStatus": TaskStatus,
        "TranscriptionResult": TranscriptionResult,
        "TranslationService": TranslationService,
        "TranslationResult": TranslationResult,
        "TtsService": TtsService,
        "AppError": AppError,
        "AppExecutionError": AppExecutionError,
        "AppValidationError": AppValidationError,
        "get_asr_service": get_asr_service,
        "get_audio_tool_service": get_audio_tool_service,
        "get_batch_pipeline_service": get_batch_pipeline_service,
        "get_job_service": get_job_service,
        "get_model_service": get_model_service,
        "get_pipeline_service": get_pipeline_service,
        "get_queue_runner": get_queue_runner,
        "get_resource_service": get_resource_service,
        "get_script_subtitle_service": get_script_subtitle_service,
        "get_subtitle_service": get_subtitle_service,
        "get_task_service": get_task_service,
        "get_translation_service": get_translation_service,
        "get_tts_service": get_tts_service,
        "get_voice_service": get_voice_service,
    }

    assert set(dto.__all__) == expected_dto_exports
    assert set(app_module.__all__) == set(expected_app_bindings)
    assert issubclass(app_module.ResourceValidationError, Exception)

    for name, expected_object in expected_app_bindings.items():
        assert getattr(app_module, name) is expected_object


def test_services_package_exports_phase1_service_bindings():
    import src.app.services as services_module
    from src.app.services.asr_service import AsrService, get_asr_service
    from src.app.services.batch_pipeline_service import (
        BatchPipelineService,
        get_batch_pipeline_service,
    )
    from src.app.services.model_service import ModelService, get_model_service
    from src.app.services.pipeline_service import PipelineService, get_pipeline_service
    from src.app.services.resource_service import ResourceService, get_resource_service
    from src.app.services.script_subtitle_service import (
        ScriptSubtitleService,
        get_script_subtitle_service,
    )
    from src.app.services.subtitle_service import SubtitleService, get_subtitle_service
    from src.app.services.task_service import TaskService, get_task_service
    from src.app.services.translation_service import TranslationService, get_translation_service
    from src.app.services.tts_service import TtsService, get_tts_service
    from src.app.services.audio_tool_service import AudioToolService, get_audio_tool_service
    from src.app.services.voice_service import VoiceService, get_voice_service
    from src.app.services.job_service import JobService, get_job_service
    from src.app.services.queue_runner import QueueRunner, get_queue_runner

    expected_service_bindings = {
        "AsrService": AsrService,
        "AudioToolService": AudioToolService,
        "JobService": JobService,
        "BatchPipelineService": BatchPipelineService,
        "ModelService": ModelService,
        "PipelineService": PipelineService,
        "QueueRunner": QueueRunner,
        "ResourceService": ResourceService,
        "ScriptSubtitleService": ScriptSubtitleService,
        "SubtitleService": SubtitleService,
        "TaskService": TaskService,
        "TranslationService": TranslationService,
        "TtsService": TtsService,
        "VoiceService": VoiceService,
        "get_asr_service": get_asr_service,
        "get_audio_tool_service": get_audio_tool_service,
        "get_batch_pipeline_service": get_batch_pipeline_service,
        "get_job_service": get_job_service,
        "get_model_service": get_model_service,
        "get_pipeline_service": get_pipeline_service,
        "get_queue_runner": get_queue_runner,
        "get_resource_service": get_resource_service,
        "get_script_subtitle_service": get_script_subtitle_service,
        "get_subtitle_service": get_subtitle_service,
        "get_task_service": get_task_service,
        "get_translation_service": get_translation_service,
        "get_tts_service": get_tts_service,
        "get_voice_service": get_voice_service,
    }

    assert set(services_module.__all__) == set(expected_service_bindings)

    for name, expected_object in expected_service_bindings.items():
        assert getattr(services_module, name) is expected_object


def test_new_application_dtos_expose_expected_fields():
    from src.app.dto import (
        ArtifactSet,
        ModelOperationResult,
        ModelVerificationResult,
        ResourceStatus,
        SynthesisResult,
        TaskStatus,
        TranscriptionResult,
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
    model_operation = ModelOperationResult(
        action="install",
        model_id="faster-whisper-base",
        success=True,
        status="installed",
        detail="ready",
    )
    model_verification = ModelVerificationResult(
        model_id="deepseek",
        success=True,
        status="configured",
        detail="api key set",
    )
    transcription = TranscriptionResult(
        segments=[],
        output_path="out/transcript.txt",
        text="hello",
    )

    assert task.task_id == "task-1"
    assert artifact.files["mix"] == "out/final_mix.wav"
    assert translation.provider == "deepseek"
    assert synthesis.output_path.endswith("final.wav")
    assert resource.available is True
    assert model_operation.action == "install"
    assert model_verification.status == "configured"
    assert transcription.output_path.endswith("transcript.txt")


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
    fetched = service.get_task("pipeline-1")
    assert fetched == created
    assert fetched is not created

    fetched.message = "mutated"
    assert service.get_task("pipeline-1").message == ""

    started = service.start_task("pipeline-1", message="running")
    assert started.state == "running"
    assert started.progress == 0.0
    assert started.message == "running"

    updated = service.update_progress("pipeline-1", progress=0.5, message="halfway")
    assert updated.state == "running"
    assert updated.progress == 0.5
    assert updated.message == "halfway"

    completed = service.complete_task("pipeline-1", message="done", detail="out/final_mix.wav")
    assert completed.state == "completed"
    assert completed.progress == 1.0
    assert completed.message == "done"
    assert completed.detail == "out/final_mix.wav"

    failed = service.fail_task("pipeline-1", message="retrying", detail="temporary issue")
    assert failed.state == "failed"
    assert failed.progress == 1.0
    assert failed.message == "retrying"
    assert failed.detail == "temporary issue"

    with pytest.raises(AppValidationError, match="unknown task id: missing-1"):
        service.get_task("missing-1")


def test_task_service_singleton_getter_reuses_instance(monkeypatch):
    import src.app.services.task_service as task_service_module
    from src.app.services import TaskService, get_task_service

    monkeypatch.setattr(task_service_module, "_service", None)

    first = get_task_service()
    second = get_task_service()

    assert isinstance(first, TaskService)
    assert first is second

    task = first.create_task("singleton")
    assert second.get_task(task.task_id).task_id == task.task_id


def test_resource_service_ensures_workspace_with_default_model_root(tmp_path, monkeypatch):
    from src.app.services.resource_service import ResourceService

    monkeypatch.delenv("ASMR_HELPER_MODEL_ROOT", raising=False)

    project_root = tmp_path / "project"
    service = ResourceService(project_root=project_root)

    workspace = service.ensure_workspace()

    assert workspace["project_root"] == project_root
    assert workspace["output_dir"] == project_root / "output"
    assert workspace["models_dir"] == project_root / "models"
    assert workspace["output_dir"].is_dir()
    assert workspace["models_dir"].is_dir()


def test_resource_service_defaults_project_root_to_current_working_directory(
    tmp_path, monkeypatch
):
    from src.app.services.resource_service import ResourceService

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ASMR_HELPER_MODEL_ROOT", raising=False)

    service = ResourceService()
    workspace = service.ensure_workspace()

    assert service.project_root == tmp_path.resolve()
    assert workspace["project_root"] == tmp_path.resolve()
    assert workspace["output_dir"] == tmp_path.resolve() / "output"
    assert workspace["models_dir"] == tmp_path.resolve() / "models"


def test_resource_service_reports_required_resources_with_env_override(tmp_path, monkeypatch):
    from src.app.services.resource_service import ResourceService

    project_root = tmp_path / "project"
    model_root = tmp_path / "shared-models"
    monkeypatch.setenv("ASMR_HELPER_MODEL_ROOT", str(model_root))

    service = ResourceService(project_root=project_root)

    statuses = {status.name: status for status in service.check_required_resources()}

    assert statuses["project_root"].available is True
    assert statuses["output_dir"].available is True
    assert statuses["models_dir"].available is True
    assert statuses["models_dir"].metadata["path"] == str(model_root)


def test_resource_service_singleton_getter_reuses_instance(monkeypatch):
    import src.app.services.resource_service as resource_service_module
    from src.app.services import ResourceService, get_resource_service

    monkeypatch.setattr(resource_service_module, "_service", None)

    first = get_resource_service()
    second = get_resource_service()

    assert isinstance(first, ResourceService)
    assert first is second


def test_resource_service_singleton_getter_uses_cwd_on_first_initialization(
    tmp_path, monkeypatch
):
    import src.app.services.resource_service as resource_service_module
    from src.app.services import get_resource_service

    first_cwd = tmp_path / "first-workspace"
    second_cwd = tmp_path / "second-workspace"
    first_cwd.mkdir()
    second_cwd.mkdir()

    monkeypatch.setattr(resource_service_module, "_service", None)
    monkeypatch.delenv("ASMR_HELPER_MODEL_ROOT", raising=False)

    monkeypatch.chdir(first_cwd)
    first = get_resource_service()

    monkeypatch.chdir(second_cwd)
    second = get_resource_service()
    workspace = second.ensure_workspace()

    assert first is second
    assert first.project_root == first_cwd.resolve()
    assert workspace["project_root"] == first_cwd.resolve()
    assert workspace["output_dir"] == first_cwd.resolve() / "output"
    assert workspace["models_dir"] == first_cwd.resolve() / "models"


def test_task_service_create_task_is_safe_for_concurrent_in_process_use():
    from src.app.services.task_service import TaskService

    service = TaskService()
    created_task_ids: list[str] = []
    created_lock = threading.Lock()

    def worker() -> None:
        task = service.create_task("pipeline")
        with created_lock:
            created_task_ids.append(task.task_id)

    threads = [threading.Thread(target=worker) for _ in range(20)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(created_task_ids) == 20
    assert len(set(created_task_ids)) == 20


def test_job_service_cancel_jobs_only_cancels_pending_jobs():
    from src.app.services.job_service import JobService

    service = JobService()
    pending = service.create_job("pending.wav", "pending.wav")
    running = service.create_job("running.wav", "running.wav")
    service.update_status(running.job_id, status="running", stage="processing", progress=0.5)

    cancelled = service.cancel_jobs([pending.job_id, running.job_id])

    assert [job.job_id for job in cancelled] == [pending.job_id]
    assert service.get_job(pending.job_id).status == "cancelled"
    assert service.get_job(pending.job_id).stage == "cancelled"
    assert service.get_job(running.job_id).status == "running"


def test_job_service_create_job_normalizes_wrapped_source_paths():
    from src.app.services.job_service import JobService

    service = JobService()
    job = service.create_job(
        '"D:\\WorkSpace\\AsmrHelper\\功能测试素材\\tc2\\sample.mp3"',
        '"sample.mp3"',
    )

    assert job.source_file == r"D:\WorkSpace\AsmrHelper\功能测试素材\tc2\sample.mp3"
    assert job.source_name == "sample.mp3"


def test_queue_runner_auto_start_submits_only_newly_started_jobs(monkeypatch):
    from src.app.dto.job import Job
    from src.app.services.queue_runner import QueueRunner

    newly_started = Job(
        job_id="new-job",
        job_type="pipeline",
        source_file="new.wav",
        source_name="new.wav",
        status="running",
        created_at=1.0,
    )

    class DummyJobs:
        def start_pending(self, max_concurrent=2):
            return [newly_started]

    runner = QueueRunner(job_service=None, pipeline_service=object(), max_concurrent=2)
    runner._jobs = DummyJobs()
    submitted: list[str] = []

    monkeypatch.setattr(runner, "_submit", lambda job: submitted.append(job.job_id))

    runner._auto_start()

    assert submitted == ["new-job"]


def test_queue_runner_run_job_updates_running_state_and_task_id():
    from src.app.dto import ArtifactSet, PipelineResult
    from src.app.services.job_service import JobService
    from src.app.services.queue_runner import QueueRunner

    class DummyPipelineService:
        def run_audio_pipeline(self, request):
            return PipelineResult(
                success=True,
                input_path=request.input_path,
                task_id="pipeline-task-1",
                artifacts=ArtifactSet(files={"mix": "out/final_mix.wav"}, primary_output="out/final_mix.wav"),
            )

    jobs = JobService()
    job = jobs.create_job("demo.wav", "demo.wav")
    jobs.start_pending(max_concurrent=1)

    runner = QueueRunner(job_service=jobs, pipeline_service=DummyPipelineService(), max_concurrent=1)
    runner._run_job(job.job_id)

    updated = jobs.get_job(job.job_id)
    assert updated is not None
    assert updated.status == "completed"
    assert updated.stage == "done"
    assert updated.progress == 1.0
    assert updated.task_id == "pipeline-task-1"
    assert updated.primary_output == "out/final_mix.wav"


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


def test_subtitle_service_load_srt_text_parses_document_segments():
    from src.app.services.subtitle_service import SubtitleService

    content = (
        "1\n"
        "00:00:00,000 --> 00:00:01,250\n"
        "hello\n"
        "\n"
        "2\n"
        "00:00:01,250 --> 00:00:03,500\n"
        "multi-line\n"
        "world\n"
    )

    service = SubtitleService()

    document = service.load_srt_text(content)

    assert len(document.segments) == 2
    assert document.segments[0].start == 0.0
    assert document.segments[0].end == 1.25
    assert document.segments[0].text == "hello"
    assert document.segments[1].start == 1.25
    assert document.segments[1].end == 3.5
    assert document.segments[1].text == "multi-line\nworld"


def test_subtitle_service_export_srt_text_formats_document():
    from src.app.dto import SubtitleDocument, SubtitleSegment
    from src.app.services.subtitle_service import SubtitleService

    document = SubtitleDocument(
        segments=[
            SubtitleSegment(start=0.0, end=1.25, text="hello"),
            SubtitleSegment(start=1.25, end=3.5, text="multi-line\nworld"),
        ]
    )

    service = SubtitleService()

    exported = service.export_srt_text(document)

    assert exported == (
        "1\n"
        "00:00:00,000 --> 00:00:01,250\n"
        "hello\n"
        "\n"
        "2\n"
        "00:00:01,250 --> 00:00:03,500\n"
        "multi-line\n"
        "world\n"
    )


def test_subtitle_service_load_srt_text_round_trips_segment_text_with_blank_lines():
    from src.app.dto import SubtitleDocument, SubtitleSegment
    from src.app.services.subtitle_service import SubtitleService

    document = SubtitleDocument(
        segments=[
            SubtitleSegment(start=0.0, end=1.25, text="hello\n\nworld"),
            SubtitleSegment(start=1.25, end=2.0, text="tail"),
        ]
    )

    service = SubtitleService()

    exported = service.export_srt_text(document)
    restored = service.load_srt_text(exported)

    assert restored.segments == document.segments


def test_subtitle_service_load_srt_text_skips_malformed_timestamp_cues():
    from src.app.services.subtitle_service import SubtitleService

    content = (
        "1\n"
        "00:00:00,000 --> 00:00:01,000\n"
        "alpha\n"
        "\n"
        "2\n"
        "not-a-time --> 00:00:02,000\n"
        "broken\n"
        "\n"
        "3\n"
        "00:00:02,500 --> 00:00:03,750\n"
        "omega\n"
    )

    service = SubtitleService()

    document = service.load_srt_text(content)

    assert len(document.segments) == 2
    assert document.segments[0].text == "alpha"
    assert document.segments[1].start == 2.5
    assert document.segments[1].end == 3.75
    assert document.segments[1].text == "omega"


def test_subtitle_service_load_srt_text_does_not_treat_arrow_text_as_new_cue():
    from src.app.services.subtitle_service import SubtitleService

    content = (
        "1\n"
        "00:00:00,000 --> 00:00:01,500\n"
        "look --> there\n"
        "still same cue\n"
        "\n"
        "2\n"
        "00:00:01,500 --> 00:00:02,000\n"
        "tail\n"
    )

    service = SubtitleService()

    document = service.load_srt_text(content)

    assert len(document.segments) == 2
    assert document.segments[0].text == "look --> there\nstill same cue"
    assert document.segments[1].text == "tail"


def test_subtitle_service_load_srt_text_does_not_treat_numeric_text_and_arrow_text_as_new_cue():
    from src.app.services.subtitle_service import SubtitleService

    content = (
        "1\n"
        "00:00:00,000 --> 00:00:02,000\n"
        "123\n"
        "look --> there\n"
        "still same cue\n"
        "\n"
        "2\n"
        "00:00:02,000 --> 00:00:03,000\n"
        "tail\n"
    )

    service = SubtitleService()

    document = service.load_srt_text(content)

    assert len(document.segments) == 2
    assert document.segments[0].text == "123\nlook --> there\nstill same cue"
    assert document.segments[1].text == "tail"


def test_asr_service_transcribes_file_through_core_runtime(monkeypatch, tmp_path):
    from src.app.dto import TranscriptionResult
    from src.app.services.asr_service import AsrService

    input_path = tmp_path / "demo.wav"
    input_path.write_bytes(b"audio")
    captured = {}

    class DummyRecognizer:
        def __init__(self, model_size, language, disable_vad=True):
            captured["init"] = (model_size, language, disable_vad)

        def recognize(self, audio_path, output_path=None):
            captured["recognize"] = (audio_path, output_path)
            return [
                {"start": 0.0, "end": 1.25, "text": "hello"},
                {"start": 1.25, "end": 2.5, "text": "world"},
            ]

    monkeypatch.setattr("src.core.asr.ASRRecognizer", DummyRecognizer)

    result = AsrService().transcribe_file(
        input_path=str(input_path),
        output_path="out/transcript.txt",
        model="small",
        language="en",
    )

    assert captured["init"] == ("small", "en", True)
    assert captured["recognize"] == (str(input_path), "out/transcript.txt")
    assert result == TranscriptionResult(
        segments=result.segments,
        output_path="out/transcript.txt",
        text="hello\nworld",
    )
    assert [segment.text for segment in result.segments] == ["hello", "world"]


def test_translation_service_translates_file_through_core_runtime(monkeypatch, tmp_path):
    from src.app.dto import TranslationResult
    from src.app.services.translation_service import TranslationService

    input_path = tmp_path / "demo.txt"
    output_path = tmp_path / "translated.txt"
    input_path.write_text("line 1\n\nline 2\n", encoding="utf-8")
    captured = {}

    class DummyTranslator:
        def __init__(self, provider):
            captured["provider"] = provider

        def translate_batch(self, texts, source_lang="ja", target_lang="zh"):
            captured["translate_batch"] = (texts, source_lang, target_lang)
            return ["L1", "L2"]

    monkeypatch.setattr("src.core.translate.Translator", DummyTranslator)

    result = TranslationService().translate_file(
        input_path=str(input_path),
        output_path=str(output_path),
        provider="openai",
        source_lang="en",
        target_lang="zh",
    )

    assert captured["provider"] == "openai"
    assert captured["translate_batch"] == (["line 1", "line 2"], "en", "zh")
    assert output_path.read_text(encoding="utf-8") == "L1\nL2"
    assert result == TranslationResult(
        items=["L1", "L2"],
        provider="openai",
        source_lang="en",
        target_lang="zh",
    )


def test_tts_service_synthesizes_file_through_core_runtime(monkeypatch, tmp_path):
    from src.app.dto import SynthesisResult
    from src.app.services.tts_service import TtsService

    input_path = tmp_path / "demo.txt"
    output_path = tmp_path / "demo.wav"
    input_path.write_text("hello world", encoding="utf-8")
    captured = {}

    class DummyTTSEngine:
        def __init__(self, engine, voice):
            captured["init"] = (engine, voice)

        def synthesize(self, text, current_output_path):
            captured["synthesize"] = (text, current_output_path)
            return current_output_path

    monkeypatch.setattr("src.core.tts.TTSEngine", DummyTTSEngine)

    result = TtsService().synthesize_file(
        input_path=str(input_path),
        output_path=str(output_path),
        engine="edge",
        voice="zh-CN-XiaoxiaoNeural",
    )

    assert captured["init"] == ("edge", "zh-CN-XiaoxiaoNeural")
    assert captured["synthesize"] == ("hello world", str(output_path))
    assert result == SynthesisResult(
        engine="edge",
        voice="zh-CN-XiaoxiaoNeural",
        output_path=str(output_path),
    )


def test_standalone_services_map_missing_inputs_to_validation_errors(tmp_path):
    from src.app.errors import AppValidationError
    from src.app.services.asr_service import AsrService
    from src.app.services.translation_service import TranslationService
    from src.app.services.tts_service import TtsService

    missing_audio = tmp_path / "missing.wav"
    missing_text = tmp_path / "missing.txt"

    with pytest.raises(AppValidationError, match="input file does not exist"):
        AsrService().transcribe_file(str(missing_audio))

    with pytest.raises(AppValidationError, match="input file does not exist"):
        TranslationService().translate_file(str(missing_text))

    with pytest.raises(AppValidationError, match="input file does not exist"):
        TtsService().synthesize_file(str(missing_text), str(tmp_path / "demo.wav"))


def test_cli_asr_translate_and_tts_use_application_services(monkeypatch, tmp_path):
    from src.cli import cli

    input_audio = tmp_path / "demo.wav"
    input_text = tmp_path / "demo.txt"
    input_audio.write_bytes(b"audio")
    input_text.write_text("line 1\nline 2\n", encoding="utf-8")
    captured = {"asr": None, "translate": None, "tts": None}

    class DummyAsrService:
        def transcribe_file(self, input_path, output_path=None, model="base", language="ja"):
            captured["asr"] = (input_path, output_path, model, language)
            return type(
                "TranscriptionResult",
                (),
                {"segments": [object(), object()], "output_path": output_path, "text": "hello\nworld"},
            )()

    class DummyTranslationService:
        def translate_file(self, input_path, output_path=None, provider="deepseek", source_lang="ja", target_lang="zh"):
            captured["translate"] = (input_path, output_path, provider, source_lang, target_lang)
            return type(
                "TranslationResult",
                (),
                {"items": ["L1", "L2"], "provider": provider, "source_lang": source_lang, "target_lang": target_lang},
            )()

    class DummyTtsService:
        def synthesize_file(self, input_path, output_path, engine="edge", voice="zh-CN-XiaoxiaoNeural"):
            captured["tts"] = (input_path, output_path, engine, voice)
            return type(
                "SynthesisResult",
                (),
                {"engine": engine, "voice": voice, "output_path": output_path},
            )()

    monkeypatch.setattr("src.cli.get_asr_service", lambda: DummyAsrService())
    monkeypatch.setattr("src.cli.get_translation_service", lambda: DummyTranslationService())
    monkeypatch.setattr("src.cli.get_tts_service", lambda: DummyTtsService())

    runner = CliRunner()
    asr_result = runner.invoke(
        cli,
        ["asr", "--input", str(input_audio), "--output", "out/transcript.txt", "--model", "small", "--language", "en"],
    )
    translate_result = runner.invoke(
        cli,
        ["translate", "--input", str(input_text), "--output", "out/translated.txt", "--provider", "openai"],
    )
    tts_result = runner.invoke(
        cli,
        ["tts", "--input", str(input_text), "--output", "out/demo.wav", "--engine", "qwen3", "--voice", "Vivian"],
    )

    assert asr_result.exit_code == 0
    assert translate_result.exit_code == 0
    assert tts_result.exit_code == 0
    assert "Recognition finished, 2 segments" in asr_result.output
    assert "Saved: out/transcript.txt" in asr_result.output
    assert "Saved: out/translated.txt" in translate_result.output
    assert "Saved: out/demo.wav" in tts_result.output
    assert captured["asr"] == (str(input_audio), "out/transcript.txt", "small", "en")
    assert captured["translate"] == (str(input_text), "out/translated.txt", "openai", "ja", "zh")
    assert captured["tts"] == (str(input_text), "out/demo.wav", "qwen3", "Vivian")


def test_cli_helpers_wrap_application_and_unexpected_errors(monkeypatch):
    from src.app.errors import AppValidationError
    from src.cli import cli

    class DummyAsrService:
        def transcribe_file(self, **kwargs):
            raise AppValidationError("missing input file")

    class DummyTtsService:
        def synthesize_file(self, **kwargs):
            raise RuntimeError("audio backend crashed")

    monkeypatch.setattr("src.cli.get_asr_service", lambda: DummyAsrService())
    monkeypatch.setattr("src.cli.get_tts_service", lambda: DummyTtsService())

    runner = CliRunner()
    asr_result = runner.invoke(cli, ["asr", "--input", "missing.wav"])
    tts_result = runner.invoke(cli, ["tts", "--input", "demo.txt", "--output", "out/demo.wav"])

    assert asr_result.exit_code != 0
    assert "Error: missing input file" in asr_result.output
    assert tts_result.exit_code != 0
    assert "Error: audio backend crashed" in tts_result.output


def test_pipeline_service_maps_request_and_result(monkeypatch):
    import inspect

    from src.app.dto import PipelineRequest
    from src.app.services.pipeline_service import PipelineService

    captured = {}

    class DummyPipeline:
        def __init__(self, config):
            captured["config"] = config

        def run(self, preset=None, progress_callback=None):
            captured["preset"] = preset
            captured["progress_callback_arity"] = len(inspect.signature(progress_callback).parameters)
            return {
                "input": "demo.wav",
                "mix_path": "out/demo_mix.wav",
                "exported_subtitle": "out/demo_subtitle.srt",
                "steps": {"asr": {"segments": 2}},
                "total_duration": 3.5,
            }

    _patch_pipeline_runtime(monkeypatch, DummyPipeline)

    request = PipelineRequest(
        input_path="demo.wav",
        output_dir="out",
        vtt_path="demo.vtt",
        source_lang="ja",
        target_lang="zh",
        use_vocal_separator=False,
        tts_engine="edge",
        tts_voice="zh-CN-XiaoxiaoNeural",
        vocal_model="htdemucs",
        asr_model="base",
        translate_provider="deepseek",
        tts_speed=1.1,
        original_volume=0.75,
        tts_volume_ratio=0.6,
        tts_delay=0.0,
        skip_existing=False,
    )

    service = PipelineService()
    result = service.run_audio_pipeline(request)

    assert captured["config"].input_path == "demo.wav"
    assert captured["config"].vtt_path == "demo.vtt"
    assert captured["config"].use_vocal_separator is False
    assert captured["config"].translate_provider == "deepseek"
    assert captured["config"].tts_speed == 1.1
    assert captured["config"].original_volume == 0.75
    assert captured["config"].tts_volume_ratio == 0.6
    assert captured["config"].source_lang == "日文"
    assert captured["config"].target_lang == "中文"
    assert captured["preset"] == "asmr_bilingual"
    assert captured["progress_callback_arity"] == 1
    assert result.success is True
    assert result.mix_path == "out/demo_mix.wav"
    assert result.exported_subtitle == "out/demo_subtitle.srt"
    assert result.task is not None
    assert result.task.task_id == result.task_id
    assert result.task.state == result.task_state


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

    _patch_pipeline_runtime(monkeypatch, DummyPipeline)

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


def test_pipeline_service_orchestrates_workspace_task_lifecycle_and_artifacts(monkeypatch):
    import inspect

    from src.app.dto import PipelineRequest
    from src.app.services.pipeline_service import PipelineService

    captured = {"task_events": []}

    class DummyTaskService:
        def create_task(self, kind):
            captured["task_events"].append(("create", kind))
            return type(
                "Task",
                (),
                {"task_id": "pipeline-1", "state": "pending", "progress": 0.0, "message": "", "detail": ""},
            )()

        def start_task(self, task_id, message=""):
            captured["task_events"].append(("start", task_id, message))
            return type(
                "Task",
                (),
                {"task_id": task_id, "state": "running", "progress": 0.0, "message": message, "detail": ""},
            )()

        def update_progress(self, task_id, progress, message=""):
            captured["task_events"].append(("progress", task_id, progress, message))
            return type(
                "Task",
                (),
                {"task_id": task_id, "state": "running", "progress": progress, "message": message, "detail": ""},
            )()

        def complete_task(self, task_id, message="", detail=""):
            captured["task_events"].append(("complete", task_id, message, detail))
            return type(
                "Task",
                (),
                {"task_id": task_id, "state": "completed", "progress": 1.0, "message": message, "detail": detail},
            )()

    class DummyResourceService:
        def ensure_workspace(self):
            captured["workspace_checked"] = True
            return {
                "project_root": "project-root",
                "output_dir": "workspace-output",
                "models_dir": "workspace-models",
            }

    class DummyPipeline:
        def __init__(self, config):
            captured["config"] = config

        def run(self, preset=None, progress_callback=None):
            captured["preset"] = preset
            captured["progress_callback"] = progress_callback
            captured["progress_callback_arity"] = len(inspect.signature(progress_callback).parameters)
            progress_callback("separating vocals")
            progress_callback("mixing audio")
            return {
                "input": "demo.wav",
                "mix_path": "workspace-output/demo_mix.wav",
                "exported_subtitle": "workspace-output/demo_subtitle.srt",
                "steps": {"mix": {"status": "done"}},
                "total_duration": 12.5,
            }

    _patch_pipeline_runtime(monkeypatch, DummyPipeline)

    request = PipelineRequest(input_path="demo.wav", output_dir="")
    service = PipelineService(
        task_service=DummyTaskService(),
        resource_service=DummyResourceService(),
    )

    result = service.run_audio_pipeline(request)

    assert captured["workspace_checked"] is True
    assert captured["config"].output_dir == "workspace-output"
    assert captured["config"].source_lang == "日文"
    assert captured["config"].target_lang == "中文"
    assert captured["preset"] == "asmr_bilingual"
    assert captured["progress_callback_arity"] == 1
    assert result.success is True
    assert result.task_id == "pipeline-1"
    assert result.task_state == "completed"
    assert result.task is not None
    assert result.task.task_id == "pipeline-1"
    assert result.task.state == "completed"
    assert result.task.progress == 1.0
    assert result.task.message == "pipeline completed"
    assert captured["progress_callback"] is not None
    assert result.artifacts.primary_output == "workspace-output/demo_mix.wav"
    assert result.artifacts.files == {
        "mix": "workspace-output/demo_mix.wav",
        "subtitle": "workspace-output/demo_subtitle.srt",
    }
    assert captured["task_events"] == [
        ("create", "pipeline"),
        ("start", "pipeline-1", "running pipeline"),
        ("progress", "pipeline-1", 0.1, "preparing workspace"),
        ("progress", "pipeline-1", 0.1, "separating vocals"),
        ("progress", "pipeline-1", 0.1, "mixing audio"),
        ("progress", "pipeline-1", 0.9, "pipeline finished"),
        (
            "complete",
            "pipeline-1",
            "pipeline completed",
            "workspace-output/demo_mix.wav",
        ),
    ]


def test_pipeline_service_fails_task_when_pipeline_reports_step_errors(monkeypatch):
    import pytest

    from src.app.dto import PipelineRequest
    from src.app.errors import AppExecutionError
    from src.app.services.pipeline_service import PipelineService

    captured = {"task_events": []}

    class DummyTaskService:
        def create_task(self, kind):
            captured["task_events"].append(("create", kind))
            return type("Task", (), {"task_id": "pipeline-7"})()

        def start_task(self, task_id, message=""):
            captured["task_events"].append(("start", task_id, message))
            return type("Task", (), {"task_id": task_id, "state": "running"})()

        def update_progress(self, task_id, progress, message=""):
            captured["task_events"].append(("progress", task_id, progress, message))
            return type("Task", (), {"task_id": task_id, "state": "running"})()

        def fail_task(self, task_id, message, detail=""):
            captured["task_events"].append(("fail", task_id, message, detail))
            return type("Task", (), {"task_id": task_id, "state": "failed"})()

    class DummyResourceService:
        def ensure_workspace(self):
            return {
                "project_root": "project-root",
                "output_dir": "workspace-output",
                "models_dir": "workspace-models",
            }

    class DummyPipeline:
        def __init__(self, config):
            captured["config"] = config

        def run(self, preset=None, progress_callback=None):
            return {
                "input": "demo.wav",
                "mix_path": "workspace-output/demo_mix.wav",
                "exported_subtitle": "workspace-output/demo_subtitle.srt",
                "steps": {
                    "asr": {"segments": 2},
                    "tts": {"error": "voice synthesis failed", "recoverable": True},
                },
                "total_duration": 9.5,
            }

    _patch_pipeline_runtime(monkeypatch, DummyPipeline)

    service = PipelineService(
        task_service=DummyTaskService(),
        resource_service=DummyResourceService(),
    )

    with pytest.raises(
        AppExecutionError,
        match="pipeline reported step errors: tts: voice synthesis failed",
    ):
        service.run_audio_pipeline(PipelineRequest(input_path="demo.wav", output_dir=""))

    assert captured["config"].output_dir == "workspace-output"
    assert captured["task_events"] == [
        ("create", "pipeline"),
        ("start", "pipeline-7", "running pipeline"),
        ("progress", "pipeline-7", 0.1, "preparing workspace"),
        (
            "fail",
            "pipeline-7",
            "pipeline failed",
            "pipeline reported step errors: tts: voice synthesis failed",
        ),
    ]


def test_pipeline_service_marks_task_failed_when_pipeline_raises(monkeypatch):
    import pytest

    from src.app.dto import PipelineRequest
    from src.app.errors import AppExecutionError
    from src.app.services.pipeline_service import PipelineService

    captured = {"task_events": []}

    class DummyTaskService:
        def create_task(self, kind):
            captured["task_events"].append(("create", kind))
            return type("Task", (), {"task_id": "pipeline-9"})()

        def start_task(self, task_id, message=""):
            captured["task_events"].append(("start", task_id, message))
            return type("Task", (), {"task_id": task_id, "state": "running"})()

        def update_progress(self, task_id, progress, message=""):
            captured["task_events"].append(("progress", task_id, progress, message))
            return type("Task", (), {"task_id": task_id, "state": "running"})()

        def fail_task(self, task_id, message, detail=""):
            captured["task_events"].append(("fail", task_id, message, detail))
            return type("Task", (), {"task_id": task_id, "state": "failed"})()

    class DummyResourceService:
        def ensure_workspace(self):
            captured["workspace_checked"] = True
            return {
                "project_root": "project-root",
                "output_dir": "workspace-output",
                "models_dir": "workspace-models",
            }

    class DummyPipeline:
        def __init__(self, config):
            captured["config"] = config

        def run(self, preset=None, progress_callback=None):
            raise RuntimeError("boom")

    _patch_pipeline_runtime(monkeypatch, DummyPipeline)

    request = PipelineRequest(input_path="demo.wav", output_dir="")
    service = PipelineService(
        task_service=DummyTaskService(),
        resource_service=DummyResourceService(),
    )

    with pytest.raises(AppExecutionError, match="boom"):
        service.run_audio_pipeline(request)

    assert captured["workspace_checked"] is True
    assert captured["config"].output_dir == "workspace-output"
    assert captured["task_events"] == [
        ("create", "pipeline"),
        ("start", "pipeline-9", "running pipeline"),
        ("progress", "pipeline-9", 0.1, "preparing workspace"),
        ("fail", "pipeline-9", "pipeline failed", "boom"),
    ]


def test_pipeline_service_marks_task_failed_when_workspace_setup_raises(monkeypatch):
    import pytest

    from src.app.dto import PipelineRequest
    from src.app.errors import AppExecutionError
    from src.app.services.pipeline_service import PipelineService

    captured = {"task_events": []}

    class DummyTaskService:
        def create_task(self, kind):
            captured["task_events"].append(("create", kind))
            return type("Task", (), {"task_id": "pipeline-3"})()

        def start_task(self, task_id, message=""):
            captured["task_events"].append(("start", task_id, message))
            return type("Task", (), {"task_id": task_id, "state": "running"})()

        def fail_task(self, task_id, message, detail=""):
            captured["task_events"].append(("fail", task_id, message, detail))
            return type("Task", (), {"task_id": task_id, "state": "failed"})()

    class DummyResourceService:
        def ensure_workspace(self):
            raise RuntimeError("workspace unavailable")

    class DummyPipeline:
        def __init__(self, config):
            raise AssertionError("Pipeline should not be constructed when workspace setup fails")

    _patch_pipeline_runtime(monkeypatch, DummyPipeline)

    service = PipelineService(
        task_service=DummyTaskService(),
        resource_service=DummyResourceService(),
    )

    with pytest.raises(AppExecutionError, match="workspace unavailable"):
        service.run_audio_pipeline(PipelineRequest(input_path="demo.wav", output_dir=""))

    assert captured["task_events"] == [
        ("create", "pipeline"),
        ("start", "pipeline-3", "running pipeline"),
        ("fail", "pipeline-3", "pipeline failed", "workspace unavailable"),
    ]


def test_pipeline_service_rejects_unsupported_language_codes():
    from src.app.dto import PipelineRequest
    from src.app.errors import AppValidationError
    from src.app.services.pipeline_service import PipelineService

    service = PipelineService()

    with pytest.raises(AppValidationError, match="unsupported source_lang: fr"):
        service.run_audio_pipeline(PipelineRequest(input_path="demo.wav", source_lang="fr"))

    with pytest.raises(AppValidationError, match="unsupported target_lang: ko"):
        service.run_audio_pipeline(PipelineRequest(input_path="demo.wav", target_lang="ko"))


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
                task=type(
                    "Task",
                    (),
                    {"task_id": "pipeline-1", "state": "completed", "progress": 1.0, "message": "", "detail": ""},
                )(),
                task_id="pipeline-1",
                task_state="completed",
                artifacts=type(
                    "ArtifactSet",
                    (),
                    {
                        "primary_output": "out/final_mix.wav",
                        "files": {
                            "mix": "out/final_mix.wav",
                            "subtitle": "out/final_subtitle.srt",
                        },
                    },
                )(),
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
    assert "Task: pipeline-1 [completed]" in result.output
    assert "Saved: out/final_mix.wav" in result.output
    assert "out/final_mix.wav" in result.output


def test_asmr_bilingual_script_wraps_pipeline_service(monkeypatch, tmp_path, capsys):
    import importlib.util
    import src.app.services as app_services

    script_path = Path("scripts/asmr_bilingual.py")
    input_path = tmp_path / "demo.wav"
    input_path.write_bytes(b"audio")
    vtt_dir = tmp_path / "ASMR_O"
    vtt_dir.mkdir()
    vtt_path = vtt_dir / "demo.wav.vtt"
    vtt_path.write_text("WEBVTT\n", encoding="utf-8")
    captured = {}

    class DummyPipelineService:
        def run_audio_pipeline(self, request):
            captured["request"] = request
            return type(
                "PipelineResult",
                (),
                {
                    "artifacts": type(
                        "ArtifactSet",
                        (),
                        {
                            "primary_output": "out/final_mix.wav",
                            "files": {
                                "mix": "out/final_mix.wav",
                                "subtitle": "out/final_subtitle.srt",
                            },
                        },
                    )(),
                    "mix_path": "out/final_mix.wav",
                    "exported_subtitle": "out/final_subtitle.srt",
                    "error_message": None,
                },
            )()

    monkeypatch.setattr(app_services, "get_pipeline_service", lambda: DummyPipelineService())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "asmr_bilingual.py",
            "--input",
            str(input_path),
            "--tts-engine",
            "qwen3",
            "--skip-existing",
            "--no-vocal",
        ],
    )

    spec = importlib.util.spec_from_file_location("asmr_bilingual_test_module", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    result = module.main()
    stdout = capsys.readouterr().out

    assert result == 0
    assert captured["request"].input_path == str(input_path)
    assert captured["request"].output_dir.endswith("demo_output")
    assert captured["request"].vtt_path == str(vtt_path)
    assert captured["request"].use_vocal_separator is False
    assert captured["request"].tts_engine == "qwen3"
    assert captured["request"].tts_voice == "Vivian"
    assert captured["request"].skip_existing is True
    assert "Pipeline completed." in stdout
    assert "Mix: out/final_mix.wav" in stdout
    assert "Subtitle Output: out/final_subtitle.srt" in stdout


def test_asmr_bilingual_script_reports_missing_input(tmp_path, monkeypatch, capsys):
    import importlib.util

    script_path = Path("scripts/asmr_bilingual.py")
    missing_path = tmp_path / "missing.wav"

    monkeypatch.setattr(sys, "argv", ["asmr_bilingual.py", "--input", str(missing_path)])

    spec = importlib.util.spec_from_file_location("asmr_bilingual_missing_input_module", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    result = module.main()
    stdout = capsys.readouterr().out

    assert result == 1
    assert f"Error: input file does not exist: {missing_path}" in stdout


def test_batch_process_script_wraps_batch_pipeline_service(monkeypatch, tmp_path, capsys):
    import importlib.util
    import src.app.services as app_services
    from src.app.dto import BatchItemResult, BatchPipelineResult

    script_path = Path("scripts/batch_process.py")
    input_path = tmp_path / "demo.wav"
    input_path.write_bytes(b"audio")
    output_base_dir = tmp_path / "batch-output"
    captured = {}

    class DummyBatchPipelineService:
        def run_batch(self, request, progress_callback=None):
            captured["request"] = request
            return BatchPipelineResult(
                items=[
                    BatchItemResult(
                        file=str(input_path),
                        status="success",
                        output=str(output_base_dir / "demo" / "final_mix.wav"),
                        duration=1.25,
                    )
                ],
                total_count=1,
                success_count=1,
                total_duration=1.25,
            )

    monkeypatch.setattr(
        app_services,
        "get_batch_pipeline_service",
        lambda: DummyBatchPipelineService(),
    )

    spec = importlib.util.spec_from_file_location("batch_process_test_module", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    result = module.process_single_file(
        input_path,
        output_base_dir=output_base_dir,
        skip_existing=False,
        tts_engine="qwen3",
        tts_voice="Vivian",
        tts_speed=1.2,
        original_volume=0.7,
        tts_ratio=0.45,
        tts_delay=125,
        vocal_model="hdemucs_mmi",
        asr_model="small",
    )
    stdout = capsys.readouterr().out

    assert result["status"] == "success"
    assert result["output"] == str(output_base_dir / "demo" / "final_mix.wav")
    assert captured["request"].input_files == [str(input_path)]
    assert captured["request"].output_base_dir == str(output_base_dir)
    assert captured["request"].tts_engine == "qwen3"
    assert captured["request"].tts_voice == "Vivian"
    assert captured["request"].tts_speed == 1.2
    assert captured["request"].original_volume == 0.7
    assert captured["request"].tts_volume_ratio == 0.45
    assert captured["request"].tts_delay == 125
    assert captured["request"].vocal_model == "hdemucs_mmi"
    assert captured["request"].asr_model == "small"
    assert captured["request"].skip_existing is False
    assert "[Pipeline] Delegating through the application API..." in stdout


def test_batch_process_script_skips_existing_mix(tmp_path):
    import importlib.util
    from src.app.dto import BatchItemResult, BatchPipelineResult

    script_path = Path("scripts/batch_process.py")
    input_path = tmp_path / "demo.wav"
    input_path.write_bytes(b"audio")
    output_base_dir = tmp_path / "batch-output"
    final_mix = output_base_dir / "demo" / "final_mix.wav"
    final_mix.parent.mkdir(parents=True)
    final_mix.write_bytes(b"mix")

    class DummyBatchPipelineService:
        def run_batch(self, request, progress_callback=None):
            return BatchPipelineResult(
                items=[
                    BatchItemResult(
                        file=str(input_path),
                        status="skipped",
                        output=str(final_mix),
                    )
                ],
                total_count=1,
                skipped_count=1,
            )

    spec = importlib.util.spec_from_file_location("batch_process_skip_module", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(module, "get_batch_pipeline_service", lambda: DummyBatchPipelineService())

    result = module.process_single_file(
        input_path,
        output_base_dir=output_base_dir,
        skip_existing=True,
    )

    assert result["status"] == "skipped"
    assert result["output"] == str(final_mix)
    monkeypatch.undo()


def test_batch_process_collects_results_without_stopping_on_failures(monkeypatch, tmp_path):
    import importlib.util
    from src.app.dto import BatchItemResult, BatchPipelineResult

    script_path = Path("scripts/batch_process.py")
    inputs = [tmp_path / "a.wav", tmp_path / "b.wav", tmp_path / "c.wav"]
    for input_path in inputs:
        input_path.write_bytes(b"audio")

    spec = importlib.util.spec_from_file_location("batch_process_aggregate_module", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    class DummyBatchPipelineService:
        def run_batch(self, request, progress_callback=None):
            items = [
                BatchItemResult(file=str(inputs[0]), status="success", output="a-out", duration=1.0),
                BatchItemResult(file=str(inputs[1]), status="failed", error="boom", duration=2.0),
                BatchItemResult(file=str(inputs[2]), status="skipped", output="c-out", duration=0.5),
            ]
            if progress_callback is not None:
                for index, item in enumerate(items, start=1):
                    progress_callback(index, len(items), item)
            return BatchPipelineResult(
                items=items,
                total_count=3,
                success_count=1,
                failed_count=1,
                skipped_count=1,
            )

    monkeypatch.setattr(module, "get_batch_pipeline_service", lambda: DummyBatchPipelineService())

    results = module.batch_process(
        inputs,
        output_base_dir=tmp_path / "out",
        max_workers=1,
        skip_existing=True,
    )

    assert [result["status"] for result in results] == ["success", "failed", "skipped"]
    assert results[1]["error"] == "boom"
    assert len(results) == 3


def test_cli_pipeline_presets_still_lists_available_presets():
    from src.cli import cli

    class DummyPipelineService:
        def list_presets(self):
            return {
                "asmr_bilingual": "Bilingual pipeline",
                "asr_only": "ASR only",
            }

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("src.cli.get_pipeline_service", lambda: DummyPipelineService())

    runner = CliRunner()
    result = runner.invoke(cli, ["pipeline", "presets"])

    monkeypatch.undo()
    assert result.exit_code == 0
    assert "asmr_bilingual" in result.output
    assert "ASR only" in result.output
