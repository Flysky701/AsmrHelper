"""Tests for Milestone 2A ASMR DSP & pre-ASR acoustic VAD operators."""

from __future__ import annotations

import math
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
import soundfile as sf

from src.app.services.artifact_service import ArtifactService
from src.app.services.speech_service import SpeechService
from src.app.services.task_service import TaskService
from src.core.engines.asr.anime_whisper import AnimeWhisperRecognizer
from src.core.engines.asr.vad_slicer import slice_speech_regions
from src.core.speech.providers import get_provider
from src.core.speech.store import SpeechStore
from src.mixer.binaural import estimate_cue_panning


def _tone(duration_sec: float, sr: int = 16000, freq: float = 220.0, amp: float = 0.18) -> np.ndarray:
    t = np.arange(round(duration_sec * sr), dtype=np.float32) / float(sr)
    return (amp * np.sin(2.0 * math.pi * freq * t)).astype(np.float32)


# ---------------------------------------------------------------------------
# 1. Pre-ASR Acoustic VAD Slicer & AnimeWhisperRecognizer VAD Integration
# ---------------------------------------------------------------------------


def test_vad_slicer_splits_across_29s_silence_gap_and_bridges_short_pauses():
    sr = 16000
    # Cue 1: 0.5s..2.2s with an internal 0.25s short pause (< min_silence_sec=0.65)
    audio = np.zeros(35 * sr, dtype=np.float32)
    audio[int(0.5 * sr) : int(1.2 * sr)] = _tone(0.7, sr, amp=0.2)
    audio[int(1.45 * sr) : int(2.2 * sr)] = _tone(0.75, sr, amp=0.2)
    # 29.0s silence gap: 2.2s..31.2s
    # Cue 2: 31.2s..33.0s
    audio[int(31.2 * sr) : int(33.0 * sr)] = _tone(1.8, sr, amp=0.16)

    regions = slice_speech_regions(audio, sample_rate=sr, min_silence_sec=0.65, pad_sec=0.15)
    assert len(regions) == 2
    (s0, e0), (s1, e1) = regions
    assert s0 == pytest.approx(0.35, abs=0.05)
    assert e0 == pytest.approx(2.35, abs=0.05)
    assert s1 == pytest.approx(31.05, abs=0.05)
    assert e1 == pytest.approx(33.15, abs=0.05)
    # Ensure the 29s silence gap is never included
    assert s1 - e0 > 28.0


def test_vad_slicer_adapts_to_elevated_noise_floor_and_handles_empty_or_silent_audio():
    sr = 16000
    rng = np.random.default_rng(42)
    # Elevated background room noise around -37 dBFS across 20s, plus two -16 dBFS speech bursts
    noise = (rng.standard_normal(20 * sr) * 0.014).astype(np.float32)
    noise[int(1.0 * sr) : int(2.5 * sr)] += _tone(1.5, sr, amp=0.22)
    noise[int(16.0 * sr) : int(17.5 * sr)] += _tone(1.5, sr, amp=0.22)

    regions = slice_speech_regions(noise, sample_rate=sr, min_silence_sec=0.65, pad_sec=0.15)
    assert len(regions) == 2
    assert regions[0][0] == pytest.approx(0.85, abs=0.1)
    assert regions[0][1] == pytest.approx(2.65, abs=0.1)
    assert regions[1][0] == pytest.approx(15.85, abs=0.1)
    assert regions[1][1] == pytest.approx(17.65, abs=0.1)

    assert slice_speech_regions(np.array([], dtype=np.float32), sample_rate=sr) == []
    assert slice_speech_regions(np.zeros(5 * sr, dtype=np.float32), sample_rate=sr) == []


