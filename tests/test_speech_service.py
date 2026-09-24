"""Integration checks for durable candidates and frozen formal dubbing requests."""
from copy import deepcopy
import json
import numpy as np
import pytest
import soundfile as sf

from src.core.speech.store import SpeechStore
from src.app.services.speech_service import SpeechService
from src.app.services.task_service import TaskService
from src.app.services.artifact_service import ArtifactService
from src.core.speech.providers import get_provider


@pytest.fixture
def lab(tmp_path, monkeypatch):
    service = SpeechService(store=SpeechStore(tmp_path / "lab"), tasks=TaskService(), artifacts=ArtifactService())
    connection = service.save_connection({"name": "Test", "provider_id": "edge", "deployment": "cloud"})
    voice = service.store.create("voices", {"name": "Voice", "bindings": [], "default_binding": "edge"})
    recipe = service.save_recipe({"name": "Voice", "voice_id": voice["id"], "provider_id": "edge", "model": "edge-tts", "mode": "builtin",
        "connection_ref": connection["id"], "variant": {"kind": "builtin", "value": "zh-CN-XiaoxiaoNeural", "style": "normal"},
        "language": "zh", "provider_options": {"schema_version": 1}})
    calls = []
    def synthesize(request, path, context, cancel):
        calls.append(deepcopy(request))
        sf.write(path, np.sin(np.arange(2400) / 20).astype("float32") * .05, 24000)
        return {"model": request["model"]}
    monkeypatch.setattr(get_provider("edge"), "synthesize", synthesize)
    return service, recipe, calls


def test_candidates_are_distinct_and_recipe_revision_pinned(lab):
    service, recipe, calls = lab
    plan = service.create_plan({"text": "第一句。第二句。"})
    experiment = service.store.create("experiments", {"name": "Test", "plan_id": plan["id"]})
    snapshot = service.snapshot(recipe["id"])
    newer = service.save_recipe({**recipe, "name": "Edited", "provider_options": {"schema_version": 1, "speed": 1.2}})
    requests = service.compile(recipe["id"], plan["id"])
    takes = service.run_requests(requests, snapshot, task_id="test-task", experiment_id=experiment["id"], plan_id=plan["id"])
    replacement = service.run_requests(requests[:1], snapshot, task_id="new-task", experiment_id=experiment["id"], plan_id=plan["id"])
    assert newer["id"] != recipe["id"] and newer["revision"] == 2
    assert len(service.store.list("takes")) == 3
    assert takes[0]["id"] != replacement[0]["id"]
    assert calls[0]["parameters"]["options"]["speed"] == 1
    for take in takes:
        service.select({"experiment_id": experiment["id"], "segment_id": take["segment_id"], "take_id": take["id"]})
    first = service.assemble(experiment["id"])
    service.select({"experiment_id": experiment["id"], "segment_id": replacement[0]["segment_id"], "take_id": replacement[0]["id"]})
    second = service.assemble(experiment["id"])
    assert first["id"] != second["id"]
    assert first["processing"][1]["take_id"] == second["processing"][1]["take_id"]
    assert first["processing"][0]["take_id"] != second["processing"][0]["take_id"]
    assert service.store.get("assemblies", first["id"])["processing"] == first["processing"]


def test_connection_edit_never_changes_snapshot_or_exposes_key(lab):
    service, _, _ = lab
    conn = service.save_connection({"name": "Fish", "provider_id": "fish_audio", "deployment": "cloud", "base_url": "https://example.com/v1", "api_key": "secret-A"})
    old = deepcopy(conn)
    service.save_connection({"id": conn["id"], "api_key": "secret-B"})
    assert service.connection_context(old)["connection"]["api_key"] == "secret-A"
    assert "secret-A" not in json.dumps(service.library())
    assert "secret-B" not in service.store.path.read_text()


