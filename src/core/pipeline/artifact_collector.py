"""
Legacy pipeline artifact handling.

This module remains in the legacy pipeline package for compatibility, but
subtitle export now delegates to the newer subtitle domain service so the
formatting rules live in one place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from ..subtitles import SubtitleDomainService


class ArtifactCollector:
    def __init__(self, config):
        self.config = config
        self.progress_callback = None
        self._subtitle_service = SubtitleDomainService()

    def _report(self, msg: str):
        if self.progress_callback:
            self.progress_callback(msg)

    def write_subtitles(
        self,
        active_steps: List[str],
        timestamped_segments: List[Dict],
        translations: List[str],
        by_product_dir: Path,
        task_name: str,
        subtitle_lang: str,
    ):
        """Export subtitle files for legacy pipeline runs."""
        if "translate" not in active_steps and self.config.pipeline_mode != "full":
            return None

        if not timestamped_segments:
            return None

        fmt = self.config.export_subtitle_format
        base_name = f"{task_name}_subtitle"
        path = by_product_dir / f"{base_name}.{fmt}"

        if fmt == "lrc":
            path.write_text(self._build_lrc(timestamped_segments), encoding="utf-8")
        elif fmt in {"srt", "vtt"}:
            self._subtitle_service.export_bilingual_subtitle(
                timestamped_segments,
                str(path),
                bilingual=True,
            )
        else:
            return None

        self._report(f"  [字幕] 导出 {path.name}")
        return str(path)

    def _build_lrc(self, segments: List[Dict]) -> str:
        lines = []
        for seg in segments:
            start_ms = int(seg["start"] * 1000)
            minutes = start_ms // 60000
            seconds = (start_ms % 60000) // 1000
            centiseconds = (start_ms % 1000) // 10
            ts = f"[{minutes:02d}:{seconds:02d}.{centiseconds:02d}]"

            text = seg.get("text", "")
            translation = seg.get("translation", "")

            if text and translation:
                lines.append(f"{ts}{text}")
                lines.append(f"{ts}{translation}")
            elif text or translation:
                lines.append(f"{ts}{text or translation}")

        return "\n".join(lines)

    def collect(self, results: Dict, input_path: Path, mix_path: Path, by_product_dir: Path):
        """Compatibility placeholder for final artifact cleanup/gathering."""
        return None