def test_vad_slicer_subdivides_continuous_speech_over_max_chunk_at_quietest_valley():
    sr = 16000
    # 54 seconds of continuous speech (> 25s max_chunk_sec) with two quiet breath dips at 18s and 37s
    audio = _tone(54.0, sr, freq=180.0, amp=0.20)
    # Dip 1 around 18.0s..18.25s (still above silence threshold or shorter than min_silence_sec)
    audio[int(18.0 * sr) : int(18.25 * sr)] *= 0.08
    # Dip 2 around 37.0s..37.25s
    audio[int(37.0 * sr) : int(37.25 * sr)] *= 0.08

    regions = slice_speech_regions(
        audio,
        sample_rate=sr,
        min_silence_sec=0.65,
        max_chunk_sec=25.0,
        pad_sec=0.15,
    )
    assert len(regions) == 3
    for start, end in regions:
        assert 0.0 <= start < end <= 54.0
        assert (end - start) <= 25.0 + 1e-6

    # Splits should land inside the quiet valleys near ~18.1s and ~37.1s
    assert regions[0][1] == pytest.approx(18.12, abs=0.25)
    assert regions[1][0] == regions[0][1]
    assert regions[1][1] == pytest.approx(37.12, abs=0.25)
    assert regions[2][0] == regions[1][1]
    assert regions[2][1] == pytest.approx(54.0, abs=0.05)


def test_anime_whisper_vad_slicing_offsets_chunk_timestamps_accurately(tmp_path, monkeypatch):
    sr = 16000
    audio = np.zeros(36 * sr, dtype=np.float32)
    # Utterance 1 at [1.0s, 2.0s], 29s silence gap, Utterance 2 at [31.0s, 32.4s]
    audio[int(1.0 * sr) : int(2.0 * sr)] = _tone(1.0, sr, amp=0.22)
    audio[int(31.0 * sr) : int(32.4 * sr)] = _tone(1.4, sr, amp=0.22)

    chunk_outputs = [
        {
            "text": "おやすみなさい。",
            "chunks": [{"timestamp": (0.15, 1.12), "text": " おやすみなさい。"}],
        },
        {
            "text": "また明日ね。",
            "chunks": [
                {"timestamp": (0.15, 0.85), "text": "また"},
                {"timestamp": (0.86, 1.50), "text": "明日ね。"},
            ],
        },
    ]
    pipe = MagicMock(side_effect=chunk_outputs)
    factory = MagicMock(return_value=pipe)
    torch_stub = SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False, empty_cache=MagicMock()),
        float16="fp16",
        float32="fp32",
    )
    monkeypatch.setitem(sys.modules, "torch", torch_stub)
    monkeypatch.setitem(sys.modules, "transformers", SimpleNamespace(pipeline=factory))

    recognizer = AnimeWhisperRecognizer.with_vad_slicing(model_size="litagin/anime-whisper")
    assert recognizer.vad_slicing is True
    monkeypatch.setattr(recognizer, "_read_audio", lambda _: audio)

    srt_out = tmp_path / "vad_out.srt"
    segments = recognizer.recognize("synthetic.wav", str(srt_out))

    assert pipe.call_count == 2
    # Each chunk passed to Whisper is < 3s rather than the full 36s recording
    first_chunk_len = pipe.call_args_list[0].args[0]["raw"].shape[0] / sr
    second_chunk_len = pipe.call_args_list[1].args[0]["raw"].shape[0] / sr
    assert first_chunk_len < 2.0
    assert second_chunk_len < 2.5

    assert len(segments) == 3
    assert segments[0]["text"] == "おやすみなさい。"
    assert segments[0]["start"] == pytest.approx(1.0, abs=0.06)
    assert segments[0]["end"] == pytest.approx(1.97, abs=0.06)

    assert segments[1]["text"] == "また"
    assert segments[1]["start"] == pytest.approx(31.0, abs=0.06)
    assert segments[2]["text"] == "明日ね。"
    assert segments[2]["end"] == pytest.approx(32.35, abs=0.06)
    assert srt_out.exists()
    srt_text = srt_out.read_text(encoding="utf-8")
    assert "おやすみなさい。" in srt_text
    assert "00:00:31," in srt_text or "00:00:30,9" in srt_text


# ---------------------------------------------------------------------------
# 2. Binaural Panning Estimation, Constant-Power Mapping & Slack Slot Planner
# ---------------------------------------------------------------------------


