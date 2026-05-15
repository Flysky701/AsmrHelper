from click.testing import CliRunner
import pytest
import threading


def test_app_package_re_exports_phase1_contract():
    import src.app as app_module
    from src.app import dto
    from src.app.dto import (
        ArtifactSet,
        ModelStatusView,
        ModelSummary,
        PipelineRequest,
        PipelineResult,
        ResourceStatus,
        SubtitleDocument,
        SubtitleSegment,
        SynthesisResult,
        TaskStatus,
        TranslationResult,
    )
    from src.app.errors import (
        AppError,
        AppExecutionError,
        AppValidationError,
        ResourceUnavailableError,
        ResourceValidationError,
    )
    from src.app.services.model_service import ModelService, get_model_service
    from src.app.services.pipeline_service import PipelineService, get_pipeline_service
    from src.app.services.resource_service import ResourceService, get_resource_service
    from src.app.services.subtitle_service import SubtitleService, get_subtitle_service
    from src.app.services.task_service import TaskService, get_task_service

    expected_dto_exports = {
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
    }
    expected_app_bindings = {
        "ArtifactSet": ArtifactSet,
        "ModelService": ModelService,
        "ModelStatusView": ModelStatusView,
        "ModelSummary": ModelSummary,
        "PipelineRequest": PipelineRequest,
        "PipelineResult": PipelineResult,
        "PipelineService": PipelineService,
        "ResourceService": ResourceService,
        "ResourceStatus": ResourceStatus,
        "ResourceUnavailableError": ResourceUnavailableError,
        "ResourceValidationError": ResourceValidationError,
        "SubtitleDocument": SubtitleDocument,
        "SubtitleSegment": SubtitleSegment,
        "SubtitleService": SubtitleService,
        "SynthesisResult": SynthesisResult,
        "TaskService": TaskService,
        "TaskStatus": TaskStatus,
        "TranslationResult": TranslationResult,
        "AppError": AppError,
        "AppExecutionError": AppExecutionError,
        "AppValidationError": AppValidationError,
        "get_model_service": get_model_service,
        "get_pipeline_service": get_pipeline_service,
        "get_resource_service": get_resource_service,
        "get_subtitle_service": get_subtitle_service,
        "get_task_service": get_task_service,
    }

    assert set(dto.__all__) == expected_dto_exports
    assert set(expected_app_bindings).issubset(set(app_module.__all__))
    assert issubclass(app_module.ResourceValidationError, Exception)

    for name, expected_object in expected_app_bindings.items():
        assert getattr(app_module, name) is expected_object


def test_services_package_exports_phase1_service_bindings():
    import src.app.services as services_module
    from src.app.services.model_service import ModelService, get_model_service
    from src.app.services.pipeline_service import PipelineService, get_pipeline_service
    from src.app.services.resource_service import ResourceService, get_resource_service
    from src.app.services.subtitle_service import SubtitleService, get_subtitle_service
    from src.app.services.task_service import TaskService, get_task_service

    expected_service_bindings = {
        "ModelService": ModelService,
        "PipelineService": PipelineService,
        "ResourceService": ResourceService,
        "SubtitleService": SubtitleService,
        "TaskService": TaskService,
        "get_model_service": get_model_service,
        "get_pipeline_service": get_pipeline_service,
        "get_resource_service": get_resource_service,
        "get_subtitle_service": get_subtitle_service,
        "get_task_service": get_task_service,
    }

    assert set(services_module.__all__) == set(expected_service_bindings)

    for name, expected_object in expected_service_bindings.items():
        assert getattr(services_module, name) is expected_object


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

    monkeypatch.setattr("src.app.services.pipeline_service.Pipeline", DummyPipeline)

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

    monkeypatch.setattr("src.app.services.pipeline_service.Pipeline", DummyPipeline)

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

    monkeypatch.setattr("src.app.services.pipeline_service.Pipeline", DummyPipeline)

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
