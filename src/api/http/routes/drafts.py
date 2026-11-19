"""HTTP routes for Two-Phase DraftSession orchestration (`/api/v1/drafts`)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from src.api.http.dependencies import draft_session_service
from src.api.http.schemas.drafts import (
    CommitDraftRequest,
    DraftListResponse,
    DraftSessionResponse,
    InspectWorkRequest,
    InspectWorkResponse,
    PatchDraftRequest,
    PrepareDraftRequest,
    QualityAuditReportResponse,
)
from src.app.persistence.draft_store import DraftConflictError
from src.app.services.draft_session_service import DraftSessionService

router = APIRouter(prefix="/drafts", tags=["drafts"])


def _conflict_response(exc: DraftConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error": {"code": "REVISION_CONFLICT", "message": str(exc)}},
    )


@router.post("/inspect", response_model=InspectWorkResponse)
def inspect_work(
    body: InspectWorkRequest,
    svc: DraftSessionService = Depends(draft_session_service),
):
    return svc.inspect_work(body.path_or_dir)


@router.post("/prepare", response_model=DraftSessionResponse)
def prepare_draft(
    body: PrepareDraftRequest,
    svc: DraftSessionService = Depends(draft_session_service),
):
    return svc.prepare_draft(
        body.path_or_dir,
        track_path=body.track_path,
        subtitle_path=body.subtitle_path,
        script_path=body.script_path,
        title=body.title,
        source_lang=body.source_lang,
        target_lang=body.target_lang,
        enable_translation=body.enable_translation,
        force_asr=body.force_asr,
        asr_provider=body.asr_provider,
        asr_model=body.asr_model,
        asr_options=body.asr_options,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        llm_options=body.llm_options,
        voice_plan=body.voice_plan,
        prepare_stems=body.prepare_stems,
        extract_voice_reference=body.extract_voice_reference,
        synthesize_samples=body.synthesize_samples,
        sample_cue_count=body.sample_cue_count,
        chars_per_second=body.chars_per_second,
        max_atempo=body.max_atempo,
    )


@router.get("", response_model=DraftListResponse)
@router.get("/", response_model=DraftListResponse, include_in_schema=False)
def list_drafts(
    state: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    svc: DraftSessionService = Depends(draft_session_service),
):
    return {"drafts": svc.list_drafts(state=state, limit=limit)}


@router.get("/{draft_id}", response_model=DraftSessionResponse)
def get_draft(
    draft_id: str,
    svc: DraftSessionService = Depends(draft_session_service),
):
    return svc.get_draft(draft_id)


@router.get("/{draft_id}/audit", response_model=QualityAuditReportResponse)
def get_draft_audit(
    draft_id: str,
    svc: DraftSessionService = Depends(draft_session_service),
):
    return svc.get_audit_report(draft_id)


@router.patch("/{draft_id}", response_model=DraftSessionResponse)
def patch_draft(
    draft_id: str,
    body: PatchDraftRequest,
    svc: DraftSessionService = Depends(draft_session_service),
):
    try:
        edits_payload = [edit.model_dump(exclude_unset=True) for edit in body.edits]
        return svc.patch_draft(
            draft_id,
            edits=edits_payload,
            voice_plan_patch=body.voice_plan_patch,
            expected_revision=body.expected_revision,
            title=body.title,
        )
    except DraftConflictError as exc:
        return _conflict_response(exc)


@router.post("/{draft_id}/commit", response_model=DraftSessionResponse)
def commit_draft(
    draft_id: str,
    body: CommitDraftRequest,
    svc: DraftSessionService = Depends(draft_session_service),
):
    try:
        return svc.commit_draft(
            draft_id,
            body.output_dir,
            export_formats=body.export_formats,
            enable_dubbing=body.enable_dubbing,
            regenerate_cue_ids=body.regenerate_cue_ids,
            bilingual=body.bilingual,
            mix_options=body.mix_options,
            expected_revision=body.expected_revision,
        )
    except DraftConflictError as exc:
        return _conflict_response(exc)
