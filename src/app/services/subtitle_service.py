"""Subtitle conversion helpers for the application layer."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from ..dto import SubtitleAsset, SubtitleDocument, SubtitleSegment
from ..errors import AppExecutionError, AppValidationError


class SubtitleService:
    """Translate subtitle entry dicts into stable application DTOs."""

    _SRT_TIMING_LINE_PATTERN = re.compile(
        r"^\s*\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}\s*$"
    )
    _SRT_CUE_INDEX_PATTERN = re.compile(r"^\s*\d+\s*$")

    def __init__(self) -> None:
        self._assets: dict[str, SubtitleAsset] = {}
        self._asset_counter = 0
        self._lock = threading.Lock()

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

        return SubtitleDocument(segments=segments)

    def parse_text(self, content: str, fmt: str = "srt") -> SubtitleDocument:
        normalized_format = self._normalize_format(fmt)
        if normalized_format != "srt":
            raise AppValidationError(f"unsupported subtitle format: {fmt}")
        return self.load_srt_text(content)

    def load_asset(self, file_path: str) -> SubtitleAsset:
        path = Path(file_path)
        if not path.exists():
            raise AppValidationError(f"subtitle file not found: {file_path}")
        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise AppExecutionError(f"failed to read subtitle file: {file_path}: {exc}") from exc

        document = self.parse_text(content, path.suffix.lstrip(".") or "srt")
        return self.create_asset(
            document=document,
            fmt=path.suffix.lstrip(".") or "srt",
            source_path=str(path),
        )

    def create_asset(
        self,
        *,
        document: SubtitleDocument,
        fmt: str = "srt",
        source_path: str = "",
        warnings: list[str] | None = None,
    ) -> SubtitleAsset:
        normalized_document = self.normalize_document(document)
        with self._lock:
            self._asset_counter += 1
            asset_id = f"subtitle-{self._asset_counter}"
            asset = SubtitleAsset(
                asset_id=asset_id,
                format=self._normalize_format(fmt),
                document=normalized_document,
                source_path=source_path,
                line_count=len([seg for seg in normalized_document.segments if seg.text.strip()]),
                warnings=list(warnings or []),
            )
            self._assets[asset_id] = asset
        return self._clone_asset(asset)

    def get_asset(self, asset_id: str) -> SubtitleAsset:
        with self._lock:
            try:
                asset = self._assets[asset_id]
            except KeyError as exc:
                raise AppValidationError(f"unknown subtitle asset id: {asset_id}") from exc
        return self._clone_asset(asset)

    def normalize_document(self, document: SubtitleDocument) -> SubtitleDocument:
        normalized_segments: list[SubtitleSegment] = []
        for segment in document.segments:
            text = self._normalize_text(segment.text)
            start = max(0.0, float(segment.start))
            end = max(start, float(segment.end))
            if not text:
                continue
            normalized_segments.append(SubtitleSegment(start=start, end=end, text=text))
        return SubtitleDocument(segments=normalized_segments)

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

    def export_bilingual_srt_text(self, segments: list[dict]) -> str:
        blocks = []
        for i, seg in enumerate(segments, start=1):
            start = self._format_srt_timestamp(seg["start"])
            end = self._format_srt_timestamp(seg["end"])
            text = seg["text"]
            if seg.get("translation"):
                text = f"{text}\n{seg['translation']}"
            blocks.append(f"{i}\n{start} --> {end}\n{text}")
        if not blocks:
            return ""
        return "\n\n".join(blocks) + "\n"

    def export_bilingual_vtt_text(self, segments: list[dict]) -> str:
        lines = ["WEBVTT", ""]
        for seg in segments:
            start = self._format_vtt_timestamp(seg["start"])
            end = self._format_vtt_timestamp(seg["end"])
            lines.append(f"{start} --> {end}")
            lines.append(seg["text"])
            if seg.get("translation"):
                lines.append(seg["translation"])
            lines.append("")
        return "\n".join(lines)

    def export_bilingual_subtitle(
        self,
        segments: list[dict],
        output_path: str,
        bilingual: bool = True,
    ) -> str:
        ext = Path(output_path).suffix.lower()
        if not bilingual:
            doc = self.from_timestamp_entries(segments)
            return self.export_document(doc, output_path=output_path)

        if ext == ".vtt":
            content = self.export_bilingual_vtt_text(segments)
        else:
            content = self.export_bilingual_srt_text(segments)

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise AppExecutionError(f"failed to write subtitle file: {output_path}: {exc}") from exc
        return str(path)

    def export_document(
        self,
        document: SubtitleDocument,
        *,
        output_path: str,
        fmt: str | None = None,
    ) -> str:
        normalized_document = self.normalize_document(document)
        resolved_format = self._normalize_format(fmt or Path(output_path).suffix.lstrip(".") or "srt")
        if resolved_format != "srt":
            raise AppValidationError(f"unsupported subtitle format: {resolved_format}")

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            path.write_text(self.export_srt_text(normalized_document), encoding="utf-8")
        except OSError as exc:
            raise AppExecutionError(f"failed to write subtitle file: {output_path}: {exc}") from exc
        return str(path)

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

    @staticmethod
    def _format_vtt_timestamp(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = seconds % 60
        return f"{h:02d}:{m:02d}:{s:06.3f}"

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

    def _skip_srt_block(self, lines: list[str], start_index: int) -> int:
        index = start_index
        while index < len(lines) and lines[index].strip():
            index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        return index

    def _contains_srt_separator(self, value: str) -> bool:
        left, separator, right = value.partition("-->")
        return bool(separator and left.strip() and right.strip())

    def _normalize_text(self, value: str) -> str:
        lines = [line.strip() for line in value.replace("\r\n", "\n").split("\n")]
        compacted = "\n".join(line for line in lines if line)
        return compacted.strip()

    def _normalize_format(self, value: str) -> str:
        normalized = value.lower().strip().lstrip(".")
        return normalized or "srt"

    def _clone_asset(self, asset: SubtitleAsset) -> SubtitleAsset:
        return SubtitleAsset(
            asset_id=asset.asset_id,
            format=asset.format,
            document=SubtitleDocument(
                segments=[
                    SubtitleSegment(start=segment.start, end=segment.end, text=segment.text)
                    for segment in asset.document.segments
                ]
            ),
            source_path=asset.source_path,
            line_count=asset.line_count,
            warnings=list(asset.warnings),
        )


_service: SubtitleService | None = None
_lock = threading.Lock()


def get_subtitle_service() -> SubtitleService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = SubtitleService()
    return _service
