"""Optional audio-separator backend for two-stem vocal separation."""

from __future__ import annotations

from math import gcd
import os
from pathlib import Path
import re
import shutil
import tempfile
from threading import Lock
from typing import Any

import numpy as np
import soundfile as sf

from packages.protocol.errors import ComputeErrorCode, ComputeRemoteError


_MODEL_ALIASES = {
    "mel_band_roformer": "model_mel_band_roformer_ep_3005_sdr_11.4360.ckpt",
    "bs_roformer": "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
}
_MODEL_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:ckpt|onnx)", re.IGNORECASE)
_STEM_NAMES = {
    "Vocals": "vocals",
    "Instrumental": "no_vocals",
    "Other": "no_vocals",
    "No Vocals": "no_vocals",
}
_DENOISE_MODEL = "denoise_mel_band_roformer_aufr33_sdr_27.9959.ckpt"


def audio_separator_model(model: str) -> str | None:
    """Resolve an alias or a catalog filename without accepting a local path."""
    if model.lower() in _MODEL_ALIASES:
        return _MODEL_ALIASES[model.lower()]
    if Path(model).suffix.lower() in {".ckpt", ".onnx"}:
        if not _MODEL_FILENAME.fullmatch(model):
            raise ValueError("Separation model must be an audio-separator catalog filename")
        return model
    return None


class AudioSeparatorHandler:
    """A resident Separator with serialized access to its mutable inference state."""

    def __init__(self, model_filename: str) -> None:
        from audio_separator.separator import Separator

        model_cache = os.environ.get("AUDIO_SEPARATOR_MODEL_DIR")
        model_root = os.environ.get("ASMR_HELPER_MODEL_ROOT")
        if not model_cache and model_root:
            directory = Path(model_root) / "audio_separator"
            model_dirs = {**_MODEL_ALIASES, "denoise_mel_band_roformer": _DENOISE_MODEL}
            for name, filename in model_dirs.items():
                if filename == model_filename and (directory / name / filename).is_file():
                    directory = directory / name
                    break
            model_cache = str(directory)
        self._separator: Any = Separator(
            model_file_dir=model_cache or str(Path(tempfile.gettempdir()) / "audio-separator-models"),
            output_format="WAV",
            use_soundfile=True,
            normalization_threshold=1.0,
        )
        self._separator.load_model(model_filename=model_filename)
        self._stem_names = (
            {"Dry": "vocals", "Noise": "no_vocals", "No Dry": "no_vocals"}
            if model_filename == _DENOISE_MODEL else _STEM_NAMES
        )
        self._lock = Lock()

    def unload(self) -> None:
        self._separator = None

    def separate(
        self,
        source: Path,
        workspace: Path,
        output_dir: Path,
        prefix: str,
        requested_stems: list[str],
    ) -> dict[str, str]:
        if set(requested_stems) - {"vocals", "no_vocals"}:
            raise ValueError("audio-separator supports vocals and no_vocals output")
        source_info = sf.info(str(source))
        if source_info.channels not in (1, 2):
            raise ValueError("audio-separator requires mono or stereo input")
        workspace.mkdir(parents=True, exist_ok=True)
        workspace = workspace.resolve()
        with self._lock:
            self._separator.output_dir = str(workspace)
            self._separator.model_instance.output_dir = str(workspace)
            files = self._separator.separate(str(source.resolve()), custom_output_names=self._stem_names)

        staged: dict[str, Path] = {}
        for filename in files:
            path = (workspace / filename).resolve()
            if path.parent != workspace or not path.is_file():
                continue
            if path.stem in requested_stems:
                staged[path.stem] = path
        missing = set(requested_stems) - staged.keys()
        if missing:
            raise ComputeRemoteError(
                code=ComputeErrorCode.MODEL_NOT_AVAILABLE,
                message=f"Separation model did not provide the requested stems: {', '.join(sorted(missing))}",
                stage="separate",
            )

        published: dict[str, str] = {}
        for stem, path in staged.items():
            target = output_dir / f"{prefix}_{stem}.wav"
            stem_info = sf.info(str(path))
            if (stem_info.samplerate, stem_info.channels, stem_info.frames) == (
                source_info.samplerate, source_info.channels, source_info.frames,
            ):
                shutil.move(path, target)
                published[stem] = str(target)
                continue
            samples, rate = sf.read(str(path), dtype="float32", always_2d=True)
            if rate != source_info.samplerate:
                from scipy.signal import resample_poly

                divisor = gcd(rate, source_info.samplerate)
                samples = resample_poly(samples, source_info.samplerate // divisor, rate // divisor, axis=0)
            if source_info.channels == 1:
                samples = samples.mean(axis=1, keepdims=True)
            elif samples.shape[1] != source_info.channels:
                raise ValueError("Separation model did not produce stereo output for stereo input")
            samples = samples[:source_info.frames]
            if len(samples) < source_info.frames:
                samples = np.pad(samples, ((0, source_info.frames - len(samples)), (0, 0)))
            sf.write(str(target), samples, source_info.samplerate, subtype="FLOAT")
            published[stem] = str(target)
        return published
