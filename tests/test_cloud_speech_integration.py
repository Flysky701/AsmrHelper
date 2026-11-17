"""Cloud adapters use existing recipes, graph snapshots, takes and recovery."""
import base64
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
import soundfile as sf

from src.app.services.graph_pipeline_service import freeze_graph_speech, make_node_plan
from src.app.services.speech_service import SpeechService
from src.core.speech.compiler import compile_recipe
from src.core.speech.providers import ProviderError
from src.core.speech.store import SpeechStore, build_plan
from test_cloud_speech_transport import install_transport, wav_bytes
from test_pipeline_stage_recovery import setup as recovery_setup, run, next_plan
from test_speech_recovery import speech_plan


CASES = [
    ("gemini", "gemini-3.8-flash-tts", "builtin", "Kore", {"style_description": "Calm"}),
    ("elevenlabs", "eleven_v3", "hosted", "JBFqnCBsd6RMkjVDRZzb", {"speed": .9}),
    ("elevenlabs", "eleven_v4", "hosted", "JBFqnCBsd6RMkjVDRZzb", {}),
    ("mimo", "mimo-v2.5-tts", "builtin", "mimo_default", {"style_description": "Calm"}),
]


@pytest.fixture(params=CASES, ids=[case[1] for case in CASES])
def cloud(request, tmp_path, monkeypatch):
    provider, model, mode, voice, options = request.param
    service = SpeechService(store=SpeechStore(tmp_path / "speech"), tasks=Mock(),
                            dispatcher=Mock(), artifacts=Mock())
    connection = service.save_connection({"name": "Fixture", "provider_id": provider,
        "deployment": "cloud", "base_url": "https://speech.invalid",
        "api_key": "fixture-old-secret", "timeout": 2})
    local_voice = service.store.create("voices", {"name": "Fixture voice", "bindings": []})
    recipe = service.save_recipe({"name": "Fixture rule", "voice_id": local_voice["id"],
        "provider_id": provider, "model": model, "mode": mode,
        "connection_ref": connection["id"], "variant": {"kind": mode, "value": voice},
        "language": "auto", "provider_options": {"schema_version": 1, **options}})
    monkeypatch.setattr("src.app.services.speech_service.get_speech_service", lambda: service)
    return service, recipe, connection


def response_for(provider):
    audio = wav_bytes()
    encoded = base64.b64encode(audio).decode("ascii")
    if provider == "gemini":
        return httpx.Response(200, json={"status": "completed", "steps": [
            {"type": "model_output", "content": [{"type": "audio", "mime_type": "audio/wav", "data": encoded}]}]})
    if provider == "mimo":
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"audio": {"data": encoded}}}]})
    return httpx.Response(200, content=audio)


@pytest.mark.parametrize("saved_rule", [True, False], ids=["saved-rule", "direct-source"])
def test_reloaded_recipe_graph_snapshot_and_runner_stay_pinned(cloud, monkeypatch, tmp_path, saved_rule):
    service, recipe, connection = cloud
    assert SpeechStore(service.store.root).get("recipes", recipe["id"]) == recipe
    source = {key: deepcopy(recipe[key]) for key in ("mode", "variant", "connection_ref", "provider_options")}
    node = {"id": "tts", "kind": "tts", "provider": recipe["provider_id"], "model": recipe["model"],
            "target_lang": "zh", "options": {"speech_recipe_id": recipe["id"]} if saved_rule else {"speech_source": source}}
    frozen = freeze_graph_speech({"version": 2, "graph": {"nodes": [node]}})
    snapshot = deepcopy(frozen["_graph_runtime"]["node_snapshots"]["tts"])
    assert snapshot["recipe"]["language"] == "zh"
    assert service.store.get("recipes", recipe["id"])["language"] == "auto"

    # Current selections and a rotated fixture key must not redirect the admitted run.
    service.save_connection({"id": connection["id"], "api_key": "fixture-new-secret", "timeout": 4})
    service.save_recipe({**recipe, "name": "New revision"})
    frozen["graph"]["nodes"][0].update(model="changed-current-model", options={})
    refrozen = freeze_graph_speech(frozen)
    assert refrozen["_graph_runtime"]["node_snapshots"]["tts"] == snapshot
    plan = make_node_plan(refrozen["graph"]["nodes"][0], task_id="fixture", output_dir=str(tmp_path),
                          snapshots=refrozen["_graph_runtime"]["node_snapshots"])
    assert plan.tts.model == recipe["model"]
    assert plan.tts.provider_options["speech_snapshot"] == snapshot
    assert snapshot["connection"]["revision"] == connection["revision"]
    assert snapshot["recipe"]["provider_options"] == recipe["provider_options"]

    calls = []
    def handler(request):
        calls.append(request)
        return response_for(recipe["provider_id"])
    install_transport(monkeypatch, handler)
    requests = compile_recipe(snapshot["recipe"], build_plan("测试。"), snapshot["assets"])
    takes = service.run_requests(requests, snapshot, task_id="fixture", experiment_id="fixture", plan_id="fixture")
    assert len(calls) == len(takes) == 1
    assert "fixture-old-secret" in str(calls[0].headers)
    assert "fixture-new-secret" not in str(calls[0].headers)
    take = takes[0]
    assert take["compiled_request"]["model"] == recipe["model"]
    assert take["compiled_request"]["connection_snapshot"] == snapshot["connection"]
    assert sf.info(take["audio_path"]).frames == 2400
    service.artifacts.register_artifact.assert_called_once()
    public = json.dumps({"snapshot": snapshot, "takes": takes, "library": service.library()})
    assert "fixture-old-secret" not in public and "fixture-new-secret" not in public


