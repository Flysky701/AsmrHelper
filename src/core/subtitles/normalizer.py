"""Subtitle normalization rules."""

from __future__ import annotations

from .models import SubtitleDocument, SubtitleSegment


class SubtitleNormalizer:
    """Normalize subtitle documents into stable domain structures."""

    def normalize_document(self, document: SubtitleDocument) -> SubtitleDocument:
        normalized_segments: list[SubtitleSegment] = []
        for segment in document.segments:
            text = self._normalize_text(segment.text)
            start = max(0.0, float(segment.start))
            end = max(start, float(segment.end))
            if not text:
                continue
            normalized_segments.append(
                SubtitleSegment(
                    start=start,
                    end=end,
                    text=text,
                    language=segment.language,
                    confidence=segment.confidence,
                )
            )
        return SubtitleDocument(
            segments=normalized_segments,
            language=document.language,
            format=document.format,
            source_path=document.source_path,
            warnings=list(document.warnings),
        )

    @staticmethod
    def _normalize_text(value: str) -> str:
        lines = [line.strip() for line in value.replace("\r\n", "\n").split("\n")]
        compacted = "\n".join(line for line in lines if line)
        return compacted.strip()
