"""Render and compare ASMR DSP variants using existing local audio assets.

Examples:
    python scripts/benchmark_asmr_remake.py original.wav timing.srt --tts dub.wav
    python scripts/benchmark_asmr_remake.py original.wav timing.srt \
        --takes cue1.wav cue2.wav --background no_vocals.wav --reference vocals.wav
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from itertools import pairwise
from math import gcd
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf
from scipy import signal

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.asr.acoustic_profiler import active_rms_db
from src.core.subtitles.parser import SubtitleParser
from src.mixer import Mixer
from src.mixer.acoustic_matching import process_cue, stretch_wsola
from src.mixer.binaural import plan_cue_slots
from src.mixer.multitrack import _load_audio, _write_audio
from src.mixer.room_tone import inpaint_room_tone
from src.utils import get_ffmpeg


VARIANTS = {
    "baseline": {},
    "spatial": {"binaural_mode": "dynamic_hrtf"},
    "level-eq": {"loudness_match": "per_cue", "eq_matching": True},
    "room": {"room_tone_inpaint": True, "reverb_match": True},
    "full": {
        "binaural_mode": "dynamic_hrtf",
        "loudness_match": "per_cue",
        "eq_matching": True,
        "room_tone_inpaint": True,
        "reverb_match": True,
        "borrow_silence_slack": True,
        "time_stretch_engine": "pytsmod_wsola",
    },
}


def _read_aligned(path: Path, sr: int) -> np.ndarray:
    audio, native_rate = _load_audio(path)
    if native_rate == sr:
        return audio
    divisor = gcd(native_rate, sr)
    return signal.resample_poly(audio, sr // divisor, native_rate // divisor, axis=0)


def _legacy_atempo(audio: np.ndarray, sr: int, ratio: float, directory: Path) -> np.ndarray:
    filters = []
    while ratio > 2:
        filters.append("atempo=2")
        ratio /= 2
    filters.append(f"atempo={ratio:.9f}")
    source = directory / "atempo-in.wav"
    target = directory / "atempo-out.wav"
    _write_audio(source, audio, sr)
    subprocess.run(
        [get_ffmpeg(), "-nostdin", "-v", "error", "-y", "-i", str(source), "-af",
         ",".join(filters), "-c:a", "pcm_f32le", str(target)],
        check=True,
        capture_output=True,
    )
    output, _ = sf.read(target, dtype="float32", always_2d=True)
    return output


def _metrics(original: np.ndarray, mixed: np.ndarray, sr: int) -> dict:
    reference_db = active_rms_db(original, sr)
    mixed_db = active_rms_db(mixed, sr)
    count = min(len(original), len(mixed))
    frequencies, reference_psd = signal.welch(
        original[:count], fs=sr, axis=0, nperseg=min(count, 2048)
    )
    _, mixed_psd = signal.welch(mixed[:count], fs=sr, axis=0, nperseg=min(count, 2048))
    band = (frequencies >= 80) & (frequencies <= min(12000, sr / 2))
    ref_power = reference_psd[band].mean(axis=1)
    mix_power = mixed_psd[band].mean(axis=1)
    distance = None
    if ref_power.size and ref_power.sum() > 0 and mix_power.sum() > 0:
        ref_db = 10 * np.log10(np.maximum(ref_power / ref_power.sum(), 1e-10))
        mix_db = 10 * np.log10(np.maximum(mix_power / mix_power.sum(), 1e-10))
        distance = float(np.sqrt(np.mean(np.square(ref_db - mix_db))))
    correlation = None
    if mixed.shape[1] == 2 and np.std(mixed[:, 0]) > 0 and np.std(mixed[:, 1]) > 0:
        correlation = float(np.corrcoef(mixed.T)[0, 1])
    return {
        "active_rms_dbfs": mixed_db,
        "loudness_difference_db": (
            mixed_db - reference_db if mixed_db is not None and reference_db is not None else None
        ),
        "spectral_distance_db": distance,
        "stereo_correlation": correlation,
    }


def _render_variant(
    name, options, *, directory, original, reference, background, sr, cues, takes, aligned_tts,
    max_atempo,
) -> dict:
    with tempfile.TemporaryDirectory(prefix=f".{name}-", dir=directory) as folder:
        work = Path(folder)
        output = directory / f"{name}.wav"
        speech_file = work / "speech.wav"
        frame_count = len(original)
        plans = []
        if aligned_tts is None:
            durations = [len(take) / sr for take in takes]
            if options.get("borrow_silence_slack"):
                plans = plan_cue_slots(cues, durations, reference_duration=frame_count / sr,
                                       max_atempo=max_atempo, cap_atempo=False)
            else:
                plans = [
                    {
                        "over_speed": duration / (cue["end"] - cue["start"]) > max_atempo,
                        "applied_atempo": max(1.0, duration / (cue["end"] - cue["start"])),
                        "effective_end_time": cue["end"],
                    }
                    for cue, duration in zip(cues, durations, strict=True)
                ]
        channels = 2 if options.get("binaural_mode") and reference.shape[1] == 2 else 1
        if aligned_tts is not None:
            channels = max(channels, aligned_tts.shape[1])
        speech = np.zeros((frame_count, channels), dtype=np.float32)
        for index, cue in enumerate(cues):
            start = round(cue["start"] * sr)
            end = round(cue["end"] * sr)
            if aligned_tts is None:
                audio = takes[index]
                tempo = plans[index]["applied_atempo"]
                if tempo > 1:
                    if options.get("time_stretch_engine") == "pytsmod_wsola":
                        audio = stretch_wsola(audio, sr, tempo)
                    else:
                        audio = _legacy_atempo(audio, sr, tempo, work)
                limit = min(frame_count, round(plans[index]["effective_end_time"] * sr))
                audio = audio[:limit - start]
            else:
                audio = aligned_tts[start:end]
            processed = process_cue(audio, sr, reference[start:end], sr, options)
            if processed.ndim == 1:
                processed = processed[:, None]
            speech[start : start + len(processed)] += processed
        _write_audio(speech_file, speech, sr)
        bed_file = work / "background.wav"
        bed = background
        if options.get("room_tone_inpaint"):
            bed = inpaint_room_tone(background, sr, original, sr, cues)
        _write_audio(bed_file, bed, sr)
        Mixer(original_volume=1.0, tts_volume_ratio=1.0).mix(
            str(bed_file), str(speech_file), str(output), adjust_tts_volume=False
        )
        rendered, rate = sf.read(output, dtype="float32", always_2d=True)
        return {
            "file": output.name,
            "options": options,
            "sample_rate": rate,
            "over_speed_cues": sum(plan["over_speed"] for plan in plans) if plans else None,
            **_metrics(original, rendered, rate),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("original", type=Path, help="Short source recording to compare against")
    parser.add_argument("subtitles", type=Path, help="SRT or VTT cue timings")
    tts = parser.add_mutually_exclusive_group(required=True)
    tts.add_argument("--tts", type=Path, help="Existing dry audio aligned to the subtitle timeline")
    tts.add_argument("--takes", type=Path, nargs="+", help="One dry audio file per cue in subtitle order")
    parser.add_argument("--reference", type=Path, help="Optional isolated vocals for cue matching")
    parser.add_argument("--background", type=Path, help="Optional separated no-vocals bed for pure replacement")
    parser.add_argument("--out-dir", type=Path, default=Path("output/asmr-benchmark"))
    parser.add_argument("--variants", nargs="+", choices=list(VARIANTS), default=list(VARIANTS))
    parser.add_argument("--max-atempo", type=float, default=1.35, help="Over-speed reporting threshold")
    args = parser.parse_args(argv)
    if not np.isfinite(args.max_atempo) or args.max_atempo < 1:
        parser.error("--max-atempo must be finite and at least 1")
    original, sr = _load_audio(args.original)
    reference = _read_aligned(args.reference, sr) if args.reference else original
    background = (
        _read_aligned(args.background, sr) if args.background else np.zeros_like(original)
    )
    duration = len(original) / sr
    background = background[:len(original)]
    if len(background) < len(original):
        background = np.pad(background, ((0, len(original) - len(background)), (0, 0)))
    segments = SubtitleParser().parse_text(
        args.subtitles.read_text(encoding="utf-8-sig"), args.subtitles.suffix
    ).segments
    if not segments or any(
        not 0 <= cue.start < cue.end <= duration + 0.0005 for cue in segments
    ) or any(left.start > right.start for left, right in pairwise(segments)):
        parser.error("provide ordered, positive cue timings inside the original audio")
    cues = [{"start": cue.start, "end": min(cue.end, duration)} for cue in segments]
    if any(round(cue["start"] * sr) >= round(cue["end"] * sr) for cue in cues):
        parser.error("each cue must span at least one source sample")
    takes = []
    aligned_tts = None
    if args.takes:
        if len(args.takes) != len(cues):
            parser.error("--takes requires one file per subtitle cue")
        takes = [_read_aligned(path, sr).mean(axis=1, keepdims=True) for path in args.takes]
    else:
        aligned_tts = _read_aligned(args.tts, sr)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    selected = list(dict.fromkeys(["baseline", *args.variants]))
    inputs = [args.original, args.reference, args.background, args.tts, *(args.takes or [])]
    if any(
        (args.out_dir / f"{name}.wav").resolve() == path.resolve()
        for name in selected for path in inputs if path is not None
    ):
        parser.error("output WAV files cannot overwrite any input")
    with ThreadPoolExecutor(max_workers=min(3, len(selected))) as pool:
        pending = {
            name: pool.submit(
                _render_variant, name, VARIANTS[name], directory=args.out_dir, original=original,
                reference=reference, background=background, sr=sr, cues=cues, takes=takes,
                aligned_tts=aligned_tts, max_atempo=args.max_atempo,
            )
            for name in selected
        }
        results = {name: job.result() for name, job in pending.items()}
    report = args.out_dir / "report.json"
    report.write_text(
        json.dumps({"variants": results, "over_speed_threshold": args.max_atempo},
                   indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
