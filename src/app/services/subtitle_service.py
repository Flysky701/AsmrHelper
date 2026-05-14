"""Subtitle conversion helpers for the application layer."""

from __future__ import annotations

import re
import threading

from ..dto import SubtitleDocument, SubtitleSegment


class SubtitleService:
    """Translate subtitle entry dicts into stable application DTOs."""

    def from_timestamp_entries(self, entries: list[dict]) -> SubtitleDocument:
        segments = [
            SubtitleSegment(
                start=float(entry.get("start", 0.0)),
                end=float(entry.get("end", 0.0)),
                text=str(entry.get("text", "")),
            )
            for entry in entries
        ]
        return SubtitleDocument(segments=segments)

    def to_timestamp_entries(self, document: SubtitleDocument) -> list[dict]:
        return [
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
            }
            for segment in document.segments
        ]

    def load_srt_text(self, content: str) -> SubtitleDocument:
        normalized = content.replace("\r\n", "\n").strip()
        if not normalized:
            return SubtitleDocument()

        segments: list[SubtitleSegment] = []
        for block in re.split(r"\n\s*\n", normalized):
            lines = [line for line in block.split("\n") if line.strip()]
            if len(lines) < 2:
                continue

            timing_line_index = 1 if "-->" not in lines[0] else 0
            if timing_line_index >= len(lines):
                continue

            timing_line = lines[timing_line_index]
            if "-->" not in timing_line:
                continue

            start_text, end_text = [part.strip() for part in timing_line.split("-->", maxsplit=1)]
            text = "\n".join(lines[timing_line_index + 1 :])
            segments.append(
                SubtitleSegment(
                    start=self._parse_srt_timestamp(start_text),
                    end=self._parse_srt_timestamp(end_text),
                    text=text,
                )
            )

        return SubtitleDocument(segments=segments)

    def export_srt_text(self, document: SubtitleDocument) -> str:
        blocks = []
        for index, segment in enumerate(document.segments, start=1):
            blocks.append(
                "\n".join(
                    [
                        str(index),
                        (
                            f"{self._format_srt_timestamp(segment.start)} --> "
                            f"{self._format_srt_timestamp(segment.end)}"
                        ),
                        segment.text,
                    ]
                )
            )

        if not blocks:
            return ""
        return "\n\n".join(blocks) + "\n"

    def _parse_srt_timestamp(self, value: str) -> float:
        hours_text, minutes_text, seconds_text = value.split(":")
        seconds, milliseconds = seconds_text.split(",")
        total_seconds = (
            int(hours_text) * 3600
            + int(minutes_text) * 60
            + int(seconds)
            + int(milliseconds) / 1000
        )
        return float(total_seconds)

    def _format_srt_timestamp(self, value: float) -> str:
        total_milliseconds = int(round(value * 1000))
        hours, remainder = divmod(total_milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


_service: SubtitleService | None = None
_lock = threading.Lock()


def get_subtitle_service() -> SubtitleService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = SubtitleService()
    return _service
