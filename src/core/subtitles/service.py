"""Core subtitle domain service."""

from __future__ import annotations

import threading
from pathlib import Path

from .exporter import SubtitleExporter
from .models import SubtitleAsset, SubtitleDocument, SubtitleSegment
from .normalizer import SubtitleNormalizer
from .parser import SubtitleParser


class SubtitleDomainService:
    """Manage subtitle parsing, normalization, export, and asset storage."""

    def __init__(
        self,
        *,
        parser: SubtitleParser | None = None,
        normalizer: SubtitleNormalizer | None = None,
        exporter: SubtitleExporter | None = None,
    ) -> None:
        self._parser = parser or SubtitleParser()
        self._normalizer = normalizer or SubtitleNormalizer()
        self._exporter = exporter or SubtitleExporter(normalizer=self._normalizer)
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
            {"start": segment.start, "end": segment.end, "text": segment.text}
            for segment in document.segments
        ]

    def parse_text(self, content: str, fmt: str = "srt") -> SubtitleDocument:
        return self._parser.parse_text(content, fmt)

    def load_asset(self, file_path: str) -> SubtitleAsset:
        path = Path(file_path)
        if not path.exists():
            raise ValueError(f"subtitle file not found: {file_path}")
        content = path.read_text(encoding="utf-8")
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
        normalized_document.format = self._parser.normalize_format(fmt)
        normalized_document.source_path = source_path or normalized_document.source_path
        with self._lock:
            self._asset_counter += 1
            asset_id = f"subtitle-{self._asset_counter}"
            asset = SubtitleAsset(
                asset_id=asset_id,
                format=normalized_document.format,
                document=normalized_document,
                source_path=source_path,
                line_count=len(
                    [segment for segment in normalized_document.segments if segment.text.strip()]
                ),
                warnings=list(warnings or normalized_document.warnings),
                language=normalized_document.language,
            )
            self._assets[asset_id] = asset
        return self._clone_asset(asset)

    def get_asset(self, asset_id: str) -> SubtitleAsset:
        with self._lock:
            try:
                asset = self._assets[asset_id]
            except KeyError as exc:
                raise ValueError(f"unknown subtitle asset id: {asset_id}") from exc
        return self._clone_asset(asset)

    def normalize_document(self, document: SubtitleDocument) -> SubtitleDocument:
        return self._normalizer.normalize_document(document)

    def export_srt_text(self, document: SubtitleDocument) -> str:
        return self._exporter.export_srt_text(document)

    def export_bilingual_srt_text(self, segments: list[dict]) -> str:
        return self._exporter.export_bilingual_srt_text(segments)

    def export_bilingual_vtt_text(self, segments: list[dict]) -> str:
        return self._exporter.export_bilingual_vtt_text(segments)

    def export_bilingual_subtitle(
        self,
        segments: list[dict],
        output_path: str,
        bilingual: bool = True,
    ) -> str:
        return self._exporter.export_bilingual_subtitle(
            segments=segments,
            output_path=output_path,
            bilingual=bilingual,
        )

    def export_document(
        self,
        document: SubtitleDocument,
        *,
        output_path: str,
        fmt: str | None = None,
    ) -> str:
        return self._exporter.export_document(document, output_path=output_path, fmt=fmt)

    def _clone_asset(self, asset: SubtitleAsset) -> SubtitleAsset:
        return SubtitleAsset(
            asset_id=asset.asset_id,
            format=asset.format,
            document=SubtitleDocument(
                segments=[
                    SubtitleSegment(
                        start=segment.start,
                        end=segment.end,
                        text=segment.text,
                        language=segment.language,
                        confidence=segment.confidence,
                    )
                    for segment in asset.document.segments
                ],
                language=asset.document.language,
                format=asset.document.format,
                source_path=asset.document.source_path,
                warnings=list(asset.document.warnings),
            ),
            source_path=asset.source_path,
            line_count=asset.line_count,
            warnings=list(asset.warnings),
            language=asset.language,
            companion_of=asset.companion_of,
        )
