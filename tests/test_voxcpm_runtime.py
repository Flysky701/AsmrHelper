from src.core.resources.model_service import ModelService
from src.core.runtime.profiles import RuntimeProfileResolver
from types import SimpleNamespace
import sys


def test_voxcpm_catalog_and_bootstrap_use_isolated_cuda_runtime(tmp_path, monkeypatch):
    resolver = RuntimeProfileResolver(tmp_path)
    profile = resolver.resolve("voxcpm2")
    assert profile.isolated and profile.cuda_torch
    assert profile.environment_dir == tmp_path / ".runtimes" / "voxcpm2"
    assert ModelService().get_model("voxcpm2").runtime_profile == profile.id
    monkeypatch.setattr("src.core.runtime.profiles.shutil.which", lambda _, **kwargs: "uv")
    monkeypatch.setattr(resolver, "_detect_nvidia_compute_capability", lambda: 12.0)
    commands = resolver.build_bootstrap_commands(profile)
    assert "torch==2.10.0+cu128" in commands[0]
    assert str(profile.python_executable) in commands[0]




def test_windows_voxcpm_uses_eager_inference_and_selected_device(monkeypatch):
    from src.core.engines.tts.voxcpm2 import VoxCPM2Engine
    captured = {}

    def load(path, **options):
        captured.update(options)
        return object()

    monkeypatch.setitem(sys.modules, "voxcpm", SimpleNamespace(VoxCPM=SimpleNamespace(from_pretrained=load)))
    monkeypatch.setattr(sys, "platform", "win32")
    VoxCPM2Engine(model_dir="local-model", device_map="cuda:0")
    assert captured == {"device": "cuda:0", "load_denoiser": False, "optimize": False}
