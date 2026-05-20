"""Audio tool routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import audio_tool_service
from src.api.http.schemas.tools import (
    ConvertRequest,
    ConvertResponse,
    SeparationRequest,
    SeparationResponse,
    SplitRequest,
    SplitResponse,
    SplitSegmentResponse,
    SubtitleTranslationRequest,
    SubtitleTranslationResponse,
    VolumePreviewRequest,
    VolumePreviewResponse,
)
from src.app.services import AudioToolService

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/separate", response_model=SeparationResponse)
def separate_vocals(
    body: SeparationRequest,
    svc: AudioToolService = Depends(audio_tool_service),
):
    task_spec = svc.create_tool_task_spec(
        task_type="tool.separate",
        input_path=body.input_path,
        execution_profile={
            "output_dir": body.output_dir,
            "model": body.model,
            "stems": body.stems,
        },
    )
    execution = svc.run_tool_task(task_spec.task_id)
    summary = execution["summary"]
    return SeparationResponse(
        input_path=body.input_path,
        stems=summary.get("stems", {}),
        primary_output=summary.get("primary_output"),
    )


@router.post("/convert", response_model=ConvertResponse)
def convert_audio(
    body: ConvertRequest,
    svc: AudioToolService = Depends(audio_tool_service),
):
    task_spec = svc.create_tool_task_spec(
        task_type="tool.convert",
        input_path=body.input_path,
        execution_profile={
            "output_path": body.output_path,
            "target_format": body.target_format,
            "sample_rate": body.sample_rate,
            "channels": body.channels,
        },
    )
    execution = svc.run_tool_task(task_spec.task_id)
    summary = execution["summary"]
    return ConvertResponse(
        input_path=body.input_path,
        output_path=summary.get("primary_output", body.output_path),
        format=summary.get("format", body.target_format),
        sample_rate=summary.get("sample_rate", body.sample_rate),
        channels=summary.get("channels", body.channels),
        duration=summary.get("duration", 0.0),
    )


@router.post("/split", response_model=SplitResponse)
def split_by_subtitle(
    body: SplitRequest,
    svc: AudioToolService = Depends(audio_tool_service),
):
    task_spec = svc.create_tool_task_spec(
        task_type="tool.split",
        input_path=body.audio_path,
        companion_paths=[body.subtitle_path],
        execution_profile={
            "output_dir": body.output_dir,
            "padding": body.padding,
        },
    )
    execution = svc.run_tool_task(task_spec.task_id)
    summary = execution["summary"]
    return SplitResponse(
        audio_path=body.audio_path,
        subtitle_path=body.subtitle_path,
        segments=[
            SplitSegmentResponse(
                index=s["index"],
                start=s["start"],
                end=s["end"],
                text=s["text"],
                output_path=s["output_path"],
            )
            for s in summary.get("segments", [])
        ],
        total_segments=summary.get("total_segments", 0),
    )


@router.post("/translate-subtitle", response_model=SubtitleTranslationResponse)
def translate_subtitle(
    body: SubtitleTranslationRequest,
    svc: AudioToolService = Depends(audio_tool_service),
):
    task_spec = svc.create_tool_task_spec(
        task_type="tool.translate_subtitle",
        input_path=body.input_path,
        execution_profile={
            "output_path": body.output_path,
            "provider": body.provider,
            "source_lang": body.source_lang,
            "target_lang": body.target_lang,
            "bilingual": body.bilingual,
        },
    )
    execution = svc.run_tool_task(task_spec.task_id)
    summary = execution["summary"]
    return SubtitleTranslationResponse(
        input_path=body.input_path,
        output_path=summary.get("primary_output"),
        total_segments=summary.get("total_segments", 0),
        provider=body.provider,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
    )


@router.post("/volume-preview", response_model=VolumePreviewResponse)
def preview_volume(
    body: VolumePreviewRequest,
    svc: AudioToolService = Depends(audio_tool_service),
):
    task_spec = svc.create_tool_task_spec(
        task_type="tool.volume_preview",
        input_path=body.audio_path,
        execution_profile={
            "tts_path": body.tts_path,
            "original_volume": body.original_volume,
            "tts_volume_ratio": body.tts_volume_ratio,
        },
    )
    execution = svc.run_tool_task(task_spec.task_id)
    summary = execution["summary"]
    return VolumePreviewResponse(
        audio_path=body.audio_path,
        rms_volume=summary.get("rms_volume", 0.0),
        tts_rms_volume=summary.get("tts_rms_volume"),
        recommended_original_volume=summary.get("recommended_original_volume", body.original_volume),
        recommended_tts_ratio=summary.get("recommended_tts_ratio", body.tts_volume_ratio),
    )
