"""Audio and transcript checks for optional TTS candidate selection."""

from __future__ import annotations

import os
from pathlib import Path
import unicodedata

import numpy as np
import soundfile as sf


def audio_issue(path: Path) -> str | None:
    """Return the reason to reject a silent, clipped or invalid waveform."""
    try:
        samples, rate = sf.read(str(path), dtype="float32", always_2d=True)
    except (OSError, RuntimeError):
        return "unreadable waveform"
    if not samples.size or not np.isfinite(samples).all():
        return "empty or invalid waveform"
    if np.mean(np.abs(samples) >= 0.999, axis=0).max() >= 0.005:
        return "clipping"

    # Measure in 50 ms frames so low-energy ASMR speech can still pass.
    frame = max(1, rate // 20)
    padded = np.pad(samples, ((0, -len(samples) % frame), (0, 0)))
    rms = np.sqrt(np.mean(padded.reshape(-1, frame, samples.shape[1]) ** 2, axis=(1, 2)))
    peak_rms = float(rms.max())
    active = np.flatnonzero(rms >= max(0.0003, peak_rms * 0.01))
    if peak_rms < 0.0003 or not active.size:
        return "silent waveform"
    silence_frames = np.diff(np.r_[-1, active, len(rms)]) - 1
    if silence_frames.max() >= 40 and (silence_frames.max() >= 60 or active.size < len(rms) * 0.4):
        return "long silence"
    return None


def _normalize(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKC", text).casefold() if ch.isalnum())


def transcript_similarity(expected: str, recognized: str) -> float:
    """Return 1 − character error rate, clipped to the unit interval."""
    expected, recognized = _normalize(expected), _normalize(recognized)
    if not expected:
        return float(not recognized)
    if abs(len(expected) - len(recognized)) >= len(expected):
        return 0.0
    previous = list(range(len(recognized) + 1))
    for row, wanted in enumerate(expected, 1):
        current = [row]
        for column, heard in enumerate(recognized, 1):
            current.append(min(previous[column] + 1, current[-1] + 1, previous[column - 1] + (wanted != heard)))
        previous = current
    return max(0.0, 1.0 - previous[-1] / len(expected))


def load_whisper():
    """Load a small CPU model without competing with the synthesis GPU lease."""
    from faster_whisper import WhisperModel

    model_root = os.environ.get("ASMR_HELPER_MODEL_ROOT")
    cache = Path(model_root) / "whisper" if model_root else None
    local_model = cache / "small" if cache else None
    model_name = str(local_model) if local_model and (local_model / "model.bin").is_file() else "small"
    return WhisperModel(model_name, device="cpu", compute_type="int8", download_root=str(cache) if cache else None)


def recognize(model, path: Path, language: str) -> str:
    language = language.strip().lower().replace("_", "-").split("-", 1)[0]
    language = {"chinese": "zh", "english": "en", "japanese": "ja", "korean": "ko", "mandarin": "zh"}.get(
        language, language
    )
    segments, _ = model.transcribe(
        str(path), language=language if len(language) == 2 else None, beam_size=1,
        vad_filter=False, condition_on_previous_text=False,
    )
    return "".join(segment.text for segment in segments)
