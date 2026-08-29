from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf

from src.core.subtitles.text_utils import detect_language, normalize_language_code
from src.core.tts import audio_preprocessor as audio_module
from src.core.tts.audio_preprocessor import AudioPreprocessor
from src.utils import cut_audio_by_subtitle


def _write_voice_like_audio(
    path,
    *,
    duration: float = 6.0,
    boundary_silence: float = 0.25,
) -> None:
    sample_rate = 8_000
    sample_count = int(sample_rate * duration)
    timeline = np.arange(sample_count, dtype=np.float64) / sample_rate
    data = (
        0.11 * np.sin(2.0 * np.pi * 180.0 * timeline)
        + 0.025 * np.sin(2.0 * np.pi * 360.0 * timeline)
    )
    boundary_samples = int(sample_rate * boundary_silence)
    if boundary_samples:
        data[:boundary_samples] = 0.0
        data[-boundary_samples:] = 0.0
    sf.write(path, data, sample_rate, subtype="FLOAT")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("zh", "zh"),
        ("zh_CN", "zh"),
        ("zh-TW", "zh"),
        ("Chinese", "zh"),
        ("en-US", "en"),
        ("English", "en"),
        ("ja-JP", "ja"),
        ("Japanese", "ja"),
    ],
)
def test_normalize_language_code_accepts_supported_aliases(value: str, expected: str) -> None:
    assert normalize_language_code(value) == expected


def test_detect_language_handles_english_and_natural_japanese() -> None:
    assert detect_language(["Hello, this is an English subtitle."]) == "en"
    assert detect_language(["今日は音色クローンのテストです。"]) == "ja"
    assert normalize_language_code(detect_language(["你好，这是中文字幕。"])) == "zh"


