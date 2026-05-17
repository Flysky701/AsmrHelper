"""Subtitle routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pathlib import Path

from src.api.http.dependencies import subtitle_service
from src.api.http.schemas.subtitles import (
    SubtitleDocumentModel,
    SubtitleExportRequest,
    SubtitleExportResponse,
    SubtitleLoadRequest,
    SubtitleLoadResponse,
    SubtitleSegmentModel,
)
from src.app.dto import SubtitleDocument, SubtitleSegment
from src.app.errors import AppExecutionError, AppValidationError
from src.app.services import SubtitleService

router = APIRouter(prefix="/subtitles", tags=["subtitles"])


def _document_from_app(document: SubtitleDocument) -> SubtitleDocumentModel:
    return SubtitleDocumentModel(
        segments=[
            SubtitleSegmentModel(start=segment.start, end=segment.end, text=segment.text)
            for segment in document.segments
        ]
    )


def _document_to_app(document: SubtitleDocumentModel) -> SubtitleDocument:
    return SubtitleDocument(
        segments=[
            SubtitleSegment(start=segment.start, end=segment.end, text=segment.text)
            for segment in document.segments
        ]
    )


@router.post("/load", response_model=SubtitleLoadResponse)
def load_subtitle(
    body: SubtitleLoadRequest,
    svc: SubtitleService = Depends(subtitle_service),
):
    try:
        content = Path(body.file_path).read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise AppValidationError(f"subtitle file not found: {body.file_path}") from exc
    except OSError as exc:
        raise AppExecutionError(f"failed to read subtitle file: {body.file_path}: {exc}") from exc
    doc = svc.load_srt_text(content)
    document = _document_from_app(doc)
    return SubtitleLoadResponse(document=document, segments=document.segments)


@router.post("/export", response_model=SubtitleExportResponse)
def export_subtitle(
    body: SubtitleExportRequest,
    svc: SubtitleService = Depends(subtitle_service),
):
    doc = _document_to_app(body.resolved_document())
    srt_text = svc.export_srt_text(doc)
    try:
        Path(body.output_path).write_text(srt_text, encoding="utf-8")
    except OSError as exc:
        raise AppExecutionError(
            f"failed to write subtitle file: {body.output_path}: {exc}"
        ) from exc
    return SubtitleExportResponse(
        output_path=body.output_path,
        segment_count=len(doc.segments),
    )
