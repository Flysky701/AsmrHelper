"""Subtitle conversion helpers for the application layer."""

from __future__ import annotations

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


_service: SubtitleService | None = None
_lock = threading.Lock()


def get_subtitle_service() -> SubtitleService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = SubtitleService()
    return _service