def test_clone_conversion_preserves_source_sample_rate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    captured: dict[str, list[str]] = {}

    def run(cmd, **_kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(audio_module, "get_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(audio_module.subprocess, "run", run)

    output = tmp_path / "converted.wav"
    AudioPreprocessor(str(tmp_path))._convert_to_clone_spec("input.flac", str(output))

    assert "-ar" not in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("-ac") + 1] == "1"
    assert "pcm_s16le" in captured["cmd"]


def test_cut_entries_clamp_both_ends_without_swallowing_audio_tail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    captured: dict[str, list[dict]] = {}
    monkeypatch.setattr(
        audio_module,
        "get_audio_info",
        lambda _path: {"duration": 100.0},
    )

    def cut(_audio_path, entries, _output_dir, prefix):
        captured["entries"] = entries
        assert prefix == "seg"
        return [dict(entry, path=f"segment-{index}.wav", duration=1.0) for index, entry in enumerate(entries)]

    monkeypatch.setattr(audio_module, "cut_audio_by_subtitle", cut)
    result = AudioPreprocessor(str(tmp_path))._cut_with_entries(
        "input.wav",
        [
            {"start": -0.20, "end": 1.0, "text": "first"},
            {"start": 5.0, "end": 10.0, "text": "last"},
        ],
    )

    assert captured["entries"][0]["start"] == 0.0
    assert captured["entries"][0]["end"] == pytest.approx(1.05)
    assert captured["entries"][1]["start"] == pytest.approx(4.95)
    assert captured["entries"][1]["end"] == pytest.approx(10.05)
    assert [segment["text"] for segment in result] == ["first", "last"]


def test_shared_audio_cutter_clamps_negative_start_and_writes_pcm16(tmp_path) -> None:
    source = tmp_path / "source.wav"
    sf.write(source, np.full(8000, 0.1), 8000, subtype="FLOAT")

    result = cut_audio_by_subtitle(
        str(source),
        [{"start": -1.0, "end": 0.25, "text": "hello"}],
        str(tmp_path / "segments"),
    )

    assert result[0]["start"] == 0.0
    assert result[0]["duration"] == pytest.approx(0.25)
    assert sf.info(result[0]["path"]).subtype == "PCM_16"


def test_filter_never_recycles_silence_or_long_segments_into_merge(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    silent = tmp_path / "silent.wav"
    short_voice = tmp_path / "short.wav"
    long_voice = tmp_path / "long.wav"
    sf.write(silent, np.zeros(8000), 8000)
    sf.write(short_voice, np.full(12_800, 0.1), 8000)
    sf.write(long_voice, np.full(248_000, 0.1), 8000)

    merged_inputs: list[dict] = []

    def merge(segments):
        merged_inputs.extend(segments)
        return []

    preprocessor = AudioPreprocessor(str(tmp_path))
    monkeypatch.setattr(preprocessor, "_merge_short_segments", merge)
    monkeypatch.setattr(
        preprocessor,
        "_trim_segment",
        lambda _segment: pytest.fail("long segments must not be trimmed"),
    )

    valid = preprocessor._filter_valid_segments(
        [
            {"path": str(silent), "start": 0.0, "end": 1.0, "duration": 1.0, "text": "silence"},
            {"path": str(short_voice), "start": 1.0, "end": 2.6, "duration": 1.6, "text": "voice"},
            {"path": str(long_voice), "start": 3.0, "end": 34.0, "duration": 31.0, "text": "long"},
        ]
    )

    assert valid == []
    assert [segment["path"] for segment in merged_inputs] == [str(short_voice)]


def test_merge_revalidates_actual_audio_duration(tmp_path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    sf.write(first, np.full(9600, 0.1), 8000)
    sf.write(second, np.full(9600, 0.1), 8000)

    merged = AudioPreprocessor(str(tmp_path))._do_merge(
        [
            {"path": str(first), "start": 0.0, "end": 1.2, "text": ""},
            {"path": str(second), "start": 2.0, "end": 3.2, "text": ""},
        ]
    )

    # The timeline span is 3.2s, but concatenated audio is only about 2.39s.
    assert merged is None


def test_concatenate_outputs_mono_pcm16_and_keeps_sample_rate(tmp_path) -> None:
    source = tmp_path / "stereo-float.wav"
    stereo = np.column_stack([np.full(22_050, 0.1), np.full(22_050, 0.2)])
    sf.write(source, stereo, 22_050, subtype="FLOAT")
    output = tmp_path / "reference.wav"

    AudioPreprocessor(str(tmp_path))._concatenate_audio_segments(
        [{"path": str(source), "text": "hello"}],
        str(output),
    )

    info = sf.info(output)
    assert info.samplerate == 22_050
    assert info.channels == 1
    assert info.subtype == "PCM_16"


def test_recommendation_uses_quality_score_before_raw_rms(tmp_path) -> None:
    louder_but_poor_text = {
        "duration": 6.0,
        "rms": 0.2,
        "text": "a",
        "quality_score": 55,
        "eligible": True,
    }
    quieter_complete_text = {
        "duration": 6.0,
        "rms": 0.1,
        "text": "complete transcript",
        "quality_score": 88,
        "eligible": True,
    }

    selected = AudioPreprocessor(str(tmp_path))._select_best_segments(
        [louder_but_poor_text, quieter_complete_text]
    )

    assert selected == [quieter_complete_text]


def test_quality_details_expose_lightweight_audio_metrics_and_subscores(tmp_path) -> None:
    source = tmp_path / "clean.wav"
    _write_voice_like_audio(source)

    quality = AudioPreprocessor(str(tmp_path)).evaluate_segment_quality(
        {
            "path": str(source),
            "start": 0.0,
            "end": 6.0,
            "duration": 6.0,
            "text": "complete aligned transcript",
        }
    )

    assert quality["eligible"] is True
    assert quality["score"] >= 60
    assert quality["label"] != "不合格"
    assert {
        "duration",
        "rms",
        "peak",
        "clipping_ratio",
        "speech_or_active_ratio",
        "boundary_energy_ratio",
        "noise_rms",
        "signal_rms",
        "snr_db",
        "duration_score",
        "rms_score",
        "text_score",
        "clipping_score",
        "peak_score",
        "active_score",
        "boundary_score",
        "snr_score",
    } <= quality["details"].keys()
    assert quality["details"]["peak"] > 0.0
    assert quality["details"]["clipping_ratio"] == 0.0
    assert quality["details"]["speech_or_active_ratio"] > 0.0


def test_quality_requires_text_only_for_icl(tmp_path) -> None:
    source = tmp_path / "voice.wav"
    _write_voice_like_audio(source)
    segment = {
        "path": str(source),
        "start": 0.0,
        "end": 6.0,
        "duration": 6.0,
        "text": "",
    }
    preprocessor = AudioPreprocessor(str(tmp_path))

    icl_quality = preprocessor.evaluate_segment_quality(segment, require_text=True)
    x_vector_quality = preprocessor.evaluate_segment_quality(
        segment,
        require_text=False,
    )

    assert icl_quality["eligible"] is False
    assert icl_quality["label"] == "不合格"
    assert any("ICL" in reason for reason in icl_quality["reasons"])
    assert x_vector_quality["eligible"] is True
    assert x_vector_quality["details"]["text_score"] == 100
    assert not any("ICL" in reason for reason in x_vector_quality["reasons"])


def test_quality_hard_rejects_obvious_clipping(tmp_path) -> None:
    source = tmp_path / "clipped.wav"
    data = np.ones(48_000, dtype=np.float64)
    data[:2_000] = 0.0
    data[-2_000:] = 0.0
    sf.write(source, data, 8_000, subtype="FLOAT")

    quality = AudioPreprocessor(str(tmp_path)).evaluate_segment_quality(
        {
            "path": str(source),
            "start": 0.0,
            "end": 6.0,
            "duration": 6.0,
            "text": "aligned transcript",
        }
    )

    assert quality["eligible"] is False
    assert quality["label"] == "不合格"
    assert quality["details"]["clipping_ratio"] > 0.01
    assert any("削波" in reason for reason in quality["reasons"])


def test_quality_hard_rejects_silence_and_invalid_timeline(tmp_path) -> None:
    silent = tmp_path / "silent.wav"
    clean = tmp_path / "clean.wav"
    sf.write(silent, np.zeros(48_000), 8_000, subtype="FLOAT")
    _write_voice_like_audio(clean)
    preprocessor = AudioPreprocessor(str(tmp_path))

    silence_quality = preprocessor.evaluate_segment_quality(
        {
            "path": str(silent),
            "start": 0.0,
            "end": 6.0,
            "duration": 6.0,
            "text": "aligned transcript",
        }
    )
    timeline_quality = preprocessor.evaluate_segment_quality(
        {
            "path": str(clean),
            "start": -0.1,
            "end": 5.9,
            "duration": 6.0,
            "text": "aligned transcript",
        }
    )

    assert silence_quality["eligible"] is False
    assert silence_quality["details"]["speech_or_active_ratio"] == 0.0
    assert any("有效语音" in reason for reason in silence_quality["reasons"])
    assert timeline_quality["eligible"] is False
    assert any("时间轴越界" in reason for reason in timeline_quality["reasons"])


def test_quality_reports_high_boundary_energy_without_hard_reject(tmp_path) -> None:
    source = tmp_path / "hard-boundary.wav"
    _write_voice_like_audio(source, boundary_silence=0.0)

    quality = AudioPreprocessor(str(tmp_path)).evaluate_segment_quality(
        {
            "path": str(source),
            "start": 0.0,
            "end": 6.0,
            "duration": 6.0,
            "text": "aligned transcript",
        }
    )

    assert quality["eligible"] is True
    assert quality["details"]["boundary_energy_ratio"] > 0.8
    assert quality["details"]["boundary_score"] < 80
    assert any("边界能量" in reason for reason in quality["reasons"])


def test_recommendation_ignores_ineligible_high_score_candidate(tmp_path) -> None:
    rejected = {
        "duration": 6.0,
        "rms": 0.2,
        "quality_score": 99,
        "eligible": False,
    }
    accepted = {
        "duration": 6.0,
        "rms": 0.1,
        "quality_score": 80,
        "eligible": True,
    }

    selected = AudioPreprocessor(str(tmp_path))._select_best_segments(
        [rejected, accepted]
    )

    assert selected == [accepted]


def test_low_asr_confidence_is_soft_warning_but_not_auto_recommended(tmp_path) -> None:
    source = tmp_path / "voice.wav"
    _write_voice_like_audio(source)
    preprocessor = AudioPreprocessor(str(tmp_path))
    segment = {
        "path": str(source),
        "start": 0.0,
        "end": 6.0,
        "duration": 6.0,
        "text": "recognized but uncertain transcript",
        "asr_confidence": 0.35,
    }

    quality = preprocessor.evaluate_segment_quality(segment, require_text=True)
    segment.update(
        quality_score=quality["score"],
        score=quality["score"],
        details=quality["details"],
        eligible=quality["eligible"],
        reasons=quality["reasons"],
    )

    assert quality["eligible"] is True
    assert quality["details"]["asr_confidence"] == 0.35
    assert any("ASR 置信度" in reason for reason in quality["reasons"])
    assert preprocessor._select_best_segments([segment]) == []


def test_prepare_clone_audio_reuses_supplied_asr_segments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    supplied = [{"start": 0.0, "end": 5.0, "text": "supplied transcript"}]
    segment = {
        "path": str(tmp_path / "segment.wav"),
        "start": 0.0,
        "end": 5.0,
        "duration": 5.0,
        "rms": 0.1,
        "text": "supplied transcript",
    }
    preprocessor = AudioPreprocessor(str(tmp_path))

    monkeypatch.setattr(
        audio_module,
        "get_audio_info",
        lambda _path: {"sample_rate": 24_000, "channels": 1, "duration": 5.0},
    )
    monkeypatch.setattr(preprocessor, "_convert_to_clone_spec", lambda _source, output: output)
    monkeypatch.setattr(
        preprocessor,
        "_run_asr",
        lambda *_args, **_kwargs: pytest.fail("supplied ASR must be reused"),
    )

    def cut(_path, entries, _callback):
        assert entries == supplied
        return [segment]

    monkeypatch.setattr(preprocessor, "_cut_with_entries", cut)
    monkeypatch.setattr(preprocessor, "_filter_valid_segments", lambda segments, _callback: segments)
    monkeypatch.setattr(preprocessor, "_select_best_segments", lambda segments: segments)
    monkeypatch.setattr(preprocessor, "_concatenate_audio_segments", lambda _segments, output: output)

    result = preprocessor.prepare_clone_audio(
        str(source),
        audio_language="en",
        asr_segments=supplied,
    )

    assert result.mode == "asr"
    assert result.ref_text == "supplied transcript"


@pytest.mark.parametrize(
    ("require_text", "expected_mode", "expected_text"),
    [(True, "asr", "recognized text"), (False, "energy", "")],
)
def test_analysis_respects_language_and_can_skip_asr_for_x_vector(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    require_text: bool,
    expected_mode: str,
    expected_text: str,
) -> None:
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    preprocessor = AudioPreprocessor(str(tmp_path))
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        audio_module,
        "get_audio_info",
        lambda _path: {"sample_rate": 24_000, "channels": 1, "duration": 6.0},
    )
    monkeypatch.setattr(preprocessor, "_convert_to_clone_spec", lambda _source, output: output)

    def asr(_path, language, progress_callback=None):
        captured["language"] = language
        return [{"start": 0.0, "end": 6.0, "text": "recognized text"}]

    monkeypatch.setattr(preprocessor, "_run_asr", asr)
    monkeypatch.setattr(
        preprocessor,
        "_detect_energy_entries",
        lambda _path: [{"start": 0.0, "end": 6.0, "text": ""}],
    )

    def cut(_path, entries, _callback):
        segment_path = tmp_path / "segment.wav"
        _write_voice_like_audio(segment_path)
        return [
            {
                "path": str(segment_path),
                "start": 0.0,
                "end": 6.0,
                "duration": 6.0,
                "rms": 0.1,
                "text": entries[0]["text"],
            }
        ]

    monkeypatch.setattr(preprocessor, "_cut_with_entries", cut)
    monkeypatch.setattr(preprocessor, "_filter_valid_segments", lambda segments, _callback: segments)

    result = preprocessor.analyze_segments(
        str(source),
        audio_language="en-US",
        require_text=require_text,
    )

    assert result["mode"] == expected_mode
    assert result["segments"][0]["text"] == expected_text
    assert result["segments"][0]["score"] >= 0
    assert result["segments"][0]["details"]
    assert result["segments"][0]["eligible"] is True
    if require_text:
        assert captured["language"] == "en"
    else:
        assert "language" not in captured
        assert result["segments"][0]["details"]["text_score"] == 100
