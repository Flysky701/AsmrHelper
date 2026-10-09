from types import SimpleNamespace

import pytest

from src.core.runtime.profiles import RuntimeProfileResolver, RuntimeProbeError
from src.core.resources.model_catalog import ModelEntry
from src.core.resources.model_service import ModelService


@pytest.fixture
def resolver(tmp_path, monkeypatch):
    monkeypatch.delenv("ASMR_HELPER_COMPUTE", raising=False)
    monkeypatch.setattr("src.core.runtime.profiles.shutil.which", lambda name, **kwargs: "uv")
    return RuntimeProfileResolver(tmp_path)


def test_persistence_and_environment_override(resolver, monkeypatch):
    assert resolver.compute_mode() == "auto"
    resolver.save_compute_mode("cpu")
    assert RuntimeProfileResolver(resolver.project_root).compute_mode() == "cpu"
    monkeypatch.setenv("ASMR_HELPER_COMPUTE", "cuda")
    assert resolver.compute_mode() == "cuda"
    monkeypatch.setenv("ASMR_HELPER_COMPUTE", "invalid")
    with pytest.raises(ValueError):
        resolver.compute_mode()
    with pytest.raises(ValueError):
        resolver.save_compute_mode("invalid")


@pytest.mark.parametrize("profile,mode,gpu,target", [
    # Every environment uses the shared policy; GPU selection is tested once.
    ("main", "auto", None, "cpu"),
    ("qwen_asr", "auto", None, "cpu"),
    ("fun_asr", "auto", None, "cpu"),
    ("qwen_tts", "auto", None, "cpu"),
    ("voxcpm2", "auto", None, "cpu"),
    ("qwen_tts", "cpu", 12.0, "cpu"),
    ("qwen_tts", "auto", 8.9, "cu126"),
    ("qwen_tts", "cuda", 12.0, "cu128"),
])
def test_all_environments_share_pinned_policy(resolver, monkeypatch, profile, mode, gpu, target):
    resolver.save_compute_mode(mode)
    monkeypatch.setattr(resolver, "_detect_nvidia_compute_capability", lambda: gpu)
    commands = resolver.build_bootstrap_commands(resolver.resolve(profile))
    assert len(commands) == 1
    assert commands[0][commands[0].index("--torch-backend") + 1] == target
    assert "--index" not in commands[0]
    assert "https://pypi.org/simple" in commands[0]
    for package in ("torch", "torchaudio"):
        assert f"{package}==2.10.0+{target}" in commands[0]
        assert f"{package}==2.10.0+{target}" in resolver.compute_constraints().read_text()


def test_explicit_cuda_never_falls_back(resolver, monkeypatch):
    resolver.save_compute_mode("cuda")
    monkeypatch.setattr(resolver, "_detect_nvidia_compute_capability", lambda: None)
    with pytest.raises(RuntimeError, match="explicitly requested"):
        resolver.build_bootstrap_commands(resolver.resolve("qwen_asr"))


def test_verify_runs_real_tensor_script_and_rejects_failed_probe(resolver, monkeypatch):
    resolver.save_compute_mode("cpu")
    captured = []
    def run(cmd, **kwargs):
        captured.append(cmd)
        return SimpleNamespace(returncode=0, stdout='__ASMR_COMPUTE__{"target":"cpu"}', stderr='')
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", run)
    assert resolver.verify_compute(resolver.resolve("main")) == {"target": "cpu"}
    assert "a @ a" in captured[0][-1]
    assert "torchaudio.__version__" in captured[0][-1]
    monkeypatch.setattr("src.core.runtime.profiles.subprocess.run", lambda *a, **kw: SimpleNamespace(returncode=1, stderr="wrong torch build", stdout=""))
    with pytest.raises(RuntimeProbeError, match="wrong torch build"):
        resolver.verify_compute(resolver.resolve("main"))


def test_model_extras_cannot_override_torch_and_final_probe_required(resolver, monkeypatch):
    resolver.save_compute_mode("cpu")
    service = ModelService()
    service.runtime_resolver = resolver
    entry = ModelEntry(id="test", kind="local", category="asr", provider="test", display_name="Test", description="", install_root=str(resolver.project_root), install_path="model", required_python_extras=["funasr"], required_runtime_packages=["torch>=2.0"])
    commands = []
    monkeypatch.setattr("src.core.resources.model_service.subprocess.run", lambda cmd, **kw: (commands.append(cmd) or SimpleNamespace(returncode=0, stdout="", stderr="")))
    def rejected(profile):
        assert profile.id == "main"
        raise RuntimeProbeError("CUDA tensor failed")
    monkeypatch.setattr(resolver, "verify_compute", rejected)
    with pytest.raises(RuntimeProbeError, match="CUDA tensor failed"):
        service._install_runtime_packages(entry)
    assert len(commands) == 3
    assert all("--constraint" in cmd for cmd in commands[1:])
