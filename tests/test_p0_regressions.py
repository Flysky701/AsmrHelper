"""Targeted regressions for P0 runtime, translation, audio mixer, and catalog fixes."""
from __future__ import annotations

import io
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import soundfile as sf

from src.core.engines.llm.translator import TranslationError, Translator
from src.core.resources import model_assets
from src.core.resources.model_catalog import ModelCatalog
from src.core.speech import local_worker
from src.core.speech.compiler import compile_recipe, text_hash
from src.mixer import Mixer


def test_local_worker_session_loads_model_once_for_multiple_cues(monkeypatch, tmp_path):
    loaded = []
    calls = []

    def fake_load(path, **kwargs):
        loaded.append((path, kwargs))
        return SimpleNamespace(
            generate_custom_voice=lambda **kw: (calls.append(kw) or [np.full(1600, 0.1, dtype="float32")], 16000)
        )

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(float32="float32", float16="float16", bfloat16="bfloat16"))
    monkeypatch.setitem(sys.modules, "qwen_tts", SimpleNamespace(Qwen3TTSModel=SimpleNamespace(from_pretrained=fake_load)))

    recipe = {
        "id": "rule",
        "revision": 1,
        "provider_id": "qwen3",
        "model": "qwen3-custom-voice",
        "mode": "builtin",
        "connection_ref": "local",
        "variant": {"kind": "builtin", "value": "Vivian"},
        "language": "zh",
        "provider_options": {"schema_version": 1},
    }
    text = "第一句。第二句。第三句。"
    plan = {
        "text": text,
        "text_hash": text_hash(text),
        "segments": [
            {"id": "s1", "start": 0, "end": 4, "delivery": "normal"},
            {"id": "s2", "start": 4, "end": 8, "delivery": "normal"},
            {"id": "s3", "start": 8, "end": 12, "delivery": "normal"},
        ],
    }
    requests = compile_recipe(recipe, plan, {})

    session_path = tmp_path / "session.json"
    ready_path = tmp_path / "ready.json"
    session_path.write_text(
        json.dumps(
            {
                "request": requests[0],
                "references": {},
                "model_path": "pinned-qwen3",
                "device": "cpu",
                "precision": "float32",
                "ready_path": str(ready_path),
            }
        ),
        encoding="utf-8",
    )

    commands = []
    for idx, req in enumerate(requests):
        job_path = tmp_path / f"job-{idx}.json"
        out_path = tmp_path / f"out-{idx}.wav"
        resp_path = tmp_path / f"resp-{idx}.json"
        job_path.write_text(
            json.dumps(
                {
                    "request": req,
                    "references": {},
                    "output_path": str(out_path),
                    "response_path": str(resp_path),
                }
            ),
            encoding="utf-8",
        )
        commands.append(str(job_path))
    commands.append("STOP")
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(commands) + "\n"))

    local_worker.serve_session(session_path)

    assert len(loaded) == 1
    assert len(calls) == 3
    assert ready_path.is_file()
    for idx in range(3):
        resp = json.loads((tmp_path / f"resp-{idx}.json").read_text(encoding="utf-8"))
        assert resp["ok"] is True
        assert sf.info(tmp_path / f"out-{idx}.wav").frames == 1600


def test_translator_recovers_from_invalid_batch_and_rejects_untranslated_japanese():
    seen_system_prompts = []

    def create(**kwargs):
        seen_system_prompts.append(kwargs["messages"][0]["content"])
        if len(seen_system_prompts) == 1:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not valid json"))])
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="翻译结果"))])

    translator = Translator(
        api_key="test-key", use_terminology=False, use_quality_check=False, use_cache=False, max_retries=1
    )
    translator._get_client = Mock(
        return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    )

    out = translator.translate_batch(["こんにちは", "ありがとう"], source_lang="日文", target_lang="中文")
    assert out == ["翻译结果", "翻译结果"]

    # Untranslated Japanese echoed verbatim must fail QA rather than silently pass
    qa_translator = Translator(
        api_key="test-key", use_terminology=False, use_quality_check=True, use_cache=False, max_retries=1
    )
    qa_translator._get_client = Mock(
        return_value=SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=lambda **kw: SimpleNamespace(
                        choices=[SimpleNamespace(message=SimpleNamespace(content="こんにちは"))]
                    )
                )
            )
        )
    )
    with pytest.raises(TranslationError, match="质量检查"):
        qa_translator.translate_batch(["こんにちは"], source_lang="日文", target_lang="中文")


def test_qwen3_model_needs_its_tokenizer_to_be_complete(tmp_path):
    catalog = ModelCatalog()

    qwen_entry = catalog.get("qwen3-custom-voice")
    qwen_dir = tmp_path / "qwen"
    (qwen_dir / "speech_tokenizer").mkdir(parents=True)
    for name in qwen_entry.required_files:
        (qwen_dir / name).write_bytes(b"weight")
    # Missing speech_tokenizer/model.safetensors must be detected even though YAML uses `engine: qwen3`
    assert model_assets.complete(qwen_entry, qwen_dir) is False
    (qwen_dir / "speech_tokenizer" / "config.json").write_text("{}", encoding="utf-8")
    (qwen_dir / "speech_tokenizer" / "model.safetensors").write_bytes(b"tok")
    assert model_assets.complete(qwen_entry, qwen_dir) is True


def test_mixer_preserves_sparse_tts_level_and_samplerate(tmp_path):
    sr = 48000
    orig = tmp_path / "orig.wav"
    tts = tmp_path / "tts.wav"
    out = tmp_path / "mixed.wav"

    # Continuous ambient signal at amplitude 0.1
    sf.write(orig, np.full((sr * 4, 2), 0.1, dtype="float32"), sr)
    # Sparse TTS: 0.4s active speech at amplitude 0.1 + 3.6s pure silence (90% silent)
    tts_samples = np.zeros((sr * 4, 2), dtype="float32")
    tts_samples[: int(sr * 0.4)] = 0.1
    sf.write(tts, tts_samples, sr)

    mixer = Mixer(original_volume=0.85, tts_volume_ratio=0.5, tts_delay_ms=0)
    mixer.mix(str(orig), str(tts), str(out))
    samples, rate = sf.read(out)
    assert rate == sr
    assert np.mean(samples[sr:]) == pytest.approx(0.085, abs=0.001)
    assert np.mean(samples[:sr // 4]) == pytest.approx(0.135, abs=0.001)
