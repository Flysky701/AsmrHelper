"""Contract tests for delivery instructions without loading model weights."""
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.core.tts import Qwen3TTSEngine, TTSEngine
from src.core.tts.speech_style import STYLE_INSTRUCTIONS
from src.core.engines.tts.registry import TtsRegistry
from src.core.engines.tts.service import TtsEngineRuntime


@pytest.fixture(autouse=True)
def no_model_import(monkeypatch):
    monkeypatch.setitem(sys.modules, "qwen_tts", SimpleNamespace())


def test_runtime_forwards_style_and_instruction(tmp_path, monkeypatch):
    synth = Mock(return_value=str(tmp_path / "sample.wav"))
    monkeypatch.setattr(Qwen3TTSEngine, "_synthesize", synth)
    registry = TtsRegistry()
    registry.register("qwen3", factory=lambda **kw: TTSEngine(engine="qwen3", **kw))
    runtime = TtsEngineRuntime(registry, enable_runtime_routing=False)
    runtime.synthesize_text(text="你好", output_path=str(tmp_path / "sample.wav"), profile={
        "provider": "qwen3", "common_options": {"voice": "Vivian"},
        "provider_options": {"speaking_style": "whisper", "instruct": "吐字清晰"},
    })
    assert synth.call_args.kwargs["instruct"] == STYLE_INSTRUCTIONS["whisper"] + "\n吐字清晰"


def test_alignment_retry_preserves_profile_and_whisper(monkeypatch):
    from src.core.tts import voice_profile
    profile = SimpleNamespace(category="preset", speaker="Vivian", instruct="温柔的语气")
    monkeypatch.setattr(voice_profile, "get_voice_manager", lambda: SimpleNamespace(get_by_id=lambda _: profile))
    engine = Qwen3TTSEngine(voice_profile_id="test", speaking_style="whisper")
    synth = Mock(return_value="fast.wav")
    monkeypatch.setattr(engine, "_synthesize", synth)
    engine.synthesize_with_instruct("你好", "fast.wav", "语速加快")
    assert synth.call_args.kwargs["instruct"] == "温柔的语气\n" + STYLE_INSTRUCTIONS["whisper"] + "\n语速加快"


@pytest.mark.parametrize("category", ["clone", "custom"])
def test_clone_rejects_style_before_loading_model(monkeypatch, category):
    from src.core.tts import voice_profile
    profile = SimpleNamespace(category=category, get_prompt_cache_path=lambda: "cache.pt")
    monkeypatch.setattr(voice_profile, "get_voice_manager", lambda: SimpleNamespace(get_by_id=lambda _: profile))
    with pytest.raises(ValueError, match="不支持风格指令"):
        Qwen3TTSEngine(voice_profile_id="test", speaking_style="whisper")


def test_default_does_not_inject_instruction(monkeypatch):
    engine = Qwen3TTSEngine()
    synth = Mock(return_value="normal.wav")
    monkeypatch.setattr(engine, "_synthesize", synth)
    engine.synthesize("你好", "normal.wav")
    assert synth.call_args.kwargs["instruct"] is None


def test_unknown_style_is_rejected():
    with pytest.raises(ValueError, match="speaking_style"):
        Qwen3TTSEngine(speaking_style="typo")


def test_timeline_retry_keeps_each_sentence_and_style(tmp_path, monkeypatch):
    import numpy as np
    import soundfile as sf

    engine = TTSEngine(engine="qwen3", voice="Vivian", speaking_style="whisper")
    calls = []

    def synth(text, output_path, instruct=None):
        calls.append((text, instruct))
        duration = 0.5 if "fast" in output_path else 2
        sf.write(output_path, np.full(int(24000 * duration), 0.1), 24000)
        return output_path

    monkeypatch.setattr(engine.engine, "_synthesize", synth)
    target = tmp_path / "timeline.wav"
    engine.synthesize_segments(
        [{"text": "第一句话", "start_time": 0, "end_time": 1},
         {"text": "第二句话", "start_time": 1, "end_time": 2}],
        str(tmp_path), str(target), reference_duration=2, sample_rate=24000,
    )
    assert [text for text, _ in calls] == ["第一句话", "第二句话", "第一句话", "第二句话"]
    assert all(STYLE_INSTRUCTIONS["whisper"] in instruction for _, instruction in calls)
    assert all(instruction != STYLE_INSTRUCTIONS["whisper"] for _, instruction in calls[2:])
    audio, sr = sf.read(target)
    assert audio.shape == (48000, 2)
    assert np.any(audio[:12000]) and np.any(audio[24000:36000])
    assert sr == 24000


def test_capability_exposes_experimental_style():
    from src.app.services.capability_descriptor_service import CapabilityDescriptorService

    descriptor = CapabilityDescriptorService().get_descriptor("tts", "qwen3")
    options = {item["name"]: item for item in descriptor["provider_option_schema"]}
    assert options["speaking_style"]["enum"] == ["normal", "soft", "whisper"]
    assert options["speaking_style"]["default"] == "normal"
    assert options["instruct"]["type"] == "string"
