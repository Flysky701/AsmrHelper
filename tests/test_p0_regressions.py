"""Targeted regressions for P0 runtime, translation, audio mixer, and catalog fixes."""
from __future__ import annotations

import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from click.testing import CliRunner
import numpy as np
import pytest
import soundfile as sf

from src.app.persistence.recovery_store import file_identity
from src.app.services.artifact_service import ArtifactService
from src.app.services.speech_service import SpeechService
from src.app.services.task_service import TaskService
from src.cli import cli
from src.core.engines.llm.translator import TranslationError, Translator, has_translatable_text
from src.core.resources import model_assets
from src.core.resources.model_catalog import ModelCatalog
from src.core.speech import local_worker
from src.core.speech.compiler import compile_recipe, text_hash
from src.core.speech.providers import get_provider
from src.core.speech.store import SpeechStore
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


def test_speech_service_reuses_single_local_worker_process_across_batch(monkeypatch, tmp_path):
    service = SpeechService(store=SpeechStore(tmp_path / "lab"), tasks=TaskService(), artifacts=ArtifactService())
    conn = service.save_connection({"name": "Local Qwen", "provider_id": "qwen3", "deployment": "local"})
    voice = service.store.create("voices", {"name": "QwenVoice", "bindings": []})
    recipe = service.save_recipe(
        {
            "name": "QwenRule",
            "voice_id": voice["id"],
            "provider_id": "qwen3",
            "model": "qwen3-custom-voice",
            "mode": "builtin",
            "connection_ref": conn["id"],
            "variant": {"kind": "builtin", "value": "Vivian", "style": "normal"},
            "language": "zh",
            "provider_options": {"schema_version": 1},
        }
    )
    provider = get_provider("qwen3")
    monkeypatch.setattr(
        provider,
        "_local_settings",
        lambda *args: (Path("fake-python.exe"), str(tmp_path), SimpleNamespace(subprocess_env=lambda: {})),
    )

    spawned = []

    class FakeStdin:
        def __init__(self, session_dir: Path):
            self.session_dir = session_dir
            self.closed = False

        def write(self, data: str):
            line = data.strip()
            if line and line != "STOP":
                job = json.loads(Path(line).read_text(encoding="utf-8"))
                sf.write(job["request"]["items"][0]["output_path"], np.full(1600, 0.05, dtype="float32"), 16000)
                Path(job["response_path"]).write_text(
                    json.dumps({"ok": True, "result": {"items": [{"ok": True}]}}), encoding="utf-8"
                )
            return len(data)

        def flush(self):
            pass

        def close(self):
            self.closed = True

    class FakeBatchProcess:
        def __init__(self, session_file: Path):
            session_file.write_text('{"status":"ready"}', encoding="utf-8")
            self.stdin = FakeStdin(session_file.parent)
            self._terminated = False
            self.returncode = None

        def poll(self):
            return 0 if self._terminated else None

        def terminate(self):
            self._terminated = True
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    def fake_popen(command, **kwargs):
        assert "--session" in command
        session_file = Path(command[-1])
        proc = FakeBatchProcess(session_file)
        spawned.append((proc, session_file.parent))
        return proc

    monkeypatch.setattr("src.core.speech.providers.subprocess.Popen", fake_popen)

    plan = service.create_plan({"text": "第一句。第二句。第三句。"})
    experiment = service.store.create("experiments", {"name": "BatchTest", "plan_id": plan["id"]})
    snapshot = service.snapshot(recipe["id"])
    requests = service.compile(recipe["id"], plan["id"])

    takes = service.run_requests(
        requests, snapshot, task_id="task-batch", experiment_id=experiment["id"], plan_id=plan["id"]
    )
    assert len(takes) == 3
    assert len(spawned) == 1
    proc, exchange_dir = spawned[0]
    assert proc._terminated or proc.stdin.closed
    assert not exchange_dir.exists()


def test_translator_batch_fallback_uses_plain_text_prompt_and_rejects_untranslated_japanese(tmp_path):
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
    assert "JSON 数组格式" in seen_system_prompts[0]
    assert "JSON 数组格式" not in seen_system_prompts[1]
    assert "纯文本" in seen_system_prompts[1]

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

    assert not has_translatable_text("♪")
    assert not has_translatable_text("...")
    assert not has_translatable_text("0")
    assert has_translatable_text("おはよう")


def test_demucs_catalog_and_qwen3_tokenizer_completeness_and_cli_presets(tmp_path):
    catalog = ModelCatalog()
    demucs = catalog.get("demucs-htdemucs")
    assert demucs.supports_install is True
    assert demucs.supports_remove is True

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

    runner = CliRunner()
    res = runner.invoke(cli, ["pipeline", "presets"])
    assert res.exit_code == 0, res.output
    assert "Available presets:" in res.output


def test_mixer_gated_rms_preserves_sparse_tts_level_and_samplerate(tmp_path, monkeypatch):
    sr = 48000
    orig = tmp_path / "orig.wav"
    tts = tmp_path / "tts.wav"
    out = tmp_path / "mixed.wav"

    # Continuous ambient signal at amplitude 0.1
    sf.write(orig, np.full((sr * 4, 2), 0.1, dtype="float32"), sr)
    # Sparse TTS: 0.4s active speech at amplitude 0.1 + 3.6s pure silence (90% silent)
    tts_samples = np.zeros(sr * 4, dtype="float32")
    tts_samples[: int(sr * 0.4)] = 0.1
    sf.write(tts, tts_samples, sr)

    mixer = Mixer(original_volume=0.85, tts_volume_ratio=0.5, tts_delay_ms=0)
    # Gated active RMS should measure ~0.1, not whole-file silence-diluted ~0.0316
    assert abs(mixer.detect_volume(str(tts)) - 0.1) < 1e-3

    captured_cmds = []

    def fake_run(cmd, **kwargs):
        captured_cmds.append(cmd)
        sf.write(out, np.zeros((1600, 2), dtype="float32"), sr)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr("src.mixer.get_ffmpeg", lambda: "ffmpeg")
    mixer.mix(str(orig), str(tts), str(out))

    cmd = captured_cmds[0]
    filter_idx = cmd.index("-filter_complex") + 1
    ar_idx = cmd.index("-ar") + 1
    assert "normalize=0" in cmd[filter_idx]
    assert cmd[ar_idx] == "48000"


def test_file_identity_memoizes_and_invalidates_on_change(tmp_path):
    sample = tmp_path / "weights.bin"
    sample.write_bytes(b"alpha")
    first = file_identity(sample)
    second = file_identity(sample)
    assert first == second
    sample.write_bytes(b"beta-longer")
    third = file_identity(sample)
    assert third["sha256"] != first["sha256"]
    assert third["size"] == 11
