"""Subtitle routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import artifact_service, script_subtitle_service, subtitle_service
from src.api.http.schemas.subtitles import (
    ScriptToVttRequest,
    ScriptToVttResponse,
    SubtitleDocumentModel,
    SubtitleExportRequest,
    SubtitleExportResponse,
    SubtitleLoadRequest,
    SubtitleLoadResponse,
    SubtitleNormalizeRequest,
    SubtitleNormalizeResponse,
    SubtitleParseRequest,
    SubtitleParseResponse,
    SubtitleSegmentModel,
)
from src.app.dto import SubtitleDocument, SubtitleSegment
from src.app.dto.script_subtitle import ScriptSubtitleRequest
from src.app.services import ArtifactService, ScriptSubtitleService, SubtitleService

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
    asset = svc.load_asset(body.file_path)
    document = _document_from_app(asset.document)
    return SubtitleLoadResponse(document=document, segments=document.segments)


@router.post("/parse", response_model=SubtitleParseResponse)
def parse_subtitle(
    body: SubtitleParseRequest,
    svc: SubtitleService = Depends(subtitle_service),
):
    document = svc.parse_text(body.content, body.fmt)
    normalized = svc.normalize_document(document)
    response_document = _document_from_app(normalized)
    return SubtitleParseResponse(
        document=response_document,
        segment_count=len(response_document.segments),
    )


@router.post("/normalize", response_model=SubtitleNormalizeResponse)
def normalize_subtitle(
    body: SubtitleNormalizeRequest,
    svc: SubtitleService = Depends(subtitle_service),
):
    doc = _document_to_app(body.resolved_document())
    normalized = svc.normalize_document(doc)
    response_document = _document_from_app(normalized)
    return SubtitleNormalizeResponse(
        document=response_document,
        segment_count=len(response_document.segments),
    )


@router.post("/export", response_model=SubtitleExportResponse)
def export_subtitle(
    body: SubtitleExportRequest,
    svc: SubtitleService = Depends(subtitle_service),
    artifact_svc: ArtifactService = Depends(artifact_service),
):
    doc = _document_to_app(body.resolved_document())
    output_path = svc.export_document(doc, output_path=body.output_path)
    if body.task_id:
        artifact_svc.register_artifact(
            task_id=body.task_id,
            artifact_type="subtitle.srt",
            path=output_path,
            label="Exported Subtitle",
            preview_kind="subtitle",
            stage="subtitle_export",
            is_primary=True,
            metadata={"segment_count": len(doc.segments)},
        )
    return SubtitleExportResponse(
        output_path=output_path,
        segment_count=len(doc.segments),
        task_id=body.task_id,
    )


@router.post("/script-to-vtt", response_model=ScriptToVttResponse)
def script_to_vtt(
    body: ScriptToVttRequest,
    svc: ScriptSubtitleService = Depends(script_subtitle_service),
    artifact_svc: ArtifactService = Depends(artifact_service),
):
    request = ScriptSubtitleRequest(
        script_path=body.script_path,
        output_path=body.output_path,
        audio_path=body.audio_path,
        vtt_path=body.vtt_path,
        fmt=body.fmt,
        use_llm_clean=body.use_llm_clean,
        asr_model_size=body.asr_model_size,
        asr_language=body.asr_language,
        track_index=body.track_index,
        vertical_mode=body.vertical_mode,
        debug_dir=body.debug_dir,
    )

    if body.vtt_path:
        result = svc.run_from_existing_vtt(request)
    elif body.audio_path:
        result = svc.run_full(request)
    else:
        result = svc.run_text_only(request)

    if body.task_id and result.output_path:
        artifact_type = f"subtitle.{body.fmt}"
        artifact_svc.register_artifact(
            task_id=body.task_id,
            artifact_type=artifact_type,
            path=result.output_path,
            label="Script Subtitle Output",
            preview_kind="subtitle",
            stage="script_to_subtitle",
            is_primary=True,
            metadata={"mode": result.mode, "line_count": result.line_count},
        )

    return ScriptToVttResponse(
        mode=result.mode,
        output_path=result.output_path,
        text=result.text,
        line_count=result.line_count,
        task_id=body.task_id,
    )
