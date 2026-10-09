"""Small cleanup endpoints, mounted inside the existing speech router."""
from fastapi import APIRouter, Depends, HTTPException
from src.app.services.speech_service import get_speech_service
from src.app.services.speech_cleanup_service import SpeechCleanupService

router = APIRouter()


def invoke(svc, method, *args, **kwargs):
    try:
        return getattr(SpeechCleanupService(svc), method)(*args, **kwargs)
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/cleanup/{kind}/{item_id}/preview")
def preview(kind: str, item_id: str, svc=Depends(get_speech_service)):
    return invoke(svc, "preview", kind, item_id)


@router.post("/cleanup/{kind}/{item_id}/execute")
def execute(kind: str, item_id: str, body: dict, svc=Depends(get_speech_service)):
    return invoke(svc, "execute", kind, item_id, body.get("token"), body.get("confirmed", False))


@router.get("/cleanup/legacy-records")
def legacy_records(svc=Depends(get_speech_service)):
    return invoke(svc, "legacy_records")
