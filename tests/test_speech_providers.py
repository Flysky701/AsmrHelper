from copy import deepcopy
from io import BytesIO
import json

import httpx
import numpy as np
import pytest
import soundfile as sf

from src.core.speech.compiler import compile_recipe, text_hash
from src.core.speech.providers import ProviderError, get_provider, list_providers, register_provider


def recipe(provider="fish_audio", **changes):
    value = {"id": "recipe", "revision": 1, "provider_id": provider, "model": "s2-pro", "mode": "hosted",
        "connection_ref": "fish-connection", "variant": {"kind": "hosted", "value": "voice-id", "style": "normal"},
        "language": "zh", "provider_options": {"schema_version": 1}}
    value.update(changes)
    return value


def plan(text="你好，世界。", **changes):
    value = {"id": "plan", "text": text, "text_hash": text_hash(text), "segments": [
        {"id": "line", "start": 0, "end": len(text), "delivery": "normal", "emotion": "neutral", "pause_ms": 0}]}
    value.update(changes)
    return value


def test_compile_does_not_mutate_and_hash_covers_effective_inputs():
    source, script = recipe(), plan()
    original = deepcopy((source, script))
    compiled = compile_recipe(source, script, {})[0]
    assert (source, script) == original
    assert compiled == compile_recipe(source, script, {})[0]
    source["variant"]["value"] = "other"
    assert compiled["parameters"]["variant"]["value"] == "voice-id"
    assert compile_recipe(source, script, {})[0]["cache_key"] != compiled["cache_key"]
    for changed in [recipe(connection_ref="other"), recipe(model="s1"), recipe(provider_options={"schema_version": 1, "temperature": .4})]:
        assert compile_recipe(changed, script, {})[0]["cache_key"] != compiled["cache_key"]


@pytest.mark.parametrize("segments", [
    [{"id": "a", "start": 1, "end": 6}],
    [{"id": "a", "start": 0, "end": 3}],
    [{"id": "a", "start": 0, "end": 4}, {"id": "b", "start": 3, "end": 6}],
    [{"id": "a", "start": 0, "end": 3}, {"id": "a", "start": 3, "end": 6}],
    [{"id": "a", "start": 0, "end": 6, "text": "rewritten"}],
])
def test_plan_must_reconstruct_exact_original(segments):
    with pytest.raises(ProviderError):
        compile_recipe(recipe(), plan(segments=segments), {})


def test_plan_hash_and_options_fail_closed():
    with pytest.raises(ProviderError, match="摘要"):
        compile_recipe(recipe(), plan(text_hash="bad"), {})
    for options in [{}, {"schema_version": 2}, {"schema_version": 1, "api_key": "secret"},
                    {"schema_version": 1, "speed": float("nan")}, {"schema_version": 1, "speed": 8}]:
        with pytest.raises(ProviderError):
            compile_recipe(recipe(provider_options=options), plan(), {})
    with pytest.raises(ProviderError):
        compile_recipe(recipe(variant={"kind": "hosted", "value": "v", "api_key": "secret"}), plan(), {})


def test_fish_model_specific_tags_do_not_modify_original_text():
    script = plan()
    script["segments"][0].update(delivery="whisper", emotion="calm")
    compiled = compile_recipe(recipe(), script, {})[0]
    assert compiled["text"] == script["text"]
    assert compiled["parameters"]["rendered_text"] == "[whispering, calm]" + script["text"]
    legacy = compile_recipe(recipe(model="s1"), script, {})[0]
    assert legacy["parameters"]["rendered_text"].startswith("(whispering)(calm)")


def test_reference_requires_asset_and_transcript_and_hashes_affect_cache():
    source = recipe("qwen3", mode="reference", model="qwen3-base", connection_ref=None,
        variant={"kind": "reference", "value": "asset", "style": "whisper"})
    with pytest.raises(ProviderError, match="素材"):
        compile_recipe(source, plan(), {})
    with pytest.raises(ProviderError, match="转录"):
        compile_recipe(source, plan(), {"asset": {"sha256": "a" * 64}})
    assets = {"asset": {"sha256": "a" * 64, "transcript": "reference text"}}
    script = plan()
    script["segments"][0]["delivery"] = "whisper"
    compiled = compile_recipe(source, script, assets)[0]
    assert compiled["asset_hashes"] == {"asset": "a" * 64}
    assets["asset"]["transcript"] = "changed transcript"
    assert compile_recipe(source, script, assets)[0]["cache_key"] != compiled["cache_key"]
    source["variant"]["style"] = "normal"
    with pytest.raises(ProviderError, match="对应风格"):
        compile_recipe(source, script, assets)


