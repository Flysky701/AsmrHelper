from __future__ import annotations

import sys
import types


def test_kokoro_tts_engine_saves_audio(tmp_path, monkeypatch):
    captured = {}

    class FakePipeline:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def __call__(self, text, voice, speed, split_pattern):
            assert text == "hello"
            assert voice == "af_heart"
            assert speed == 1.0
            assert split_pattern == r"\n+"
            return [
                ("g1", "p1", [0.1, 0.2]),
                ("g2", "p2", [0.3, 0.4]),
            ]

    class FakeSoundFileModule:
        @staticmethod
        def write(path, audio, sample_rate):
            captured["path"] = path
            captured["audio"] = list(audio)
            captured["sample_rate"] = sample_rate

    fake_module = types.SimpleNamespace(KPipeline=FakePipeline)
    monkeypatch.setitem(sys.modules, "kokoro", fake_module)
    monkeypatch.setitem(sys.modules, "soundfile", FakeSoundFileModule)

    from src.core.engines.tts.kokoro import KokoroTtsEngine

    output_path = tmp_path / "kokoro.wav"
    engine = KokoroTtsEngine(voice="af_heart", speed=1.0)
    written = engine.synthesize("hello", str(output_path))

    assert written == str(output_path)
    assert captured["path"] == str(output_path)
    assert captured["sample_rate"] == 24000
    assert captured["audio"] == [0.1, 0.2, 0.3, 0.4]


def test_kokoro_tts_engine_infers_lang_code_from_voice(tmp_path, monkeypatch):
    captured = {}

    class FakePipeline:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __call__(self, text, voice, speed, split_pattern):
            return [("g", "p", [0.1, 0.2])]

    class FakeSoundFileModule:
        @staticmethod
        def write(path, audio, sample_rate):
            captured["path"] = path
            captured["sample_rate"] = sample_rate

    fake_module = types.SimpleNamespace(KPipeline=FakePipeline)
    monkeypatch.setitem(sys.modules, "kokoro", fake_module)
    monkeypatch.setitem(sys.modules, "soundfile", FakeSoundFileModule)

    from src.core.engines.tts.kokoro import KokoroTtsEngine

    engine = KokoroTtsEngine(voice="zf_001")
    engine.synthesize("ni hao", str(tmp_path / "zh.wav"))

    assert captured["lang_code"] == "z"