@pytest.mark.parametrize("when", ["before", "after"])
def test_cancel_does_not_publish_take_or_artifact(cloud, monkeypatch, when):
    service, recipe, _ = cloud
    snapshot = service.snapshot(recipe["id"])
    requests = compile_recipe(recipe, build_plan("测试。"), {})
    calls = []
    def handler(request):
        calls.append(request)
        return response_for(recipe["provider_id"])
    install_transport(monkeypatch, handler)
    with pytest.raises(InterruptedError if when == "before" else ProviderError) as caught:
        service.run_requests(requests, snapshot, task_id="cancel", experiment_id="cancel", plan_id="cancel",
                             cancel_check=lambda: when == "before" or bool(calls))
    if when == "after":
        assert caught.value.code == "cancelled"
    assert len(calls) == (0 if when == "before" else 1)
    assert service.store.list("takes") == []
    assert list(service.store.root.glob("audio/*.wav")) == []
    service.artifacts.register_artifact.assert_not_called()


def test_auto_language_is_validated_after_graph_target_is_frozen(cloud):
    service, recipe, _ = cloud
    profile = {"version": 2, "graph": {"nodes": [{"id": "tts", "kind": "tts",
        "provider": recipe["provider_id"], "model": recipe["model"], "target_lang": "ja",
        "options": {"speech_recipe_id": recipe["id"]}}]}}
    if recipe["provider_id"] == "mimo":
        with pytest.raises(ProviderError) as caught:
            freeze_graph_speech(profile)
        assert caught.value.code == "invalid_language"
    else:
        frozen = freeze_graph_speech(profile)
        assert frozen["_graph_runtime"]["node_snapshots"]["tts"]["recipe"]["language"] == "ja"
    assert service.store.get("recipes", recipe["id"])["language"] == "auto"
    service.artifacts.register_artifact.assert_not_called()


@pytest.mark.parametrize("field", ["request_connection", "snapshot_connection", "model"])
def test_mixed_request_snapshot_rejected_before_credentials_or_network(cloud, monkeypatch, field):
    service, recipe, _ = cloud
    snapshot = service.snapshot(recipe["id"])
    requests = compile_recipe(recipe, build_plan("Fixture."), {})
    if field == "request_connection":
        requests[0]["connection_ref"] = "other-connection"
    elif field == "snapshot_connection":
        snapshot["connection"]["id"] = "other-connection"
    else:
        requests[0]["model"] = "other-model"
    monkeypatch.setattr(service, "connection_context", lambda *_: pytest.fail("must not resolve credentials"))
    install_transport(monkeypatch, lambda *_: pytest.fail("must not send HTTP"))
    with pytest.raises(ValueError, match="快照不一致"):
        service.run_requests(requests, snapshot, task_id="invalid", experiment_id="invalid", plan_id="invalid")
    assert not service.store.list("takes")
    service.artifacts.register_artifact.assert_not_called()


@pytest.mark.parametrize("provider,model,mode,voice,options", CASES, ids=[case[0] for case in CASES])
def test_audited_completed_stage_reuses_without_resynthesis(recovery_setup, provider, model, mode, voice, options):
    store, plan = recovery_setup
    snapshot = speech_plan(plan, provider=provider, model=model, mode=mode, kind=mode, value=voice)
    snapshot["recipe"]["provider_options"].update(options)
    run(store, plan)
    executor, result = run(store, next_plan(plan), "first")
    assert executor.calls == []
    assert Path(result["tts_audio_path"]).read_bytes() == b"complete audio"
    audit = store.checkpoint("second", "tts")["payload"]["speech_identity"]
    assert audit["provider_id"] == provider and "opaque-ref" not in str(audit)