def test_unsupported_intent_fails_instead_of_silent_edge_fallback():
    source = recipe("edge", model="edge-tts", mode="builtin", connection_ref=None,
        variant={"kind": "builtin", "value": "zh-CN-XiaoxiaoNeural", "style": "normal"})
    script = plan()
    script["segments"][0]["delivery"] = "whisper"
    with pytest.raises(ProviderError) as error:
        compile_recipe(source, script, {})
    assert error.value.code == "unsupported_intent"


def wav():
    buffer = BytesIO()
    sf.write(buffer, np.full(1600, .1), 16000, format="WAV")
    return buffer.getvalue()


def mock_http(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: original(**kw, transport=httpx.MockTransport(handler)))


def context():
    return {"connection": {"provider_id": "fish_audio", "base_url": "https://api.fish.audio/v1", "api_key": "private-key"}}


def test_fish_execution_uses_native_protocol_and_returns_audio_contract(monkeypatch, tmp_path):
    request = compile_recipe(recipe(), plan(), {})[0]

    def handler(http_request):
        assert str(http_request.url) == "https://api.fish.audio/v1/tts"
        assert http_request.headers["model"] == "s2-pro"
        assert http_request.headers["authorization"] == "Bearer private-key"
        body = json.loads(http_request.content)
        assert body["reference_id"] == "voice-id" and body["format"] == "wav"
        assert "model" not in body and "instructions" not in body
        return httpx.Response(200, content=wav(), headers={"x-request-id": "remote-1"})

    mock_http(monkeypatch, handler)
    metadata = get_provider("fish_audio").synthesize(request, tmp_path / "audio.wav", context(), lambda: False)
    assert metadata["sample_rate"] == 16000 and metadata["channels"] == 1
    assert metadata["duration"] == .1 and metadata["remote_request_id"] == "remote-1"
    assert "private-key" not in json.dumps(request) + json.dumps(metadata)


@pytest.mark.parametrize("status,code", [(401, "authentication_failed"), (429, "rate_limited"), (404, "model_unavailable"), (500, "remote_failed"), (200, "invalid_audio")])
def test_remote_errors_classified_without_leaking_body(monkeypatch, tmp_path, status, code):
    mock_http(monkeypatch, lambda req: httpx.Response(status, content=b"private-key"))
    output = tmp_path / "bad.wav"
    with pytest.raises(ProviderError) as error:
        get_provider("fish_audio").synthesize(compile_recipe(recipe(), plan(), {})[0], output, context(), lambda: False)
    assert error.value.code == code and "private-key" not in str(error.value)
    assert not output.exists()


