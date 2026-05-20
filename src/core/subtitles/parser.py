"""Subtitle parsing helpers."""

from __future__ import annotations

import re

from .models import SubtitleDocument, SubtitleSegment


class SubtitleParser:
    """Parse raw subtitle text into domain documents."""

    _SRT_TIMING_LINE_PATTERN = re.compile(
        r"^\s*\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}\s*$"
    )
    _SRT_CUE_INDEX_PATTERN = re.compile(r"^\s*\d+\s*$")

    def parse_text(self, content: str, fmt: str = "srt") -> SubtitleDocument:
        normalized_format = self.normalize_format(fmt)
        if normalized_format != "srt":
            raise ValueError(f"unsupported subtitle format: {fmt}")
        document = self.load_srt_text(content)
        document.format = normalized_format
        return document

    def load_srt_text(self, content: str) -> SubtitleDocument:
        normalized = content.replace("\r\n", "\n").strip()
        if not normalized:
            return SubtitleDocument(format="srt")

        segments: list[SubtitleSegment] = []
        lines = normalized.split("\n")
        line_count = len(lines)
        index = 0

        while index < line_count:
            cue_start, timing_line_index = self._find_srt_timing_line(lines, index)
            if timing_line_index is None:
                if self._is_malformed_srt_cue_start(lines, index):
                    index = self._skip_srt_block(lines, index + 1)
                    continue
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

        return SubtitleDocument(segments=segments, format="srt")

    @staticmethod
    def normalize_format(value: str) -> str:
        normalized = value.lower().strip().lstrip(".")
        return normalized or "srt"

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

    def _find_srt_timing_line(
        self, lines: list[str], start_index: int
    ) -> tuple[int, int | None]:
        if self._is_srt_timing_line(lines[start_index]):
            return start_index, start_index
        if (
            start_index + 1 < len(lines)
            and self._is_srt_cue_index_at_block_start(lines, start_index)
            and self._is_srt_timing_line(lines[start_index + 1])
        ):
            return start_index, start_index + 1
        return start_index, None

    def _find_next_srt_cue_start(self, lines: list[str], start_index: int) -> int:
        for index in range(start_index, len(lines)):
            cue_start, timing_line_index = self._find_srt_timing_line(lines, index)
            if timing_line_index is not None:
                return cue_start
            if self._is_malformed_srt_cue_start(lines, index):
                return index
        return len(lines)

    def _is_srt_timing_line(self, value: str) -> bool:
        return bool(self._SRT_TIMING_LINE_PATTERN.fullmatch(value))

    def _is_srt_cue_index(self, value: str) -> bool:
        return bool(self._SRT_CUE_INDEX_PATTERN.fullmatch(value))

    def _is_srt_cue_index_at_block_start(self, lines: list[str], index: int) -> bool:
        return self._is_srt_cue_index(lines[index]) and (index == 0 or not lines[index - 1].strip())

    def _is_malformed_srt_cue_start(self, lines: list[str], start_index: int) -> bool:
        return (
            start_index + 1 < len(lines)
            and self._is_srt_cue_index_at_block_start(lines, start_index)
            and self._contains_srt_separator(lines[start_index + 1])
            and not self._is_srt_timing_line(lines[start_index + 1])
        )

    @staticmethod
    def _skip_srt_block(lines: list[str], start_index: int) -> int:
        index = start_index
        while index < len(lines) and lines[index].strip():
            index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        return index

    @staticmethod
    def _contains_srt_separator(value: str) -> bool:
        left, separator, right = value.partition("-->")
        return bool(separator and left.strip() and right.strip())
