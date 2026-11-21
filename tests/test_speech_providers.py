from io import BytesIO
import json

import httpx
import numpy as np
import pytest
import soundfile as sf

from src.core.speech.compiler import compile_recipe, text_hash
from src.core.speech.providers import ProviderError, get_provider


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


@pytest.mark.parametrize("segments", [
    [{"id": "a", "start": 0, "end": 4}, {"id": "b", "start": 3, "end": 6}],
    [{"id": "a", "start": 0, "end": 6, "text": "rewritten"}],
])
def test_plan_must_reconstruct_exact_original(segments):
    with pytest.raises(ProviderError):
        compile_recipe(recipe(), plan(segments=segments), {})


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


def test_timeout_is_unknown_and_never_retried(monkeypatch, tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("private-key")
    mock_http(monkeypatch, handler)
    with pytest.raises(ProviderError) as error:
        get_provider("fish_audio").synthesize(compile_recipe(recipe(), plan(), {})[0], tmp_path / "out.wav", context(), lambda: False)
    assert len(calls) == 1 and error.value.result_unknown and not error.value.retryable


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
        assert "packages.gpu_worker.cli" in command
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


def test_local_worker_abnormal_exit_reports_error_and_cleans_exchange(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from pathlib import Path
    from src.core.speech import providers
    provider = get_provider('qwen3')
    source = recipe('qwen3', mode='builtin', model='qwen3-custom-voice', connection_ref=None,
                    variant={'kind': 'builtin', 'value': 'Vivian', 'style': 'normal'})
    request = compile_recipe(source, plan(), {})[0]
    monkeypatch.setattr(provider, '_local_settings', lambda *args:
        (Path('custom-python.exe'), str(tmp_path), SimpleNamespace(subprocess_env=lambda: {})))
    exchange = []
    class FailedProcess:
        returncode = 23
        def poll(self):
            return self.returncode
    def popen(command, **kwargs):
        assert 'packages.gpu_worker.cli' in command
        request_path = Path(command[-1])
        assert request_path.is_file()
        exchange.append(request_path.parent)
        return FailedProcess()
    monkeypatch.setattr(providers.subprocess, 'Popen', popen)
    with pytest.raises(ProviderError) as error:
        provider.synthesize(request, tmp_path / 'failed.wav', {}, lambda: False)
    assert error.value.code == 'local_failed'
    assert exchange and all(not directory.exists() for directory in exchange)
    assert not providers._LOCAL_LOCK.locked()
    assert not (tmp_path / 'failed.wav').exists()
