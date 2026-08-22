from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.engines.tts.service import TtsEngineRuntime
from src.core.resources.model_catalog import ModelEntry
from src.core.resources.model_status import ModelStatusResolver
from src.core.runtime.profiles import RuntimeProbeError, RuntimeProfileResolver
from src.core.runtime.router import RuntimeRouter


def test_runtime_profiles_resolve_project_relative_interpreters(tmp_path):
    resolver = RuntimeProfileResolver(project_root=tmp_path)

    main = resolver.resolve("main")
    qwen_tts = resolver.resolve("qwen_tts")
    fun_asr = resolver.resolve("fun_asr")

    assert main.isolated is False
    assert qwen_tts.isolated is True
    assert qwen_tts.environment_dir == tmp_path / ".runtimes" / "qwen_tts"
    assert qwen_tts.python_executable == qwen_tts.environment_dir / "Scripts" / "python.exe"
    assert fun_asr.isolated is True
    assert fun_asr.environment_dir == tmp_path / ".runtimes" / "fun_asr"
    assert fun_asr.project_extra == "funasr"


def test_runtime_subprocess_environment_keeps_uv_state_inside_project(tmp_path, monkeypatch):
    monkeypatch.delenv("UV_CACHE_DIR", raising=False)
    monkeypatch.delenv("UV_PYTHON_INSTALL_DIR", raising=False)
    resolver = RuntimeProfileResolver(project_root=tmp_path)

    env = resolver.subprocess_env()

    assert env["UV_CACHE_DIR"] == str(tmp_path / ".uv-cache")
    assert env["UV_PYTHON_INSTALL_DIR"] == str(tmp_path / ".runtimes" / "python")


def test_runtime_module_probe_timeout_is_reported_as_probe_failure(tmp_path, monkeypatch):
    resolver = RuntimeProfileResolver(project_root=tmp_path)
    python_executable = resolver.resolve("qwen_tts").python_executable
    python_executable.parent.mkdir(parents=True)
    python_executable.write_bytes(b"python")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get("timeout", 30))

    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", timeout)

    with pytest.raises(RuntimeProbeError, match="probe failed"):
        resolver.check_modules("qwen_tts", ["qwen_tts"])
    with pytest.raises(RuntimeProbeError, match="probe failed"):
        resolver.has_cuda("qwen_tts")


def test_fun_asr_runtime_probe_imports_auto_model_symbol(tmp_path, monkeypatch):
    resolver = RuntimeProfileResolver(project_root=tmp_path)
    python_executable = resolver.resolve("fun_asr").python_executable
    python_executable.parent.mkdir(parents=True)
    python_executable.write_bytes(b"python")
    captured: dict[str, str] = {}

    def fake_run(cmd, **_kwargs):
        captured["script"] = cmd[-1]
        return SimpleNamespace(
            returncode=0,
            stdout='__ASMR_RUNTIME_PROBE__{"funasr": true}\n',
            stderr="",
        )

    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", fake_run)

    assert resolver.check_modules("fun_asr", ["funasr"]) is True
    assert "from funasr import AutoModel" in captured["script"]


def test_isolated_model_status_reports_missing_runtime(tmp_path):
    install_dir = tmp_path / "models" / "qwen"
    install_dir.mkdir(parents=True)
    (install_dir / "model.safetensors").write_bytes(b"model")
    entry = ModelEntry(
        id="qwen3-custom-voice",
        kind="local",
        category="tts",
        engine="qwen3",
        display_name="Qwen3 CustomVoice",
        description="test",
        install_root=str(tmp_path / "models"),
        install_path="qwen",
        required_files=["model.safetensors"],
        required_python_extras=["qwen3"],
        runtime_profile="qwen_tts",
        requires_gpu=True,
    )
    resolver = ModelStatusResolver(runtime_resolver=RuntimeProfileResolver(project_root=tmp_path))

    status = resolver.resolve(entry)

    assert status.executable is False
    assert any(issue.code == "RUNTIME_ENVIRONMENT_MISSING" for issue in status.issues)


def test_qwen_tts_runtime_bootstrap_uses_cuda_wheels(tmp_path, monkeypatch):
    resolver = RuntimeProfileResolver(project_root=tmp_path)
    monkeypatch.setattr("src.core.runtime.profiles.shutil.which", lambda name: "uv.exe")

    commands = resolver.build_bootstrap_commands(resolver.resolve("qwen_tts"))

    assert len(commands) == 1
    assert "https://download.pytorch.org/whl/cu126" in commands[0]
    assert "torch==2.10.0+cu126" in commands[0]
    assert "torchaudio==2.10.0+cu126" in commands[0]


