from __future__ import annotations

from types import SimpleNamespace


def test_asr_recognizer_prefers_installed_local_model_directory(monkeypatch, tmp_path):
    import src.core.asr as asr_module

    local_model_dir = tmp_path / "models" / "whisper" / "base"
    local_model_dir.mkdir(parents=True)
    captured: dict[str, object] = {}

    class FakeWhisperModel:
        def __init__(self, model_reference, **kwargs):
            captured["model_reference"] = model_reference
            captured.update(kwargs)

    monkeypatch.setattr(asr_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(asr_module, "WhisperModel", FakeWhisperModel)

    asr_module.ASRRecognizer(model_size="base", device="cpu")

    assert captured["model_reference"] == str(local_model_dir)
    assert captured["download_root"] is None


def test_asr_runtime_prefers_managed_local_model_directory(monkeypatch, tmp_path):
    import src.core.resources.model_reference as reference_module
    from src.core.engines.asr.service import _resolve_model_name

    local_model_dir = tmp_path / "models" / "qwen3-asr"
    local_model_dir.mkdir(parents=True)
    entry = SimpleNamespace(
        resolved_install_dir=lambda: local_model_dir,
        upstream_name="Qwen/Qwen3-ASR-0.6B",
    )
    monkeypatch.setattr(reference_module._catalog, "get", lambda model_id: entry)

    assert _resolve_model_name("qwen3_asr", "qwen3-asr-0.6b") == str(local_model_dir)
