from __future__ import annotations

from types import SimpleNamespace


def test_voice_analysis_routes_catalog_model_id_through_asr_runtime(
    monkeypatch,
    tmp_path,
):
    from src.core.engines.asr import service as asr_service_module
    from src.core.tts.audio_preprocessor import AudioPreprocessor

    captured = {}

    class FakeRuntime:
        def transcribe_file(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                segments=[SimpleNamespace(start=0.0, end=1.25, text=" test ")]
            )

    monkeypatch.setattr(asr_service_module, "AsrEngineRuntime", FakeRuntime)
    monkeypatch.setattr(
        "src.config.config.get",
        lambda key, default=None: (
            "faster-whisper-base" if key == "processing.asr_model" else default
        ),
    )
    preprocessor = AudioPreprocessor(output_dir=str(tmp_path))

    result = preprocessor._run_asr(str(tmp_path / "input.wav"), language="ja")

    assert captured["profile"] == {
        "provider": "faster_whisper",
        "model": "faster-whisper-base",
        "common_options": {"language": "ja"},
        "provider_options": {"vad_filter": False},
    }
    assert result == [{"start": 0.0, "end": 1.25, "text": "test"}]
