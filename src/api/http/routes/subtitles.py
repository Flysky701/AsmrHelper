"""Subtitle routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from src.api.http.dependencies import artifact_service, script_subtitle_service, subtitle_service
from src.api.http.schemas.subtitles import (
    ScriptToSubtitleRequest,
    ScriptToSubtitleResponse,
    SubtitleBilingualizeRequest,
    SubtitleBilingualizeResponse,
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
    SubtitleTranslateRequest,
    SubtitleTranslateResponse,
)
from src.api.http.schemas.tasks import TaskStatusResponse
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


@router.post("/translate", response_model=SubtitleTranslateResponse)
def translate_subtitle(
    body: SubtitleTranslateRequest,
    svc: SubtitleService = Depends(subtitle_service),
    artifact_svc: ArtifactService = Depends(artifact_service),
):
    result = svc.translate_subtitle(
        input_path=body.input_path,
        output_path=body.output_path or "",
        provider=body.provider,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
        bilingual=body.bilingual,
    )
    if body.task_id and result.output_path:
        artifact_svc.register_artifact(
            task_id=body.task_id,
            artifact_type=f"subtitle.{Path(result.output_path).suffix.lstrip('.') or 'srt'}",
            path=result.output_path,
            label="Translated Subtitle",
            preview_kind="subtitle",
            stage="translate_subtitle",
            is_primary=True,
            metadata={"segment_count": result.total_segments, "provider": result.provider},
        )
    return SubtitleTranslateResponse(
        output_path=result.output_path,
        total_segments=result.total_segments,
        provider=result.provider,
        source_lang=result.source_lang,
        target_lang=result.target_lang,
        task_id=body.task_id,
    )


@router.post("/bilingualize", response_model=SubtitleBilingualizeResponse)
def bilingualize_subtitle(
    body: SubtitleBilingualizeRequest,
    svc: SubtitleService = Depends(subtitle_service),
    artifact_svc: ArtifactService = Depends(artifact_service),
):
    segments = [
        {
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "translation": segment.translation,
        }
        for segment in body.segments
    ]
    output_path = svc.bilingualize_segments(
        segments=segments,
        output_path=body.output_path,
    )
    if body.task_id:
        artifact_svc.register_artifact(
            task_id=body.task_id,
            artifact_type=f"subtitle.{Path(output_path).suffix.lstrip('.') or 'srt'}",
            path=output_path,
            label="Bilingual Subtitle",
            preview_kind="subtitle",
            stage="subtitle_bilingualize",
            is_primary=True,
            metadata={"segment_count": len(body.segments)},
        )
    return SubtitleBilingualizeResponse(
        output_path=output_path,
        segment_count=len(body.segments),
        task_id=body.task_id,
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
        artifact_format = Path(output_path).suffix.lstrip(".").lower() or "srt"
        artifact_svc.register_artifact(
            task_id=body.task_id,
            artifact_type=f"subtitle.{artifact_format}",
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


@router.post("/script-to-subtitle", response_model=ScriptToSubtitleResponse)
def script_to_subtitle(
    body: ScriptToSubtitleRequest,
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

    return ScriptToSubtitleResponse(
        mode=result.mode,
        output_path=result.output_path,
        text=result.text,
        line_count=result.line_count,
        task_id=body.task_id,
    )


@router.post("/script-to-subtitle/tasks", response_model=TaskStatusResponse, status_code=201)
def create_script_to_subtitle_task(
    body: ScriptToSubtitleRequest,
    svc: ScriptSubtitleService = Depends(script_subtitle_service),
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
    return TaskStatusResponse.from_task_status(svc.create_task(request))
