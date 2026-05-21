"""Core ASR engine runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.subtitles import SubtitleDocument, SubtitleSegment

from .registry import get_asr_registry


class AsrEngineRuntime:
    """Execute ASR transcription against the legacy recognizer."""

    def __init__(self, registry=None) -> None:
        self._registry = registry or get_asr_registry()

    def transcribe_file(
        self,
        *,
        input_path: str,
        output_path: str | None,
        profile: dict[str, Any],
    ) -> SubtitleDocument:
        source_path = Path(input_path)
        if not source_path.exists():
            raise ValueError(f"input file does not exist: {input_path}")

        common_options = dict(profile.get("common_options", {}))
        provider_options = dict(profile.get("provider_options", {}))
        provider = str(profile.get("provider", "faster_whisper"))

        recognizer = self._registry.get(
            provider,
            model_size=str(profile.get("model", "")),
            language=str(common_options.get("language", "ja")),
            disable_vad=bool(provider_options.get("disable_vad", True)),
        )
        entries = recognizer.recognize(str(source_path), output_path)
        segments = [
            SubtitleSegment(
                start=float(entry.get("start", 0.0)),
                end=float(entry.get("end", 0.0)),
                text=str(entry.get("text", "")),
            )
            for entry in entries
        ]
        return SubtitleDocument(
            segments=segments,
            language=str(common_options.get("language", "ja")),
            format="srt" if output_path else "",
            source_path=output_path or "",
        )
