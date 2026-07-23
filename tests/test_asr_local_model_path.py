from __future__ import annotations


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
