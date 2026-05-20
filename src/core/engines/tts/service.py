"""Core TTS engine runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class TtsEngineRuntime:
    """Execute TTS synthesis against the legacy engine implementation."""

    def synthesize_text(
        self,
        *,
        text: str,
        output_path: str,
        profile: dict[str, Any],
    ) -> str:
        from src.core.tts import TTSEngine

        engine_id = str(profile["provider"])
        common_options = dict(profile.get("common_options", {}))
        provider_options = dict(profile.get("provider_options", {}))

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        engine = TTSEngine(
            engine=engine_id,
            voice=str(common_options.get("voice", "")) or "zh-CN-XiaoxiaoNeural",
            speed=float(common_options.get("speed", 1.0)),
            voice_profile_id=provider_options.get("voice_profile_id"),
        )
        return engine.synthesize(text, output_path)