def test_cancel_between_sentences_preserves_only_completed_take(lab):
    service, recipe, calls = lab
    plan = service.create_plan({"text": "第一句。第二句。"})
    with pytest.raises(InterruptedError):
        service.run_requests(service.compile(recipe["id"], plan["id"]), service.snapshot(recipe["id"]),
            task_id="test", experiment_id="test", plan_id=plan["id"], cancel_check=lambda: len(calls) >= 1)
    assert len(calls) == 1
    assert service.store.list("takes") == []


def test_formal_dubbing_uses_same_compiler_and_runner(lab, tmp_path):
    service, recipe, calls = lab
    snapshot = service.snapshot(recipe["id"])
    assembly = service.synthesize_timeline(snapshot, [{"text": "你好。", "start_time": .5, "end_time": 1}], tmp_path / "formal.wav", "formal-task", reference_duration=2)
    assert assembly["duration"] == 2
    assert assembly["processing"][0]["start"] == .5
    assert calls[0]["recipe_id"] == recipe["id"]
    assert sf.info(tmp_path / "formal.wav").duration == 2


def test_invalid_plan_does_not_persist(lab):
    service, _, _ = lab
    with pytest.raises(ValueError):
        service.create_plan({"text": "不能改写。", "segments": [{"id": "a", "start": 1, "end": 5}]})
    assert service.store.list("plans") == []


def test_artifact_registration_failure_does_not_leave_dangling_completed_take(lab, monkeypatch):
    from pathlib import Path
    service, recipe, _ = lab
    plan = service.create_plan({"text": "测试。"})
    def unavailable(**kwargs):
        raise RuntimeError("artifact store unavailable")
    monkeypatch.setattr(service.artifacts, "register_artifact", unavailable)
    with pytest.raises(RuntimeError, match="artifact store"):
        service.run_requests(service.compile(recipe["id"], plan["id"]), service.snapshot(recipe["id"]),
            task_id="test", experiment_id="test", plan_id=plan["id"])
    # Either the completed take is rolled back or its real audio remains playable.
    for take in service.store.list("takes"):
        assert Path(take["audio_path"]).is_file()
        assert sf.info(take["audio_path"]).frames > 0


def test_registered_extra_provider_runs_through_service_without_business_branch(lab, monkeypatch):
    from src.core.speech import providers
    service, _, _ = lab
    class ExtraLocal:
        provider_id, version, remote = "test-extra-local", "test-1", False
        def describe(self):
            return {"provider_id": self.provider_id, "version": self.version}
        def validate(self, recipe, assets):
            if recipe["provider_options"] != {"schema_version": 1}:
                raise ValueError("unsupported options")
        def compile(self, recipe, segment, text, assets):
            return {"text": text, "voice": recipe["variant"]["value"]}
        def probe(self, context):
            return {"ready": True}
        def synthesize(self, request, path, context, cancel_check):
            sf.write(path, np.ones(800, dtype="float32") * .1, 8000)
            return {"model": request["model"], "sample_rate": 8000}
        def release(self):
            pass
    monkeypatch.setattr(providers, "_PROVIDERS", dict(providers._PROVIDERS))
    providers.register_provider(ExtraLocal())
    conn = service.save_connection({"provider_id": "test-extra-local", "name": "Extra", "deployment": "local"})
    voice = service.store.create("voices", {"name": "Extra", "bindings": []})
    source = service.save_recipe({"name": "Extra", "voice_id": voice["id"], "provider_id": "test-extra-local",
        "model": "fixture-model", "mode": "builtin", "connection_ref": conn["id"],
        "variant": {"kind": "builtin", "value": "speaker", "style": "normal"}, "provider_options": {"schema_version": 1}})
    script = service.create_plan({"text": "扩展引擎。"})
    experiment = service.store.create("experiments", {"name": "Extra", "plan_id": script["id"]})
    task = service.generate(experiment["id"], {"recipe_id": source["id"]})
    service.dispatcher.run(task.task_id)
    assert service.tasks.get_task(task.task_id).state == "completed"
    take = service.experiment(experiment["id"])["takes"][0]
    assert take["compiled_request"]["provider_version"] == "test-1"
    assert sf.info(take["audio_path"]).samplerate == 8000
