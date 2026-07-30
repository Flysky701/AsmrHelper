"""Core TTS engine runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.resources.model_reference import resolve_model_reference

from .registry import get_tts_registry


class TtsEngineRuntime:
    """Execute TTS synthesis against the legacy engine implementation."""

    def __init__(self, registry=None) -> None:
        self._registry = registry or get_tts_registry()

    def synthesize_text(
        self,
        *,
        text: str,
        output_path: str,
        profile: dict[str, Any],
    ) -> str:
        engine_id = str(profile["provider"])

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        engine = self._registry.get(engine_id, **self._build_engine_kwargs(engine_id, profile))
        return engine.synthesize(text, output_path)

    def synthesize_segments(
        self,
        *,
        segments: list[dict[str, Any]],
        output_dir: str,
        output_path: str,
        profile: dict[str, Any],
        reference_duration: float = 0.0,
        sample_rate: int = 44100,
        max_tts_ratio: float = 1.2,
        compress_ratio: float = 0.75,
    ) -> tuple[str, Any]:
        engine_id = str(profile["provider"])

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        engine = self._registry.get(engine_id, **self._build_engine_kwargs(engine_id, profile))
        if hasattr(engine, "synthesize_segments"):
            engine.synthesize_segments(
                segments,
                output_dir,
                output_path,
                reference_duration=reference_duration,
                sample_rate=sample_rate,
                max_tts_ratio=max_tts_ratio,
                compress_ratio=compress_ratio,
            )
        elif hasattr(engine, "synthesize"):
            self._synthesize_generic_segments(
                engine=engine,
                segments=segments,
                output_dir=output_dir,
                output_path=output_path,
                reference_duration=reference_duration,
                sample_rate=sample_rate,
            )
        else:
            raise ValueError(f"TTS provider does not support synthesis: {engine_id}")
        return output_path, engine

    @staticmethod
    def _build_engine_kwargs(engine_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        common_options = dict(profile.get("common_options", {}))
        provider_options = dict(profile.get("provider_options", {}))

        voice = str(common_options.get("voice", "")).strip()
        speed = float(common_options.get("speed", 1.0))

        if engine_id == "edge":
            kwargs = {
                "voice": voice or "zh-CN-XiaoxiaoNeural",
                "rate": TtsEngineRuntime._edge_rate_from_speed(speed),
            }
            proxy = str(provider_options.get("proxy") or "").strip()
            if proxy:
                kwargs["proxy"] = proxy
            return kwargs

        if engine_id == "kokoro":
            return {
                "voice": voice or "af_heart",
                "speed": speed,
                "lang_code": provider_options.get("lang_code"),
                "repo_id": provider_options.get("repo_id"),
                "split_pattern": provider_options.get("split_pattern", r"\n+"),
                "sample_rate": int(provider_options.get("sample_rate", 24000)),
            }

        if engine_id == "voxcpm2":
            model_id = str(profile.get("model") or "voxcpm2")
            model_reference = resolve_model_reference(model_id)
            return {
                "model_dir": provider_options.get("model_dir") or model_reference,
                "cfg_value": float(provider_options.get("cfg_value", 2.0)),
                "inference_timesteps": int(provider_options.get("inference_timesteps", 10)),
                "load_denoiser": bool(provider_options.get("load_denoiser", True)),
                "device_map": str(provider_options.get("device_map", "auto")),
                "reference_wav_path": provider_options.get("reference_wav_path"),
                "prompt_wav_path": provider_options.get("prompt_wav_path"),
                "prompt_text": provider_options.get("prompt_text"),
            }

        kwargs = {
            "voice": voice or "zh-CN-XiaoxiaoNeural",
            "speed": speed,
            "voice_profile_id": provider_options.get("voice_profile_id"),
        }
        # Pass through all extra provider options (emotion, temperature, etc.)
        for key, value in provider_options.items():
            if key not in kwargs:
                kwargs[key] = value
        return kwargs

    @staticmethod
    def _synthesize_generic_segments(
        *,
        engine: Any,
        segments: list[dict[str, Any]],
        output_dir: str,
        output_path: str,
        reference_duration: float,
        sample_rate: int,
    ) -> None:
        """Adapt a text-to-audio provider to the pipeline timeline contract."""
        import numpy as np
        import soundfile as sf

        target_rate = max(int(sample_rate), 1)
        temp_dir = Path(output_dir) / "tts_temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        chunks: list[tuple[float, Any]] = []
        latest_end = 0.0

        for position, segment in enumerate(segments):
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            start_time = max(float(segment.get("start_time", 0.0)), 0.0)
            temp_path = temp_dir / f"generic_{position:04d}.wav"
            engine.synthesize(text, str(temp_path))
            audio, source_rate = sf.read(str(temp_path), dtype="float32")
            audio = np.asarray(audio, dtype="float32")
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if source_rate != target_rate and len(audio) > 0:
                target_length = max(round(len(audio) * target_rate / source_rate), 1)
                audio = np.interp(
                    np.linspace(0.0, 1.0, target_length, endpoint=False),
                    np.linspace(0.0, 1.0, len(audio), endpoint=False),
                    audio,
                ).astype("float32")
            chunks.append((start_time, audio))
            latest_end = max(latest_end, start_time + len(audio) / target_rate)

        if not chunks:
            raise RuntimeError("TTS provider produced no audio chunks")

        total_duration = max(float(reference_duration), latest_end)
        output_audio = np.zeros(max(round(total_duration * target_rate), 1), dtype="float32")
        for start_time, audio in chunks:
            start_sample = round(start_time * target_rate)
            end_sample = min(start_sample + len(audio), len(output_audio))
            if end_sample <= start_sample:
                continue
            output_audio[start_sample:end_sample] += audio[: end_sample - start_sample]

        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(target), np.clip(output_audio, -1.0, 1.0), target_rate)

    @staticmethod
    def _edge_rate_from_speed(speed: float) -> str:
        """Map the project-wide speed multiplier to edge-tts's signed percent."""
        if not 0.5 <= speed <= 2.0:
            raise ValueError("Edge TTS speed must be between 0.5 and 2.0")
        percent = round((speed - 1.0) * 100)
        return f"{percent:+d}%"
