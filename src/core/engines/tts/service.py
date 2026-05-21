"""Core TTS engine runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
        common_options = dict(profile.get("common_options", {}))
        provider_options = dict(profile.get("provider_options", {}))

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        engine = self._registry.get(
            engine_id,
            voice=str(common_options.get("voice", "")) or "zh-CN-XiaoxiaoNeural",
            speed=float(common_options.get("speed", 1.0)),
            voice_profile_id=provider_options.get("voice_profile_id"),
        )
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
        common_options = dict(profile.get("common_options", {}))
        provider_options = dict(profile.get("provider_options", {}))

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        engine = self._registry.get(
            engine_id,
            voice=str(common_options.get("voice", "")) or "zh-CN-XiaoxiaoNeural",
            speed=float(common_options.get("speed", 1.0)),
            voice_profile_id=provider_options.get("voice_profile_id"),
        )
        engine.synthesize_segments(
            segments,
            output_dir,
            output_path,
            reference_duration=reference_duration,
            sample_rate=sample_rate,
            max_tts_ratio=max_tts_ratio,
            compress_ratio=compress_ratio,
        )
        return output_path, engine
