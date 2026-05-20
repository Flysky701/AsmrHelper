"""Core subtitle domain models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class SubtitleSegment:
    start: float
    end: float
    text: str
    language: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class SubtitleDocument:
    segments: list[SubtitleSegment] = field(default_factory=list)
    language: str = ""
    format: str = ""
    source_path: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def line_count(self) -> int:
        return len(self.segments)

    @property
    def duration_ms(self) -> float:
        if not self.segments:
            return 0.0
        return max(segment.end for segment in self.segments)


@dataclass(slots=True)
class SubtitleAsset:
    asset_id: str
    format: str
    document: SubtitleDocument = field(default_factory=SubtitleDocument)
    source_path: str = ""
    line_count: int = 0
    warnings: list[str] = field(default_factory=list)
    language: str = ""
    companion_of: str = ""
