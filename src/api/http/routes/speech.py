"""The VoiceLab v2 API; no legacy voice-profile projection."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from src.app.services.speech_service import get_speech_service
from src.core.speech.providers import list_providers, get_provider
from src.api.http.schemas.tasks import TaskStatusResponse

router = APIRouter(prefix="/speech", tags=["speech"])


def call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (ValueError, KeyError, TypeError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc)) from exc


def required(body, key):
    if key not in body or body[key] is None or body[key] == "":
        raise HTTPException(422, f"缺少字段：{key}")
    return body[key]


@router.get("/providers")
def providers():
    return {"providers": list_providers()}


@router.get("/library")
def library(svc=Depends(get_speech_service)):
    return svc.library()


@router.post("/connections")
def connection(body: dict, svc=Depends(get_speech_service)):
    return call(svc.save_connection, body)


@router.post("/connections/{connection_id}/probe")
def probe(connection_id: str, body: dict | None = None, svc=Depends(get_speech_service)):
    item = call(svc.store.get, "connections", connection_id)
    context = call(svc.connection_context, item)
    context.update({k: v for k, v in (body or {}).items() if k in {"model", "mode"}})
    return call(get_provider(item["provider_id"]).probe, context)


@router.post("/voices")
def voice(body: dict, svc=Depends(get_speech_service)):
    if not str(body.get("name", "")).strip():
        raise HTTPException(422, "请填写声音名称")
    for binding in body.get("bindings", []):
        call(get_provider, required(binding, "provider_id"))
    if body.get("id"):
        return call(svc.store.update, "voices", body["id"], body, expected_revision=body.get("revision"))
    return call(svc.store.create, "voices", body)


@router.post("/recipes")
def recipe(body: dict, svc=Depends(get_speech_service)):
    return call(svc.save_recipe, body)


@router.post("/plans")
def plan(body: dict, svc=Depends(get_speech_service)):
    return call(svc.create_plan, body)


@router.post("/plan-performance")
def performance(body: dict, svc=Depends(get_speech_service)):
    return call(svc.auto_performance, required(body, "plan_id"), body.get("connection_ref"))


@router.post("/compile")
def compile_plan(body: dict, svc=Depends(get_speech_service)):
    return {"requests": call(svc.compile, required(body, "recipe_id"), required(body, "plan_id"))}


@router.post("/references/inspect")
def inspect_reference(body: dict, svc=Depends(get_speech_service)):
    return call(svc.store.inspect_reference, required(body, "path"))


@router.post("/references/analyze")
def analyze_reference(body: dict, svc=Depends(get_speech_service)):
    return call(svc.analyze_reference, body)


@router.post("/references")
def reference(body: dict, svc=Depends(get_speech_service)):
    return call(svc.store.import_reference, required(body, "path"), body.get("start", 0), body.get("end"),
        body.get("transcript", ""), body.get("language", "auto"), confirmed=body.get("confirmed", False))


def reference_record(svc, asset_id):
    try:
        return svc.store.get("assets", asset_id)
    except (ValueError, KeyError):
        return svc.store.get_inspection(asset_id)


@router.get("/references/{asset_id}/waveform")
def waveform(asset_id: str, svc=Depends(get_speech_service)):
    return call(reference_record, svc, asset_id)


@router.get("/references/{asset_id}/audio")
def reference_audio(asset_id: str, source: bool = False, svc=Depends(get_speech_service)):
    asset = call(reference_record, svc, asset_id)
    path = (asset.get("source_playback_path") or asset.get("source_path")) if source else asset.get("path")
    return FileResponse(path or asset["path"])


@router.post("/experiments")
def experiment(body: dict, svc=Depends(get_speech_service)):
    call(svc.store.get, "plans", required(body, "plan_id"))
    return call(svc.store.create, "experiments", body)


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str, svc=Depends(get_speech_service)):
    return call(svc.experiment, experiment_id)


@router.post("/experiments/{experiment_id}/generate", status_code=202)
def generate(experiment_id: str, body: dict, svc=Depends(get_speech_service)):
    return TaskStatusResponse.from_task_status(call(svc.generate, experiment_id, body))


@router.post("/selections")
def select(body: dict, svc=Depends(get_speech_service)):
    return call(svc.select, body)


@router.get("/takes/{take_id}/audio")
def take_audio(take_id: str, svc=Depends(get_speech_service)):
    take = call(svc.store.get, "takes", take_id)
    return FileResponse(take["audio_path"], media_type="audio/wav")


@router.post("/assemblies")
def assembly(body: dict, svc=Depends(get_speech_service)):
    return call(svc.assemble, required(body, "experiment_id"))


@router.get("/assemblies/{assembly_id}/audio")
def assembly_audio(assembly_id: str, svc=Depends(get_speech_service)):
    assembly = call(svc.store.get, "assemblies", assembly_id)
    return FileResponse(assembly.get("mixed_path") or assembly["audio_path"], media_type="audio/wav", filename="voice-lab.wav")


@router.post("/workbench-draft")
def draft(body: dict, svc=Depends(get_speech_service)):
    return {"recipe": call(svc.store.get, "recipes", required(body, "recipe_id"))}
