from types import SimpleNamespace
import sys


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
