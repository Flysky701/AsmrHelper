from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.core.engines.tts.service import TtsEngineRuntime
from src.core.resources.model_catalog import ModelEntry
from src.core.resources.model_status import ModelStatusResolver
from src.core.runtime.profiles import RuntimeProfileResolver
from src.core.runtime.router import RuntimeRouter


def test_runtime_profiles_resolve_project_relative_interpreters(tmp_path):
    resolver = RuntimeProfileResolver(project_root=tmp_path)

    main = resolver.resolve("main")
    qwen_tts = resolver.resolve("qwen_tts")

    assert main.isolated is False
    assert qwen_tts.isolated is True
    assert qwen_tts.environment_dir == tmp_path / ".runtimes" / "qwen_tts"
    assert qwen_tts.python_executable == qwen_tts.environment_dir / "Scripts" / "python.exe"


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