def test_estimate_cue_panning_streams_slice_only_and_detects_left_right_center(tmp_path, monkeypatch):
    sr = 48000
    # 10s stereo WAV: [0..2s] hard left, [3..5s] hard right, [6..8s] center
    stereo = np.zeros((10 * sr, 2), dtype=np.float32)
    t_cue = _tone(1.5, sr, freq=260.0, amp=0.25)
    # Cue 1 (0.25..1.75s): Left ear dominant (with minor -24 dB right bleed)
    stereo[int(0.25 * sr) : int(1.75 * sr), 0] = t_cue
    stereo[int(0.25 * sr) : int(1.75 * sr), 1] = t_cue * 0.05
    # Cue 2 (3.25..4.75s): Right ear dominant
    stereo[int(3.25 * sr) : int(4.75 * sr), 0] = t_cue * 0.04
    stereo[int(3.25 * sr) : int(4.75 * sr), 1] = t_cue
    # Cue 3 (6.25..7.75s): Center equal
    stereo[int(6.25 * sr) : int(7.75 * sr), 0] = t_cue * 0.8
    stereo[int(6.25 * sr) : int(7.75 * sr), 1] = t_cue * 0.8

    stereo_path = tmp_path / "binaural_48k.wav"
    sf.write(stereo_path, stereo, sr, subtype="FLOAT")

    # Verify streaming seek+read reads only the cue window, never the full 10s file
    real_soundfile = sf.SoundFile
    frames_read_log: list[int] = []

    class TrackingSoundFile:
        def __init__(self, *args, **kwargs):
            self._inner = real_soundfile(*args, **kwargs)

        def __enter__(self):
            self._inner.__enter__()
            return self

        def __exit__(self, *exc):
            return self._inner.__exit__(*exc)

        @property
        def channels(self):
            return self._inner.channels

        @property
        def frames(self):
            return self._inner.frames

        @property
        def samplerate(self):
            return self._inner.samplerate

        def seek(self, frames):
            return self._inner.seek(frames)

        def read(self, frames=-1, **kwargs):
            data = self._inner.read(frames, **kwargs)
            frames_read_log.append(len(data))
            return data

        def __getattr__(self, name):
            return getattr(self._inner, name)

    monkeypatch.setattr(sf, "SoundFile", TrackingSoundFile)

    pan_left = estimate_cue_panning(stereo_path, 0.0, 2.0)
    assert sum(frames_read_log) == 2 * sr  # Read 2.0s, NOT 10.0s!
    assert -0.95 <= pan_left < -0.7

    frames_read_log.clear()
    pan_right = estimate_cue_panning(stereo_path, 3.0, 5.0)
    assert sum(frames_read_log) == 2 * sr
    assert 0.7 < pan_right <= 0.95

    pan_center = estimate_cue_panning(stereo_path, 6.0, 8.0)
    assert pan_center == pytest.approx(0.0, abs=1e-4)

    # Silent region [8.5..9.5s] -> 0.0
    assert estimate_cue_panning(stereo_path, 8.5, 9.5) == 0.0

    # Mono file -> 0.0 immediately
    mono_path = tmp_path / "mono.wav"
    real_sf_write = sf.write
    real_sf_write(mono_path, t_cue, sr)
    frames_read_log.clear()
    assert estimate_cue_panning(mono_path, 0.0, 1.0) == 0.0
    assert frames_read_log == []


# ---------------------------------------------------------------------------
# 3. SpeechService End-to-End Binaural Panning & Silence Slack Borrowing
# ---------------------------------------------------------------------------


@pytest.fixture
def speech_env(tmp_path):
    service = SpeechService(
        store=SpeechStore(tmp_path / "speech_lab"),
        tasks=TaskService(),
        artifacts=ArtifactService(),
    )
    conn = service.save_connection({"name": "Edge", "provider_id": "edge", "deployment": "cloud"})
    voice = service.store.create("voices", {"name": "ASMR", "bindings": [], "default_binding": "edge"})
    recipe = service.save_recipe(
        {
            "name": "ASMR Voice",
            "voice_id": voice["id"],
            "provider_id": "edge",
            "model": "edge-tts",
            "mode": "builtin",
            "connection_ref": conn["id"],
            "variant": {"kind": "builtin", "value": "zh-CN-XiaoxiaoNeural", "style": "normal"},
            "language": "zh",
            "provider_options": {"schema_version": 1},
        }
    )
    return service, recipe


