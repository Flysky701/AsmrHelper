"""VoxCPM2 TTS provider wrapper.

VoxCPM2 is a 2B-parameter tokenizer-free diffusion autoregressive TTS model
by OpenBMB, supporting 30 languages, voice design, and controllable cloning.

HuggingFace: openbmb/VoxCPM2
Install:     pip install voxcpm
Requires:    PyTorch >= 2.5.0, CUDA >= 12.0, ~8GB VRAM
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any


class VoxCPM2Engine:
    """Adapter around the official voxcpm VoxCPM interface.

    Supports three synthesis modes:
    - Basic TTS: text only
    - Voice Design: text with description in parentheses, e.g. "(温柔女声)你好"
    - Voice Cloning: text + reference_wav_path (+ optional prompt_wav_path for ultimate cloning)
    """

    DEFAULT_CFG_VALUE = 2.0
    DEFAULT_INFERENCE_TIMESTEPS = 10
    DEFAULT_SAMPLE_RATE = 48000  # VoxCPM2 outputs 48kHz

    @classmethod
    def list_voices(cls) -> list[dict]:
        """VoxCPM2 uses voice design / cloning — no fixed voice list."""
        return [
            {"id": "default", "name": "默认 (文本驱动)", "language": "multilingual"},
            {"id": "voice_design", "name": "音色设计 (括号描述)", "language": "multilingual"},
            {"id": "voice_clone", "name": "音色克隆 (需参考音频)", "language": "multilingual"},
        ]

    def __init__(
        self,
        *,
        model_dir: str | None = None,
        cfg_value: float = DEFAULT_CFG_VALUE,
        inference_timesteps: int = DEFAULT_INFERENCE_TIMESTEPS,
        load_denoiser: bool = True,
        device_map: str = "auto",
        # Voice cloning params (set per-call, stored as defaults)
        reference_wav_path: str | None = None,
        prompt_wav_path: str | None = None,
        prompt_text: str | None = None,
    ) -> None:
        try:
            from voxcpm import VoxCPM
        except ImportError as exc:
            raise RuntimeError(
                "VoxCPM2 requires the optional 'voxcpm' dependency. "
                "Install it with `pip install voxcpm` (requires PyTorch >= 2.5.0, CUDA >= 12.0)."
            ) from exc

        self.cfg_value = float(cfg_value)
        self.inference_timesteps = int(inference_timesteps)
        self.default_reference_wav = reference_wav_path
        self.default_prompt_wav = prompt_wav_path
        self.default_prompt_text = prompt_text

        pretrained_id = model_dir or "openbmb/VoxCPM2"
        try:
            self.model = VoxCPM.from_pretrained(
                pretrained_id,
                load_denoiser=load_denoiser,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load VoxCPM2 from '{pretrained_id}': {exc}. "
                "Make sure the model is downloaded and CUDA is available."
            ) from exc

    def synthesize(self, text: str, output_path: str) -> str:
        """Synthesize text to audio file.

        Supports all three VoxCPM2 modes based on provider_options set at init:
        - Basic: no reference audio
        - Voice Design: text starts with (description)
        - Cloning: reference_wav_path is set
        """
        import soundfile as sf

        generate_kwargs: dict[str, Any] = {
            "text": text,
            "cfg_value": self.cfg_value,
            "inference_timesteps": self.inference_timesteps,
        }

        if self.default_reference_wav and Path(self.default_reference_wav).exists():
            generate_kwargs["reference_wav_path"] = self.default_reference_wav

        if self.default_prompt_wav and Path(self.default_prompt_wav).exists():
            generate_kwargs["prompt_wav_path"] = self.default_prompt_wav
            if self.default_prompt_text:
                generate_kwargs["prompt_text"] = self.default_prompt_text

        try:
            wav = self.model.generate(**generate_kwargs)
        except Exception as exc:
            raise RuntimeError(f"VoxCPM2 synthesis failed: {exc}") from exc

        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(target), wav, self.model.tts_model.sample_rate)
        return str(target)

    def synthesize_segments(
        self,
        segments: list[dict[str, Any]],
        output_dir: str,
        output_path: str,
        *,
        reference_duration: float = 0.0,
        sample_rate: int = 44100,
        max_tts_ratio: float = 1.2,
        compress_ratio: float = 0.75,
    ) -> None:
        """Synthesize multiple segments and concatenate into a single audio file.

        Each segment: {"index": str, "text": str, "start_time": float, "end_time": float}
        """
        import numpy as np
        import soundfile as sf

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        chunks: list[tuple[float, float, Any]] = []  # (start, end, wav_array)
        model_sr = self.model.tts_model.sample_rate

        for seg in segments:
            text = str(seg.get("text", "")).strip()
            if not text:
                continue

            start_time = float(seg.get("start_time", 0.0))
            end_time = float(seg.get("end_time", start_time + 5.0))

            generate_kwargs: dict[str, Any] = {
                "text": text,
                "cfg_value": self.cfg_value,
                "inference_timesteps": self.inference_timesteps,
            }
            if self.default_reference_wav and Path(self.default_reference_wav).exists():
                generate_kwargs["reference_wav_path"] = self.default_reference_wav
            if self.default_prompt_wav and Path(self.default_prompt_wav).exists():
                generate_kwargs["prompt_wav_path"] = self.default_prompt_wav
                if self.default_prompt_text:
                    generate_kwargs["prompt_text"] = self.default_prompt_text

            try:
                wav = self.model.generate(**generate_kwargs)
                chunks.append((start_time, end_time, np.asarray(wav, dtype="float32")))
            except Exception as exc:
                # Skip failed segments rather than aborting the whole run
                import logging
                logging.getLogger(__name__).warning(
                    "VoxCPM2 segment synthesis failed (text=%r): %s", text[:40], exc
                )

        if not chunks:
            raise RuntimeError("VoxCPM2 produced no audio chunks")

        # Build timeline-aligned output
        if reference_duration > 0:
            total_samples = int(reference_duration * model_sr)
        else:
            last_end = max(end for _, end, _ in chunks)
            total_samples = int(last_end * model_sr) + model_sr  # +1s padding

        output_audio = np.zeros(total_samples, dtype="float32")

        for start_time, end_time, wav_chunk in chunks:
            start_sample = int(start_time * model_sr)
            available_samples = total_samples - start_sample
            if available_samples <= 0:
                continue
            chunk_len = min(len(wav_chunk), available_samples)
            output_audio[start_sample: start_sample + chunk_len] = wav_chunk[:chunk_len]

        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(target), output_audio, model_sr)

    def unload(self) -> None:
        """Release model from memory."""
        if hasattr(self, "model"):
            del self.model
            self.model = None  # type: ignore[assignment]
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
