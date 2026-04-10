"""Subtitle preloading and timestamp entry strategy for pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from . import PipelineConfig


@dataclass
class SubtitleContext:
    subtitle_path: Optional[str]
    subtitle_type: str
    subtitle_translations: List[str]
    subtitle_lang: Optional[str]
    has_subtitle: bool
    is_chinese_subtitle: bool


class SubtitleStrategy:
    """Encapsulate subtitle loading, cleaning and timestamp retrieval."""

    def __init__(self, config: "PipelineConfig"):
        self.config = config

    def preload(self) -> SubtitleContext:
        from ..translate import clean_subtitle_batch, detect_subtitle_language, load_subtitle_translations

        subtitle_path = self.config.vtt_path
        subtitle_type = Path(subtitle_path).suffix.upper().lstrip(".") if subtitle_path else "VTT"

        if not subtitle_path or not Path(subtitle_path).exists():
            return SubtitleContext(
                subtitle_path=subtitle_path,
                subtitle_type=subtitle_type,
                subtitle_translations=[],
                subtitle_lang=None,
                has_subtitle=False,
                is_chinese_subtitle=False,
            )

        translations = load_subtitle_translations(subtitle_path)
        if not translations:
            return SubtitleContext(
                subtitle_path=subtitle_path,
                subtitle_type=subtitle_type,
                subtitle_translations=[],
                subtitle_lang=None,
                has_subtitle=False,
                is_chinese_subtitle=False,
            )

        if self.config.clean_subtitle:
            translations = clean_subtitle_batch(
                translations,
                clean_sound_effects=self.config.clean_sound_effects,
                clean_speaker_names=self.config.clean_speaker_names,
            )

        subtitle_lang = detect_subtitle_language(translations)
        return SubtitleContext(
            subtitle_path=subtitle_path,
            subtitle_type=subtitle_type,
            subtitle_translations=translations,
            subtitle_lang=subtitle_lang,
            has_subtitle=True,
            is_chinese_subtitle=(subtitle_lang == "zh"),
        )

    def load_entries(self, subtitle_path: str) -> List[Dict]:
        """Load subtitle entries with timestamps using current clean strategy."""
        from ..translate import load_and_clean_subtitle, load_subtitle_with_timestamps

        if self.config.clean_subtitle:
            return load_and_clean_subtitle(
                subtitle_path,
                clean_sound_effects=self.config.clean_sound_effects,
                clean_speaker_names=self.config.clean_speaker_names,
            )

        return load_subtitle_with_timestamps(subtitle_path)

    @staticmethod
    def to_segments(entries: List[Dict]) -> List[Dict]:
        """Normalize subtitle entries to pipeline segment shape."""
        return [{"start": e["start"], "end": e["end"], "text": e["text"]} for e in entries]