def test_speech_service_binaural_panning_renders_48khz_stereo_following_ears(
    speech_env, tmp_path, monkeypatch
):
    service, recipe = speech_env

    # TTS provider emits 24 kHz mono takes (0.6s each)
    def fake_synthesize(request, path, context, cancel):
        sf.write(path, _tone(0.6, sr=24000, freq=300.0, amp=0.2), 24000)
        return {"model": request["model"]}

    monkeypatch.setattr(get_provider("edge"), "synthesize", fake_synthesize)

    # 48 kHz 2-channel separated vocal stem: Left ear -> Right ear -> Center
    sr_ref = 48000
    binaural_stem = np.zeros((6 * sr_ref, 2), dtype=np.float32)
    cue_wave = _tone(0.8, sr=sr_ref, freq=240.0, amp=0.25)
    # Cue 1 [0.2, 1.0]: Left ear
    binaural_stem[round(0.2 * sr_ref) : round(1.0 * sr_ref), 0] = cue_wave
    binaural_stem[round(0.2 * sr_ref) : round(1.0 * sr_ref), 1] = cue_wave * 0.03
    # Cue 2 [2.0, 2.8]: Right ear
    binaural_stem[round(2.0 * sr_ref) : round(2.8 * sr_ref), 0] = cue_wave * 0.03
    binaural_stem[round(2.0 * sr_ref) : round(2.8 * sr_ref), 1] = cue_wave
    # Cue 3 [3.8, 4.6]: Center
    binaural_stem[round(3.8 * sr_ref) : round(4.6 * sr_ref), 0] = cue_wave * 0.7
    binaural_stem[round(3.8 * sr_ref) : round(4.6 * sr_ref), 1] = cue_wave * 0.7

    stem_path = tmp_path / "vocals_48k_stereo.wav"
    sf.write(stem_path, binaural_stem, sr_ref, subtype="FLOAT")

    out_wav = tmp_path / "dubbed_binaural.wav"
    snapshot = service.snapshot(recipe["id"])
    segments = [
        {"text": "左边耳语。", "start_time": 0.2, "end_time": 1.0},
        {"text": "右边耳语。", "start_time": 2.0, "end_time": 2.8},
        {"text": "中间说话。", "start_time": 3.8, "end_time": 4.6},
    ]

    assembly = service.synthesize_timeline(
        snapshot,
        segments,
        out_wav,
        "binaural-task",
        reference_duration=6.0,
        binaural_source_path=stem_path,
    )

    info = sf.info(out_wav)
    assert info.channels == 2
    assert info.samplerate == 48000
    assert info.duration == pytest.approx(6.0, abs=0.01)

    pans = [item["pan"] for item in assembly["processing"]]
    assert pans[0] < -0.7
    assert pans[1] > 0.7
    assert abs(pans[2]) < 0.05

    rendered, rendered_sr = sf.read(out_wav, dtype="float32", always_2d=True)
    assert rendered_sr == 48000

    c1 = rendered[int(0.2 * rendered_sr) : int(0.8 * rendered_sr)]
    c2 = rendered[int(2.0 * rendered_sr) : int(2.6 * rendered_sr)]
    c3 = rendered[int(3.8 * rendered_sr) : int(4.4 * rendered_sr)]

    rms_c1_l, rms_c1_r = np.sqrt(np.mean(c1[:, 0] ** 2)), np.sqrt(np.mean(c1[:, 1] ** 2))
    rms_c2_l, rms_c2_r = np.sqrt(np.mean(c2[:, 0] ** 2)), np.sqrt(np.mean(c2[:, 1] ** 2))
    rms_c3_l, rms_c3_r = np.sqrt(np.mean(c3[:, 0] ** 2)), np.sqrt(np.mean(c3[:, 1] ** 2))

    assert rms_c1_l > rms_c1_r * 8.0
    assert rms_c2_r > rms_c2_l * 8.0
    assert rms_c3_l == pytest.approx(rms_c3_r, rel=0.05)


