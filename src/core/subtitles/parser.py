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
    _VTT_TIMING_LINE_PATTERN = re.compile(
        r"^\s*(?P<start>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})\s*-->\s*"
        r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}\.\d{3})(?:\s+.*)?$"
    )
    _LRC_TIMESTAMP_PATTERN = re.compile(
        r"\[(?P<minutes>\d{1,3}):(?P<seconds>\d{1,2})(?:[.:](?P<fraction>\d{1,3}))?\]"
    )

    def parse_text(self, content: str, fmt: str = "srt") -> SubtitleDocument:
        normalized_format = self.normalize_format(fmt)
        loaders = {
            "srt": self.load_srt_text,
            "vtt": self.load_vtt_text,
            "lrc": self.load_lrc_text,
        }
        try:
            loader = loaders[normalized_format]
        except KeyError as exc:
            raise ValueError(f"unsupported subtitle format: {fmt}") from exc
        document = loader(content)
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

    def load_vtt_text(self, content: str) -> SubtitleDocument:
        normalized = content.replace("\ufeff", "", 1).replace("\r\n", "\n").strip()
        if not normalized:
            return SubtitleDocument(format="vtt")

        lines = normalized.split("\n")
        segments: list[SubtitleSegment] = []
        index = 1 if lines[0].strip().upper().startswith("WEBVTT") else 0

        while index < len(lines):
            if not lines[index].strip():
                index += 1
                continue

            block_start = index
            while index < len(lines) and lines[index].strip():
                index += 1
            block = lines[block_start:index]
            block_kind = block[0].lstrip().split(maxsplit=1)[0].upper() if block else ""
            if not block or block_kind in {"NOTE", "STYLE", "REGION"}:
                continue

            timing_index = next(
                (
                    current
                    for current, line in enumerate(block[:2])
                    if self._VTT_TIMING_LINE_PATTERN.fullmatch(line)
                ),
                None,
            )
            if timing_index is None:
                continue

            match = self._VTT_TIMING_LINE_PATTERN.fullmatch(block[timing_index])
            if match is None:
                continue
            text = "\n".join(block[timing_index + 1 :]).strip()
            if not text:
                continue
            try:
                segments.append(
                    SubtitleSegment(
                        start=self._parse_vtt_timestamp(match.group("start")),
                        end=self._parse_vtt_timestamp(match.group("end")),
                        text=text,
                    )
                )
            except ValueError:
                continue

        return SubtitleDocument(segments=segments, format="vtt")

    def load_lrc_text(self, content: str) -> SubtitleDocument:
        normalized = content.replace("\ufeff", "", 1).replace("\r\n", "\n")
        pending: list[tuple[float, int, str]] = []
        sequence = 0

        for line in normalized.split("\n"):
            matches = list(self._LRC_TIMESTAMP_PATTERN.finditer(line))
            if not matches:
                continue
            text = line[matches[-1].end() :].strip()
            if not text:
                continue
            for match in matches:
                minutes = int(match.group("minutes"))
                seconds = int(match.group("seconds"))
                if seconds >= 60:
                    continue
                fraction_text = match.group("fraction") or "0"
                fraction = int(fraction_text) / (10 ** len(fraction_text))
                pending.append((minutes * 60 + seconds + fraction, sequence, text))
                sequence += 1

        pending.sort(key=lambda item: (item[0], item[1]))
        segments: list[SubtitleSegment] = []
        for current, (start, _sequence, text) in enumerate(pending):
            next_start = pending[current + 1][0] if current + 1 < len(pending) else start + 3.0
            end = next_start if next_start > start else start + 3.0
            segments.append(SubtitleSegment(start=start, end=end, text=text))
        return SubtitleDocument(segments=segments, format="lrc")

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

    @staticmethod
    def _parse_vtt_timestamp(value: str) -> float:
        fields = value.split(":")
        if len(fields) == 2:
            hours = 0
            minutes_text, seconds_text = fields
        elif len(fields) == 3:
            hours_text, minutes_text, seconds_text = fields
            hours = int(hours_text)
        else:
            raise ValueError(f"invalid WebVTT timestamp: {value}")
        seconds, milliseconds = seconds_text.split(".")
        return float(
            hours * 3600
            + int(minutes_text) * 60
            + int(seconds)
            + int(milliseconds) / 1000
        )

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