def test_timeout_is_unknown_and_never_retried(monkeypatch, tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private-key")
    mock_http(monkeypatch, handler)
    with pytest.raises(ProviderError) as error:
        get_provider("fish_audio").synthesize(compile_recipe(recipe(), plan(), {})[0], tmp_path / "out.wav", context(), lambda: False)
    assert len(calls) == 1 and error.value.result_unknown and not error.value.retryable


def test_cancel_and_version_mismatch_prevent_requests(monkeypatch, tmp_path):
    mock_http(monkeypatch, lambda request: pytest.fail("must not send"))
    compiled = compile_recipe(recipe(), plan(), {})[0]
    with pytest.raises(ProviderError) as error:
        get_provider("fish_audio").synthesize(compiled, tmp_path / "a.wav", context(), lambda: True)
    assert error.value.code == "cancelled"
    compiled["provider_version"] = "future"
    with pytest.raises(ProviderError) as error:
        get_provider("fish_audio").synthesize(compiled, tmp_path / "a.wav", context(), lambda: False)
    assert error.value.code == "version_mismatch"


def test_registry_extension_needs_no_compiler_business_branch(monkeypatch):
    from src.core.speech import providers
    class Fake:
        provider_id, version, remote = "fake-local", "4", False
        def describe(self):
            return {"provider_id": self.provider_id}
        def validate(self, recipe, assets):
            pass
        def compile(self, recipe, segment, text, assets):
            return {"verbatim": text}
    monkeypatch.setattr(providers, "_PROVIDERS", dict(providers._PROVIDERS))
    register_provider(Fake())
    compiled = compile_recipe(recipe("fake-local"), plan(), {})[0]
    assert compiled["parameters"]["verbatim"] == plan()["text"]
    assert compiled["provider_version"] == "4"
    with pytest.raises(ProviderError):
        register_provider(Fake())


def test_descriptors_have_no_load_side_effect_and_are_independent():
    descriptions = list_providers()
    assert {d["provider_id"] for d in descriptions} >= {"fish_audio", "edge", "qwen3", "voxcpm2", "openai_compatible"}
    descriptions[0]["options_schema"]["properties"].clear()
    assert get_provider("fish_audio").describe()["options_schema"]["properties"]


def test_mimo_is_explicit_provider_with_chat_audio_contract(monkeypatch, tmp_path):
    from base64 import b64encode
    source = recipe("mimo_audio", model="mimo-v2.5-tts", variant={"kind": "hosted", "value": "mimo_default", "style": "normal"},
        provider_options={"schema_version": 1, "instructions": "自然朗读"})
    script = plan()
    script["segments"][0]["delivery"] = "whisper"
    request = compile_recipe(source, script, {})[0]
    def handler(req):
        assert str(req.url) == "https://mimo.invalid/v1/chat/completions"
        payload = json.loads(req.content)
        assert payload["messages"][0]["role"] == "user"
        assert "自然朗读" in payload["messages"][0]["content"]
        assert payload["messages"][1] == {"role": "assistant", "content": script["text"]}
        assert payload["audio"] == {"voice": "mimo_default", "format": "wav"}
        return httpx.Response(200, json={"choices": [{"message": {"audio": {"data": b64encode(wav()).decode()}}}]})
    mock_http(monkeypatch, handler)
    metadata = get_provider("mimo_audio").synthesize(request, tmp_path / "mimo.wav", {
        "connection": {"provider_id": "mimo_audio", "base_url": "https://mimo.invalid/v1", "api_key": "secret"}}, lambda: False)
    assert metadata["duration"] == .1
    source["model"] = "mimo-v2.5-tts-voiceclone"
    with pytest.raises(ProviderError, match="模型"):
        compile_recipe(source, script, {})


def test_local_probe_matches_selected_mode_and_runtime_override(tmp_path):
    import sys
    model = tmp_path / "model"
    model.mkdir()
    (model / "config.json").write_text(json.dumps({"tts_model_type": "base"}))
    (model / "model.safetensors").write_bytes(b"fixture")
    context = {"model": "qwen3-base", "mode": "reference", "model_path": str(model), "runtime": sys.executable}
    result = get_provider("qwen3").probe(context)
    assert result["ready"] and result["runtime"] == sys.executable
    context["mode"] = "design"
    result = get_provider("qwen3").probe(context)
    assert not result["ready"] and result["code"] == "model_mismatch"
    context["model_path"] = str(tmp_path / "absent")
    assert not get_provider("qwen3").probe(context)["ready"]


def test_provider_error_preserves_task_state():
    error = ProviderError("result_unknown", "timeout", result_unknown=True)
    assert error.task_error == {"code": "result_unknown", "detail": "timeout", "stage": "tts",
        "retryable": False, "result_unknown": True}


def test_local_cancellation_terminates_isolated_worker(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from pathlib import Path
    from src.core.speech import providers
    provider = get_provider("qwen3")
    source = recipe("qwen3", mode="builtin", model="qwen3-custom-voice", connection_ref=None,
        variant={"kind": "builtin", "value": "Vivian", "style": "normal"})
    request = compile_recipe(source, plan(), {})[0]
    monkeypatch.setattr(provider, "_local_settings", lambda *args: (Path("custom-python.exe"), str(tmp_path), SimpleNamespace(subprocess_env=lambda: {})))
    state = {"terminated": False, "waited": False, "checks": 0}
    class Process:
        returncode = None
        def poll(self):
            return 0 if state["terminated"] else None
        def terminate(self):
            state["terminated"] = True
        def wait(self, timeout=None):
            state["waited"] = True
            return 0
    def popen(command, **kwargs):
        assert command[0] == "custom-python.exe"
        assert "src.core.speech.local_worker" in command
        return Process()
    monkeypatch.setattr(providers.subprocess, "Popen", popen)
    def cancelled():
        state["checks"] += 1
        return state["checks"] >= 3
    with pytest.raises(ProviderError) as error:
        provider.synthesize(request, tmp_path / "cancelled.wav", {}, cancelled)
    assert error.value.code == "cancelled"
    assert state["terminated"] and state["waited"]
    assert not providers._LOCAL_LOCK.locked()