def test_speech_service_silence_slack_borrowing_and_capped_atempo(
    speech_env, tmp_path, monkeypatch
):
    service, recipe = speech_env

    # Synthesize 1.2s takes for each cue
    def fake_synthesize(request, path, context, cancel):
        req_copy = deepcopy(request)
        sf.write(path, _tone(1.2, sr=24000, freq=280.0, amp=0.15), 24000)
        return {"model": req_copy["model"]}

    monkeypatch.setattr(get_provider("edge"), "synthesize", fake_synthesize)

    ffmpeg_calls: list[list[str]] = []

    def fake_ffmpeg_stretch(cmd, **kwargs):
        ffmpeg_calls.append(list(cmd))
        # Parse atempo factor from "-af atempo=..." and write proportionally stretched WAV
        af_arg = cmd[cmd.index("-af") + 1]
        factor = 1.0
        for part in af_arg.split(","):
            factor *= float(part.split("=")[1])
        out_frames = max(1, round((1.2 / factor) * 24000))
        sf.write(cmd[-1], _tone(out_frames / 24000.0, sr=24000, amp=0.15), 24000)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_ffmpeg_stretch)
    monkeypatch.setattr("src.utils.get_ffmpeg", lambda: "ffmpeg")

    out_wav = tmp_path / "slack_borrowed.wav"
    snapshot = service.snapshot(recipe["id"])
    # Cue 1: [0.0, 0.6] (natural 0.6s), followed by Cue 2 at 2.5s -> 1.84s slack -> borrows 0.6s, NO atempo!
    # Cue 2: [2.5, 3.1] (natural 0.6s), followed by Cue 3 at 3.36s -> 0.20s slack -> effective 0.80s,
    #        required 1.2 / 0.8 = 1.50x > 1.35x -> over_speed=True, capped at 1.35x!
    # Cue 3: [3.36, 4.6] (natural 1.24s) -> fits naturally -> borrowed 0.0s, NO atempo!
    segments = [
        {"text": "借用静音不加速。", "start_time": 0.0, "end_time": 0.6},
        {"text": "间隙不足触发限速。", "start_time": 2.5, "end_time": 3.1},
        {"text": "自然放得下。", "start_time": 3.36, "end_time": 4.6},
    ]

    assembly = service.synthesize_timeline(
        snapshot,
        segments,
        out_wav,
        "slack-task",
        reference_duration=5.0,
        borrow_silence_slack=True,
        max_atempo=1.35,
    )

    # Only Cue 2 needed FFmpeg time-stretching!
    assert len(ffmpeg_calls) == 1
    proc0, proc1, proc2 = assembly["processing"]

    assert proc0["borrowed_seconds"] == pytest.approx(0.6)
    assert proc0["time_stretch"] == pytest.approx(1.0)
    assert proc0["operation"] == "resample_and_place"
    assert proc0["over_speed"] is False

    assert proc1["borrowed_seconds"] == pytest.approx(0.2)
    assert proc1["time_stretch"] == pytest.approx(1.35)
    assert proc1["operation"] == "atempo_resample_and_place"
    assert proc1["over_speed"] is True

    assert proc2["borrowed_seconds"] == pytest.approx(0.0)
    assert proc2["time_stretch"] == pytest.approx(1.0)
    assert proc2["over_speed"] is False

    # Re-assembling by experiment_id alone preserves persisted slack/max_atempo settings
    rebuilt = service.assemble(assembly["experiment_id"])
    assert rebuilt["processing"][0]["borrowed_seconds"] == pytest.approx(0.6)
    assert rebuilt["processing"][1]["over_speed"] is True
    assert rebuilt["processing"][1]["time_stretch"] == pytest.approx(1.35)
