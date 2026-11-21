from __future__ import annotations

from types import SimpleNamespace


from src.core.resources.model_catalog import ModelEntry
from src.core.resources.model_status import ModelStatusResolver
from src.core.runtime.profiles import RuntimeProfileResolver
from src.core.runtime.router import RuntimeRouter


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




def test_runtime_router_reads_structured_asr_worker_result(tmp_path, monkeypatch):
    resolver = RuntimeProfileResolver(project_root=tmp_path)
    profile = resolver.resolve("qwen_asr")
    profile.python_executable.parent.mkdir(parents=True)
    profile.python_executable.write_bytes(b"python")
    router = RuntimeRouter(resolver=resolver, project_root=tmp_path)

    from contextlib import contextmanager

    from packages.gpu_worker.client import ComputeClient
    from packages.protocol.compute import AsrResult, AsrSegmentItem

    def transcribe(request):
        assert request.provider == "qwen3_asr"
        assert request.input_path == "input.wav"
        return AsrResult(
            segments=[AsrSegmentItem(start=0.0, end=1.0, text="hello", confidence=0.8)],
            language="en",
            format="srt",
            source_path="result.srt",
        )

    @contextmanager
    def local_client(**kwargs):
        assert kwargs["python_executable"] == profile.python_executable
        yield SimpleNamespace(asr=transcribe)

    monkeypatch.setattr(ComputeClient, "from_local", local_client)

    result = router.transcribe_file(
        {
            "input_path": "input.wav",
            "output_path": "result.srt",
            "profile": {"provider": "qwen3_asr"},
        }
    )

    assert result["document"]["segments"][0]["text"] == "hello"
