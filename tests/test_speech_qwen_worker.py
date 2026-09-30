"""Compiler-to-worker Qwen contracts without downloading or loading weights."""
import json
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from src.core.speech.compiler import compile_recipe, text_hash
from src.core.speech.local_worker import execute


@pytest.mark.parametrize("mode,model,variant,delivery,expected_method", [
    ("builtin", "qwen3-custom-voice", "Vivian", "normal", "custom"),
    ("builtin", "qwen3-custom-voice", "Vivian", "whisper", "custom"),
    ("design", "qwen3-voice-design", "温和清晰的声音", "soft", "design"),
    ("reference", "qwen3-base", "reference", "normal", "clone"),
])
def test_compiled_qwen_modes_preserve_text_language_and_voice(
    monkeypatch, tmp_path, mode, model, variant, delivery, expected_method
):
    text = "こんにちは。"
    assets = {"reference": {"sha256": "a" * 64, "transcript": "参考原文"}}
    recipe = {"id": "rule", "revision": 1, "provider_id": "qwen3", "model": model,
        "mode": mode, "connection_ref": "local", "variant": {"kind": mode, "value": variant},
        "language": "ja", "provider_options": {"schema_version": 1}}
    plan = {"text": text, "text_hash": text_hash(text), "segments": [
        {"id": "sentence", "start": 0, "end": len(text), "delivery": delivery}]}
    request = compile_recipe(recipe, plan, assets)[0]
    calls = []

    def generate(method, **kwargs):
        calls.append((method, kwargs))
        return [np.full(800, .2)], 16000

    engine = SimpleNamespace(
        generate_custom_voice=lambda **kw: generate("custom", **kw),
        generate_voice_design=lambda **kw: generate("design", **kw),
        generate_voice_clone=lambda **kw: generate("clone", **kw),
    )
    loaded = []

    def load(path, **kwargs):
        loaded.append((path, kwargs))
        return engine

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(float32="float32", float16="float16", bfloat16="bfloat16"))
    monkeypatch.setitem(sys.modules, "qwen_tts", SimpleNamespace(Qwen3TTSModel=SimpleNamespace(from_pretrained=load)))
    output, response = tmp_path / "audio.wav", tmp_path / "response.json"
    execute({"request": request, "references": {"reference": "reference.wav"},
        "model_path": "pinned-model", "device": "cpu", "output_path": str(output), "response_path": str(response)})

    assert loaded == [("pinned-model", {"device_map": "cpu", "dtype": "float32"})]
    assert len(calls) == 1 and calls[0][0] == expected_method
    arguments = calls[0][1]
    assert arguments["text"] == text and arguments["language"] == "Japanese"
    if mode == "reference":
        assert arguments["ref_audio"] == "reference.wav" and arguments["ref_text"] == "参考原文"
    elif mode == "design":
        assert variant in arguments["instruct"] and request["parameters"]["instruction"] in arguments["instruct"]
    else:
        assert arguments["speaker"] == variant
        assert bool(arguments["instruct"]) == (delivery != "normal")
    samples, rate = sf.read(output)
    assert samples.size == 800 and rate == 16000 and np.any(samples)
    assert json.loads(response.read_text())["output_path"] == str(output)
