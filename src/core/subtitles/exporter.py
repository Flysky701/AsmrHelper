"""Subtitle export helpers."""

from __future__ import annotations

from pathlib import Path

from .models import SubtitleDocument
from .normalizer import SubtitleNormalizer
from .parser import SubtitleParser


class SubtitleExporter:
    """Export subtitle documents to text and files."""

    def __init__(self, *, normalizer: SubtitleNormalizer | None = None) -> None:
        self._normalizer = normalizer or SubtitleNormalizer()

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

    def export_vtt_text(self, document: SubtitleDocument) -> str:
        lines = ["WEBVTT", ""]
        for segment in document.segments:
            lines.extend(
                [
                    (
                        f"{self._format_vtt_timestamp(segment.start)} --> "
                        f"{self._format_vtt_timestamp(segment.end)}"
                    ),
                    segment.text,
                    "",
                ]
            )
        return "\n".join(lines)

    def export_lrc_text(self, document: SubtitleDocument) -> str:
        lines = []
        for segment in document.segments:
            text = " / ".join(
                line.strip() for line in segment.text.replace("\r\n", "\n").split("\n") if line.strip()
            )
            if text:
                lines.append(f"{self._format_lrc_timestamp(segment.start)}{text}")
        return "\n".join(lines) + ("\n" if lines else "")

    def export_bilingual_srt_text(self, segments: list[dict]) -> str:
        blocks = []
        for index, segment in enumerate(segments, start=1):
            start = self._format_srt_timestamp(segment["start"])
            end = self._format_srt_timestamp(segment["end"])
            text = segment["text"]
            if segment.get("translation"):
                text = f"{text}\n{segment['translation']}"
            blocks.append(f"{index}\n{start} --> {end}\n{text}")
        if not blocks:
            return ""
        return "\n\n".join(blocks) + "\n"

    def export_bilingual_vtt_text(self, segments: list[dict]) -> str:
        lines = ["WEBVTT", ""]
        for segment in segments:
            start = self._format_vtt_timestamp(segment["start"])
            end = self._format_vtt_timestamp(segment["end"])
            lines.append(f"{start} --> {end}")
            lines.append(segment["text"])
            if segment.get("translation"):
                lines.append(segment["translation"])
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
            document = SubtitleDocument(
                segments=[],
            )
            document.segments = [
                self._segment_from_timestamp_entry(segment) for segment in segments
            ]
            return self.export_document(document, output_path=output_path)

        if ext not in {".srt", ".vtt", ".lrc"}:
            raise ValueError(f"unsupported subtitle format: {ext.lstrip('.') or '(missing)'}")
        if ext == ".vtt":
            content = self.export_bilingual_vtt_text(segments)
        elif ext == ".lrc":
            document = SubtitleDocument(
                segments=[
                    self._segment_from_timestamp_entry(
                        {
                            **segment,
                            "text": (
                                f"{segment['text']}\n{segment['translation']}"
                                if segment.get("translation")
                                else segment["text"]
                            ),
                        }
                    )
                    for segment in segments
                ]
            )
            content = self.export_lrc_text(document)
        else:  # .srt
            content = self.export_bilingual_srt_text(segments)

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)

    def export_document(
        self,
        document: SubtitleDocument,
        *,
        output_path: str,
        fmt: str | None = None,
    ) -> str:
        normalized_document = self._normalizer.normalize_document(document)
        resolved_format = SubtitleParser.normalize_format(
            fmt or Path(output_path).suffix.lstrip(".") or normalized_document.format or "srt"
        )
        exporters = {
            "srt": self.export_srt_text,
            "vtt": self.export_vtt_text,
            "lrc": self.export_lrc_text,
        }
        try:
            exporter = exporters[resolved_format]
        except KeyError as exc:
            raise ValueError(f"unsupported subtitle format: {resolved_format}") from exc

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(exporter(normalized_document), encoding="utf-8")
        return str(path)

    @staticmethod
    def _segment_from_timestamp_entry(entry: dict):
        from .models import SubtitleSegment

        return SubtitleSegment(
            start=float(entry.get("start", 0.0)),
            end=float(entry.get("end", 0.0)),
            text=str(entry.get("text", "")),
        )

    @staticmethod
    def _format_srt_timestamp(value: float) -> str:
        total_milliseconds = int(round(value * 1000))
        hours, remainder = divmod(total_milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, milliseconds = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    @staticmethod
    def _format_vtt_timestamp(seconds: float) -> str:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        remainder = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{remainder:06.3f}"

    @staticmethod
    def _format_lrc_timestamp(seconds: float) -> str:
        total_centiseconds = max(0, int(round(seconds * 100)))
        minutes, remainder = divmod(total_centiseconds, 6000)
        whole_seconds, centiseconds = divmod(remainder, 100)
        return f"[{minutes:02d}:{whole_seconds:02d}.{centiseconds:02d}]"
