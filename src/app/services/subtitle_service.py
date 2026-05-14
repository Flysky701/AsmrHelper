"""Subtitle conversion helpers for the application layer."""

from __future__ import annotations

import re
import threading

from ..dto import SubtitleDocument, SubtitleSegment


class SubtitleService:
    """Translate subtitle entry dicts into stable application DTOs."""

    _SRT_TIMING_LINE_PATTERN = re.compile(
        r"^\s*\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}\s*$"
    )
    _SRT_CUE_INDEX_PATTERN = re.compile(r"^\s*\d+\s*$")

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
        lines = normalized.split("\n")
        line_count = len(lines)
        index = 0

        while index < line_count:
            cue_start, timing_line_index = self._find_srt_timing_line(lines, index)
            if timing_line_index is None:
                index += 1
                continue

            next_cue_start = self._find_next_srt_cue_start(lines, timing_line_index + 1)
            timing_line = lines[timing_line_index]
            start_text, end_text = [part.strip() for part in timing_line.split("-->", maxsplit=1)]
            text = "\n".join(lines[timing_line_index + 1 : next_cue_start]).rstrip("\n")

            try:
                segments.append(
                    SubtitleSegment(
                        start=self._parse_srt_timestamp(start_text),
                        end=self._parse_srt_timestamp(end_text),
                        text=text,
                    )
                )
            except ValueError:
                pass

            index = next_cue_start

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

    def _find_srt_timing_line(
        self, lines: list[str], start_index: int
    ) -> tuple[int, int | None]:
        if self._is_srt_timing_line(lines[start_index]):
            return start_index, start_index
        if (
            start_index + 1 < len(lines)
            and self._is_srt_cue_index(lines[start_index])
            and self._contains_srt_separator(lines[start_index + 1])
        ):
            return start_index, start_index + 1
        return start_index, None

    def _find_next_srt_cue_start(self, lines: list[str], start_index: int) -> int:
        for index in range(start_index, len(lines)):
            cue_start, timing_line_index = self._find_srt_timing_line(lines, index)
            if timing_line_index is not None:
                return cue_start
        return len(lines)

    def _is_srt_timing_line(self, value: str) -> bool:
        return bool(self._SRT_TIMING_LINE_PATTERN.fullmatch(value))

    def _is_srt_cue_index(self, value: str) -> bool:
        return bool(self._SRT_CUE_INDEX_PATTERN.fullmatch(value))

    def _contains_srt_separator(self, value: str) -> bool:
        left, separator, right = value.partition("-->")
        return bool(separator and left.strip() and right.strip())


_service: SubtitleService | None = None
_lock = threading.Lock()


def get_subtitle_service() -> SubtitleService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = SubtitleService()
    return _service
