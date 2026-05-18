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
from src.app.dto import (
    ConvertRequest as ConvertDTO,
    SeparationRequest as SeparationDTO,
    SplitRequest as SplitDTO,
    SubtitleTranslationRequest as SubtitleTranslationDTO,
    VolumePreviewRequest as VolumePreviewDTO,
)
from src.app.services import AudioToolService

router = APIRouter(prefix="/tools", tags=["tools"])


@router.post("/separate", response_model=SeparationResponse)
def separate_vocals(
    body: SeparationRequest,
    svc: AudioToolService = Depends(audio_tool_service),
):
    result = svc.separate_vocals(SeparationDTO(
        input_path=body.input_path,
        output_dir=body.output_dir,
        model=body.model,
        stems=body.stems,
    ))
    return SeparationResponse(
        input_path=result.input_path,
        stems=result.stems,
        primary_output=result.primary_output,
    )


@router.post("/convert", response_model=ConvertResponse)
def convert_audio(
    body: ConvertRequest,
    svc: AudioToolService = Depends(audio_tool_service),
):
    result = svc.convert_audio(ConvertDTO(
        input_path=body.input_path,
        output_path=body.output_path,
        target_format=body.target_format,
        sample_rate=body.sample_rate,
        channels=body.channels,
    ))
    return ConvertResponse(
        input_path=result.input_path,
        output_path=result.output_path,
        format=result.format,
        sample_rate=result.sample_rate,
        channels=result.channels,
        duration=result.duration,
    )


@router.post("/split", response_model=SplitResponse)
def split_by_subtitle(
    body: SplitRequest,
    svc: AudioToolService = Depends(audio_tool_service),
):
    result = svc.split_by_subtitle(SplitDTO(
        audio_path=body.audio_path,
        subtitle_path=body.subtitle_path,
        output_dir=body.output_dir,
        padding=body.padding,
    ))
    return SplitResponse(
        audio_path=result.audio_path,
        subtitle_path=result.subtitle_path,
        segments=[
            SplitSegmentResponse(
                index=s.index,
                start=s.start,
                end=s.end,
                text=s.text,
                output_path=s.output_path,
            )
            for s in result.segments
        ],
        total_segments=result.total_segments,
    )


@router.post("/translate-subtitle", response_model=SubtitleTranslationResponse)
def translate_subtitle(
    body: SubtitleTranslationRequest,
    svc: AudioToolService = Depends(audio_tool_service),
):
    result = svc.translate_subtitle(SubtitleTranslationDTO(
        input_path=body.input_path,
        output_path=body.output_path,
        provider=body.provider,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
        bilingual=body.bilingual,
    ))
    return SubtitleTranslationResponse(
        input_path=result.input_path,
        output_path=result.output_path,
        total_segments=result.total_segments,
        provider=result.provider,
        source_lang=result.source_lang,
        target_lang=result.target_lang,
    )


@router.post("/volume-preview", response_model=VolumePreviewResponse)
def preview_volume(
    body: VolumePreviewRequest,
    svc: AudioToolService = Depends(audio_tool_service),
):
    result = svc.preview_volume(VolumePreviewDTO(
        audio_path=body.audio_path,
        tts_path=body.tts_path,
        original_volume=body.original_volume,
        tts_volume_ratio=body.tts_volume_ratio,
    ))
    return VolumePreviewResponse(
        audio_path=result.audio_path,
        rms_volume=result.rms_volume,
        tts_rms_volume=result.tts_rms_volume,
        recommended_original_volume=result.recommended_original_volume,
        recommended_tts_ratio=result.recommended_tts_ratio,
    )
