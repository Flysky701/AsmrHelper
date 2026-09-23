from src.core.engines.tts.service import TtsEngineRuntime
from src.core.resources.model_service import ModelService
from src.core.runtime.profiles import RuntimeProfileResolver
from src.core.runtime.router import RuntimeRouter
from types import SimpleNamespace
import sys


def test_voxcpm_catalog_and_bootstrap_use_isolated_cuda_runtime(tmp_path, monkeypatch):
    resolver = RuntimeProfileResolver(tmp_path)
    profile = resolver.resolve("voxcpm2")
    assert profile.isolated and profile.cuda_torch
    assert profile.environment_dir == tmp_path / ".runtimes" / "voxcpm2"
    assert ModelService().get_model("voxcpm2").runtime_profile == profile.id
    monkeypatch.setattr("src.core.runtime.profiles.shutil.which", lambda _: "uv")
    monkeypatch.setattr(resolver, "_detect_nvidia_compute_capability", lambda: 12.0)
    commands = resolver.build_bootstrap_commands(profile)
    assert "torch==2.10.0+cu128" in commands[0]
    assert str(profile.python_executable) in commands[0]


def test_voxcpm_synthesis_does_not_import_engine_in_main_process(tmp_path, monkeypatch):
    router = RuntimeRouter(project_root=tmp_path)
    captured = []

    def worker(operation, payload, profile_id):
        captured.append((operation, payload, profile_id))
        return {"output_path": str(tmp_path / "speech.wav")}

    class Registry:
        def get(self, *args, **kwargs):
            raise AssertionError("VoxCPM must not load into the main CPU environment")

    monkeypatch.setattr(router, "_run_worker", worker)
    runtime = TtsEngineRuntime(registry=Registry(), runtime_router=router)
    output = runtime.synthesize_text(
        text="你好", output_path=str(tmp_path / "speech.wav"),
        profile={"provider": "voxcpm2", "model": "voxcpm2", "common_options": {}, "provider_options": {}},
    )
    assert output == str(tmp_path / "speech.wav")
    assert captured[0][0] == "tts.synthesize_text"
    assert captured[0][2] == "voxcpm2"


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
    assert TtsEngineRuntime._build_engine_kwargs("voxcpm2", {"model": "voxcpm2"})["load_denoiser"] is False
