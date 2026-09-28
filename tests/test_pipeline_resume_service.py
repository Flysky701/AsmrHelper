"""Restart recovery across the real pipeline service/session/executor boundary."""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.app.dto import PipelineRequest
from src.app.errors import AppExecutionError
from src.app.persistence import SqliteStateStore
from src.app.services.artifact_service import ArtifactService
from src.app.services.input_catalog_service import InputCatalogService
from src.app.services.pipeline_service import PipelineService
from src.app.services.pipeline_task_orchestrator import PipelineTaskOrchestrator
from src.app.services.session_service import SessionService
from src.app.services.task_service import TaskService
from src.app.services.workspace_service import WorkspaceService
from src.config import config
from src.core.orchestration.pipeline.executor import PipelineExecutor
from src.core.sessions import WorkspaceContext
from src.core.speech.store import SpeechStore
from src.app.services.speech_service import SpeechService


def test_resume_after_restart_reconstructs_session_and_reuses_asr_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "_config", {"api": {}, "external_tts": {}})
    monkeypatch.setattr(PipelineExecutor, "_try_clear_gpu", staticmethod(lambda: None))
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"original audio bytes")
    calls = []
    first_tts_outputs = []
    speech_store = SpeechStore(tmp_path / "voice-lab")
    connection = speech_store.create("connections", {"name": "Edge", "provider_id": "edge", "deployment": "cloud"})
    recipe = speech_store.create("recipes", {
        "name": "Frozen voice", "voice_id": "voice", "provider_id": "edge", "model": "edge-tts",
        "mode": "builtin", "connection_ref": connection["id"], "language": "ja",
        "variant": {"kind": "builtin", "value": "ja-JP-NanamiNeural", "style": "normal"},
        "provider_options": {"schema_version": 1},
    })

    def transcribe_file(*, input_path, output_path, profile):
        assert Path(input_path) == audio
        calls.append("asr")
        Path(output_path).write_text("spoken", encoding="utf-8")
        return SimpleNamespace(segments=[SimpleNamespace(start=0.0, end=1.0, text="spoken")])

    def fail_synthesis(**kwargs):
        calls.append("failed-tts")
        first_tts_outputs.append(Path(kwargs["output_path"]))
        Path(kwargs["output_path"]).write_bytes(b"partial audio")
        raise RuntimeError("injected synthesis failure")

    def synthesize(**kwargs):
        calls.append("tts")
        assert kwargs["segments"][0]["text"] == "spoken"
        assert kwargs["segments"][0]["start_time"] == 0.0
        Path(kwargs["output_path"]).write_bytes(b"complete audio")

    def make_services(state_store, tts_function):
        task_service = TaskService(state_store=state_store)
        speech = SpeechService(store=SpeechStore(speech_store.root), tasks=task_service,
                               dispatcher=Mock(), artifacts=Mock())
        def synthesize_timeline(snapshot, segments, output_path, task_id, **kwargs):
            assert snapshot["recipe"]["id"] == recipe["id"]
            assert snapshot["connection"]["id"] == connection["id"]
            tts_function(segments=segments, output_path=output_path)
            return {"experiment_id": "experiment-" + task_id, "id": "assembly-" + task_id}
        speech.synthesize_timeline = synthesize_timeline
        monkeypatch.setattr("src.app.services.speech_service.get_speech_service", lambda: speech)
        workspace = WorkspaceContext("test-workspace", str(tmp_path), str(tmp_path / "output"),
                                     str(tmp_path / "temp"), str(tmp_path / "models"))
        workspace_service = WorkspaceService(resolver=Mock(resolve=Mock(return_value=workspace)))
        catalog = InputCatalogService()
        sessions = SessionService(workspace_service=workspace_service, input_catalog_service=catalog)
        artifacts = ArtifactService(state_store=state_store)
        resources = Mock()
        resources.check_task_readiness.return_value = {"ready": True}
        resources.ensure_workspace.return_value = {"output_dir": tmp_path / "output"}
        executor = PipelineExecutor(asr=SimpleNamespace(transcribe_file=transcribe_file),
                                    tts=SimpleNamespace(synthesize_segments=tts_function))
        service = PipelineService(task_service=task_service, resource_service=resources,
                                  workspace_service=workspace_service, input_catalog_service=catalog,
                                  session_service=sessions, artifact_service=artifacts, executor=executor)
        orchestrator = PipelineTaskOrchestrator(pipeline_service=service, task_service=task_service)
        return task_service, service, orchestrator, catalog, sessions, workspace

    db_path = tmp_path / "state.sqlite3"
    tasks, pipeline, orchestrator, _, _, _ = make_services(SqliteStateStore(db_path), fail_synthesis)
    request = PipelineRequest(input_path=str(audio), output_dir=str(tmp_path / "chosen-output"),
                              source_lang="ja", target_lang="ja", use_vocal_separator=False)
    profile = PipelineService._resolve_execution_profile(request)
    profile["stages"]["mix"]["enabled"] = False
    profile["stages"]["tts"] = {"enabled": True, "provider": "speech", "model": None,
                                 "options": {"speech_recipe_id": recipe["id"]}, "provider_options": {}}
    request.execution_profile = profile
    _, first_spec = pipeline.create_pipeline_task(request)
    with pytest.raises(AppExecutionError, match="injected synthesis failure"):
        orchestrator.run_task(first_spec.task_id)
    assert calls == ["asr", "failed-tts"]
    assert tasks.get_task(first_spec.task_id).state == "failed"
    assert tasks.recovery_store.checkpoint(first_spec.task_id, "asr") is not None
    assert tasks.recovery_store.checkpoint(first_spec.task_id, "tts") is None

    # Fresh registries after restart. Occupy old IDs with unrelated assets to
    # detect accidental use of the previous in-memory session/input IDs.
    tasks2, pipeline2, orchestrator2, catalog2, sessions2, workspace2 = make_services(
        SqliteStateStore(db_path), synthesize)
    unrelated = tmp_path / "unrelated.wav"
    unrelated.write_bytes(b"unrelated audio")
    other_asset = catalog2.inspect_paths([str(unrelated)])[0]
    sessions2.create_session(workspace_id=workspace2.workspace_id, mode="single-audio",
                             input_asset_ids=[other_asset.asset_id], primary_input_asset_id=other_asset.asset_id)
    original_status = asdict(tasks2.get_task(first_spec.task_id))
    resumed = pipeline2.resume_pipeline_task(first_spec.task_id)
    resumed_spec = tasks2.get_task_spec(resumed.task_id)
    assert resumed.task_id != first_spec.task_id
    assert resumed_spec.session_id != first_spec.session_id
    assert resumed_spec.input_asset_id != first_spec.input_asset_id
    assert resumed.retry_of_task_id == first_spec.task_id
    result = orchestrator2.run_task(resumed.task_id)

    assert calls == ["asr", "failed-tts", "tts"]
    assert result.success
    assert tasks2.get_task(resumed.task_id).state == "completed"
    assert asdict(tasks2.get_task(first_spec.task_id)) == original_status
    new_output = Path(pipeline2.build_plan(resumed_spec).output_dir)
    assert new_output.is_relative_to(tmp_path / "chosen-output")
    assert resumed.task_id in new_output.parts
    assert first_tts_outputs[0].read_bytes() == b"partial audio"
    restored_asr = tasks2.recovery_store.checkpoint(resumed.task_id, "asr")
    assert Path(restored_asr["files"][0]["original"]).is_relative_to(new_output)
    restored_tts = tasks2.recovery_store.checkpoint(resumed.task_id, "tts")
    tts_output = Path(restored_tts["files"][0]["original"])
    assert tts_output.is_relative_to(new_output)
    assert tts_output.read_bytes() == b"complete audio"
    assert Path(result.exported_subtitle).is_file()
