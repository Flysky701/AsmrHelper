"""Voice profile and design routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.http.dependencies import voice_service
from src.api.http.schemas.tasks import TaskStatusResponse
from src.api.http.schemas.voice import (
    SegmentAnalyzeRequest,
    SegmentAnalyzeResponse,
    SegmentInfoResponse,
    VoiceCloneRequest,
    VoiceDesignRequest,
    VoicePreviewRequest,
    VoiceProfileResponse,
    VoiceProfileSummaryResponse,
)
from src.app.dto import (
    SegmentAnalyzeRequest as SegmentAnalyzeDTO,
    VoiceCloneRequest as VoiceCloneDTO,
    VoiceDesignRequest as VoiceDesignDTO,
    VoicePreviewRequest as VoicePreviewDTO,
)
from src.app.services import VoiceService

router = APIRouter(prefix="/voice", tags=["voice"])


@router.get("/profiles", response_model=list[VoiceProfileSummaryResponse])
def list_profiles(
    kind: str | None = None,
    svc: VoiceService = Depends(voice_service),
):
    profiles = svc.list_profiles(kind=kind)
    return [
        VoiceProfileSummaryResponse(
            id=p.id,
            name=p.name,
            category=p.category,
            engine=p.engine,
            description=p.description,
            available=p.available,
        )
        for p in profiles
    ]


@router.get("/profiles/{profile_id}", response_model=VoiceProfileResponse)
def get_profile(
    profile_id: str,
    svc: VoiceService = Depends(voice_service),
):
    p = svc.get_profile(profile_id)
    return VoiceProfileResponse(
        id=p.id,
        name=p.name,
        category=p.category,
        engine=p.engine,
        description=p.description,
        speaker=p.speaker,
        instruct=p.instruct,
        design_instruct=p.design_instruct,
        ref_audio=p.ref_audio,
        generated=p.generated,
        available=p.available,
    )


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(
    profile_id: str,
    svc: VoiceService = Depends(voice_service),
):
    svc.delete_profile(profile_id)


@router.post("/design", response_model=TaskStatusResponse, status_code=201)
def design_voice(
    body: VoiceDesignRequest,
    svc: VoiceService = Depends(voice_service),
):
    task = svc.submit_design_voice(VoiceDesignDTO(
        description=body.description,
        name=body.name,
        ref_text=body.ref_text,
    ))
    return TaskStatusResponse.from_task_status(task)


@router.post("/clone", response_model=TaskStatusResponse, status_code=201)
def clone_voice(
    body: VoiceCloneRequest,
    svc: VoiceService = Depends(voice_service),
):
    task = svc.submit_clone_voice(VoiceCloneDTO(
        audio_path=body.audio_path,
        name=body.name,
        ref_text=body.ref_text,
        x_vector_only_mode=body.x_vector_only_mode,
    ))
    return TaskStatusResponse.from_task_status(task)


@router.post("/analyze-segments", response_model=SegmentAnalyzeResponse)
def analyze_segments(
    body: SegmentAnalyzeRequest,
    svc: VoiceService = Depends(voice_service),
):
    result = svc.analyze_segments(SegmentAnalyzeDTO(
        audio_path=body.audio_path,
        subtitle_path=body.subtitle_path,
        audio_language=body.audio_language,
    ))
    return SegmentAnalyzeResponse(
        audio_path=result.audio_path,
        mode=result.mode,
        segments=[
            SegmentInfoResponse(
                index=s.index,
                start=s.start,
                end=s.end,
                text=s.text,
                duration=s.duration,
                score=s.score,
                label=s.label,
                details=s.details,
            )
            for s in result.segments
        ],
        recommended_indices=result.recommended_indices,
        warnings=result.warnings,
    )


@router.post("/profiles/{profile_id}/preview", response_model=TaskStatusResponse, status_code=201)
def preview_voice(
    profile_id: str,
    body: VoicePreviewRequest,
    svc: VoiceService = Depends(voice_service),
):
    task = svc.submit_preview_voice(VoicePreviewDTO(
        profile_id=profile_id,
        text=body.text,
        speed=body.speed,
        language=body.language,
    ))
    return TaskStatusResponse.from_task_status(task)