def test_tts_runtime_routes_qwen_to_isolated_worker(tmp_path):
    class Router:
        def __init__(self):
            self.payload = None

        def tts_profile(self, provider):
            return "qwen_tts" if provider == "qwen3" else None

        def synthesize_text(self, payload):
            self.payload = payload
            return str(tmp_path / "qwen.wav")

    class Registry:
        def get(self, name, **kwargs):
            raise AssertionError("isolated providers must not load in the main process")

    router = Router()
    runtime = TtsEngineRuntime(registry=Registry(), runtime_router=router)
    output = runtime.synthesize_text(
        text="hello",
        output_path=str(tmp_path / "qwen.wav"),
        profile={
            "provider": "qwen3",
            "model": "qwen3-custom-voice",
            "common_options": {"voice": "Vivian", "speed": 1.0},
            "provider_options": {},
        },
    )

    assert output == str(tmp_path / "qwen.wav")
    assert router.payload["profile"]["model"] == "qwen3-custom-voice"


def test_asr_runtime_routes_conflicting_providers_to_isolated_worker(tmp_path):
    class Router:
        def __init__(self):
            self.payload = None

        def asr_profile(self, provider):
            return "qwen_asr" if provider == "qwen3_asr" else None

        def transcribe_file(self, payload):
            self.payload = payload
            return {
                "document": {
                    "segments": [
                        {
                            "start": 0.0,
                            "end": 1.25,
                            "text": "isolated",
                            "language": "en",
                            "confidence": 0.9,
                        }
                    ],
                    "language": "en",
                    "format": "srt",
                    "source_path": "worker.srt",
                    "warnings": [],
                }
            }

    class Registry:
        def get(self, name, **kwargs):
            raise AssertionError("isolated providers must not load in the main process")

    from src.core.engines.asr.service import AsrEngineRuntime

    router = Router()
    runtime = AsrEngineRuntime(registry=Registry(), runtime_router=router)
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fake")

    document = runtime.transcribe_file(
        input_path=str(audio_path),
        output_path=None,
        profile={"provider": "qwen3_asr", "model": "qwen3-asr-0.6b"},
    )

    assert router.payload["profile"]["provider"] == "qwen3_asr"
    assert document.segments[0].text == "isolated"
    assert document.segments[0].confidence == 0.9


def test_runtime_router_reads_structured_worker_result(tmp_path, monkeypatch):
    resolver = RuntimeProfileResolver(project_root=tmp_path)
    profile = resolver.resolve("qwen_tts")
    profile.python_executable.parent.mkdir(parents=True)
    profile.python_executable.write_bytes(b"python")
    router = RuntimeRouter(resolver=resolver, project_root=tmp_path)

    def fake_run(cmd, **kwargs):
        response_path = Path(cmd[cmd.index("--response") + 1])
        response_path.write_text(
            json.dumps({"success": True, "result": {"output_path": "result.wav"}}),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.core.runtime.router.subprocess.run", fake_run)

    result = router.synthesize_text(
        {
            "text": "hello",
            "output_path": "result.wav",
            "profile": {"provider": "qwen3"},
        }
    )

    assert result == "result.wav"


def test_runtime_router_reads_structured_asr_worker_result(tmp_path, monkeypatch):
    resolver = RuntimeProfileResolver(project_root=tmp_path)
    profile = resolver.resolve("qwen_asr")
    profile.python_executable.parent.mkdir(parents=True)
    profile.python_executable.write_bytes(b"python")
    router = RuntimeRouter(resolver=resolver, project_root=tmp_path)

    def fake_run(cmd, **kwargs):
        response_path = Path(cmd[cmd.index("--response") + 1])
        response_path.write_text(
            json.dumps(
                {
                    "success": True,
                    "result": {
                        "document": {
                            "segments": [
                                {
                                    "start": 0.0,
                                    "end": 1.0,
                                    "text": "hello",
                                    "language": "en",
                                    "confidence": 0.8,
                                }
                            ],
                            "language": "en",
                            "format": "srt",
                            "source_path": "result.srt",
                            "warnings": [],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("src.core.runtime.router.subprocess.run", fake_run)

    result = router.transcribe_file(
        {
            "input_path": "input.wav",
            "output_path": "result.srt",
            "profile": {"provider": "qwen3_asr"},
        }
    )

    assert result["document"]["segments"][0]["text"] == "hello"
