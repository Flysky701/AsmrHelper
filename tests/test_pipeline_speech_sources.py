"""Engine-first pipeline voices share the existing compiler and frozen runner."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from src.app.services.speech_service import SpeechService
from src.core.speech.providers import get_provider, list_providers
from src.core.speech.store import SpeechStore, build_plan
from src.core.speech.compiler import compile_recipe


@pytest.fixture
def speech(tmp_path, monkeypatch):
    service = SpeechService(store=SpeechStore(tmp_path / "speech"), tasks=Mock(),
                            dispatcher=Mock(), artifacts=Mock())
    for provider_id in ("edge", "qwen3", "voxcpm2", "fish_audio", "openai_compatible"):
        monkeypatch.setattr(get_provider(provider_id), "probe", lambda context: {"ready": True})
    return service


@pytest.mark.parametrize("provider,model,expected", [
    ("edge", "edge-tts", "zh-CN-XiaoxiaoNeural"),
    ("qwen3", "qwen3-custom-voice", "Vivian"),
    ("voxcpm2", "voxcpm2", "default"),
])
def test_defaults_need_no_saved_rule_or_connection(speech, provider, model, expected):
    stage = {"provider": provider, "model": model, "options": {"language": "zh"}}
    original = deepcopy(stage)
    snap = speech.pipeline_snapshot(stage)
    assert snap["recipe"]["variant"]["value"] == expected
    assert compile_recipe(snap["recipe"], build_plan("你好。"), snap["assets"])[0]["model"] == model
    assert stage == original
    for collection in ("voices", "recipes", "connections"):
        assert speech.store.list(collection) == []


def test_preset_speed_and_parameters_are_frozen(speech):
    stage = {"provider": "edge", "model": "edge-tts", "options": {
        "language": "ja", "speed": 1.2, "speech_source": {
            "mode": "builtin", "variant": {"kind": "builtin", "value": "ja-JP-NanamiNeural"}}}}
    snap = speech.pipeline_snapshot(stage)
    stage["options"]["speech_source"]["variant"]["value"] = "other"
    compiled = compile_recipe(snap["recipe"], build_plan("こんにちは。"), {})[0]
    assert compiled["parameters"]["variant"]["value"] == "ja-JP-NanamiNeural"
    assert compiled["parameters"]["options"]["speed"] == 1.2
    assert compiled["parameters"]["language"] == "ja"


@pytest.mark.parametrize("provider,model,mode", [
    ("qwen3", "qwen3-base", "reference"),
    ("qwen3", "qwen3-voice-design", "design"),
    ("fish_audio", "s2-pro", "hosted"),
    ("openai_compatible", "server-model", "hosted"),
])
def test_input_required_modes_have_no_fake_default(speech, provider, model, mode):
    with pytest.raises(ValueError):
        speech.pipeline_snapshot({"provider": provider, "model": model,
            "options": {"voice": "zh-CN-XiaoxiaoNeural", "speech_source": {"mode": mode}}})
    assert get_provider(provider).voice_sources(mode)["default"] is None


def test_hosted_voice_requires_matching_connection_and_pins_revision(speech):
    source = {"mode": "hosted", "variant": {"kind": "hosted", "value": "real-hosted-id"}}
    stage = {"provider": "fish_audio", "model": "s2-pro", "options": {"speech_source": source}}
    with pytest.raises(ValueError, match="连接"):
        speech.pipeline_snapshot(stage)
    connection = speech.save_connection({"name": "Mock cloud", "provider_id": "fish_audio",
        "deployment": "cloud", "base_url": "https://example.invalid/v1"})
    source["connection_ref"] = connection["id"]
    snap = speech.pipeline_snapshot(stage)
    speech.save_connection({"id": connection["id"], "timeout": 240})
    assert snap["connection"]["timeout"] == 120
    assert snap["connection"]["revision"] == connection["revision"]
    wrong = speech.save_connection({"name": "Other", "provider_id": "edge", "deployment": "cloud"})
    source["connection_ref"] = wrong["id"]
    with pytest.raises(ValueError, match="引擎"):
        speech.pipeline_snapshot(stage)


def test_saved_rule_cannot_override_explicit_engine_model(speech):
    connection = speech.save_connection({"name": "Edge", "provider_id": "edge", "deployment": "cloud"})
    recipe = speech.store.create("recipes", {"name": "Saved", "voice_id": "test-voice", "provider_id": "edge", "model": "edge-tts",
        "mode": "builtin", "connection_ref": connection["id"],
        "variant": {"kind": "builtin", "value": "en-US-JennyNeural"},
        "provider_options": {"schema_version": 1}})
    stage = {"provider": "edge", "model": "edge-tts", "options": {"speech_recipe_id": recipe["id"]}}
    assert speech.pipeline_snapshot(stage)["recipe"]["id"] == recipe["id"]
    with pytest.raises(ValueError, match="引擎"):
        speech.pipeline_snapshot({**stage, "provider": "qwen3"})
    with pytest.raises(ValueError, match="模型"):
        speech.pipeline_snapshot({**stage, "model": "qwen3-base"})
    with pytest.raises(ValueError, match="同时"):
        speech.pipeline_snapshot({**stage, "options": {**stage["options"], "speech_source": {"mode": "builtin"}}})


def test_local_resolved_paths_are_pinned(speech, monkeypatch):
    monkeypatch.setattr(get_provider("voxcpm2"), "probe", lambda context: {
        "ready": True, "model_path": "models/pinned", "runtime": "runtime/pinned/python"})
    snap = speech.pipeline_snapshot({"provider": "voxcpm2", "model": "voxcpm2"})
    assert snap["connection"]["model_path"] == "models/pinned"
    assert snap["connection"]["runtime"] == "runtime/pinned/python"


def test_descriptor_catalog_is_specific_to_model_mode():
    providers = {p["provider_id"]: p for p in list_providers()}
    qwen = {m["id"]: m["voice_sources"] for m in providers["qwen3"]["modes"]}
    assert "Vivian" in {v["id"] for v in qwen["builtin"]["presets"]}
    assert qwen["builtin"]["allow_custom"] is False
    assert providers["edge"]["modes"][0]["voice_sources"]["allow_custom"] is True
    assert qwen["reference"]["required"] and not qwen["reference"]["presets"]
    assert providers["fish_audio"]["modes"][0]["voice_sources"]["presets"] == []


def test_default_voxcpm_worker_uses_plain_text_without_reference(monkeypatch, tmp_path):
    from src.core.speech.local_worker import execute
    engine = Mock()
    factory = Mock(return_value=engine)
    monkeypatch.setattr("src.core.engines.tts.voxcpm2.VoxCPM2Engine", factory)
    recipe = {"id": "task-recipe", "revision": 1, "provider_id": "voxcpm2", "model": "voxcpm2",
              "mode": "default", "variant": {"kind": "default", "value": "default"},
              "provider_options": {"schema_version": 1}}
    request = compile_recipe(recipe, build_plan("你好。"), {})[0]
    execute({"request": request, "references": {}, "model_path": "test-model",
             "output_path": str(tmp_path / "out.wav"), "response_path": str(tmp_path / "response.json")})
    assert factory.call_args.kwargs["reference_wav_path"] is None
    engine.synthesize.assert_called_once_with("你好。", str(tmp_path / "out.wav"))


def test_pipeline_submission_embeds_snapshot_without_creating_rule(speech, monkeypatch):
    from src.app.dto import PipelineRequest
    from src.app.services.pipeline_service import PipelineService
    monkeypatch.setattr("src.app.services.speech_service.get_speech_service", lambda: speech)
    tasks = Mock()
    tasks.create_task_spec.return_value = (Mock(task_id="task-test"), Mock())
    catalog = Mock()
    catalog.inspect_paths.return_value = [Mock(asset_id="input", absolute_path="input.wav")]
    service = PipelineService(task_service=tasks, resource_service=Mock(), workspace_service=Mock(),
        input_catalog_service=catalog, session_service=Mock(), artifact_service=Mock(), executor=Mock())
    profile = {"version": 1, "stages": {"tts": {"enabled": True, "provider": "edge", "model": "edge-tts",
        "options": {"language": "zh"}, "provider_options": {}}}}
    original = deepcopy(profile)
    service.create_pipeline_task_spec(PipelineRequest(input_path="input.wav", execution_profile=profile))
    submitted = tasks.create_task_spec.call_args.kwargs["execution_profile"]
    snap = submitted["stages"]["tts"]["provider_options"]["speech_snapshot"]
    assert snap["recipe"]["variant"]["value"] == "zh-CN-XiaoxiaoNeural"
    assert profile == original
    assert speech.store.list("recipes") == []


def test_readiness_uses_same_engine_source_resolution(speech, monkeypatch, tmp_path):
    from src.app.services.resource_service import ResourceService
    monkeypatch.setattr("src.app.services.speech_service.get_speech_service", lambda: speech)
    models = Mock()
    models.list_models.return_value = []
    resources = ResourceService(project_root=tmp_path, descriptor_service=Mock(), model_service=models)
    assert resources._check_pipeline_profile({"stages": {"tts": {"provider": "edge"}}}) == []
    issues = resources._check_pipeline_profile({"stages": {"tts": {"provider": "fish_audio", "model": "s2-pro"}}})
    assert issues[0]["code"] == "SPEECH_SOURCE_NOT_READY"
    assert issues[0]["requirement"] == "speech_source"
    assert "VoiceLab" not in issues[0]["message"]
