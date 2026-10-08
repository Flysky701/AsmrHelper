"""The VoiceLab v2 API; no legacy voice-profile projection."""
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from src.app.services.speech_service import get_speech_service
from src.core.speech.providers import list_providers, get_provider
from src.api.http.schemas.tasks import TaskStatusResponse
from src.api.http.schemas.speech import (
    ConnectionDefaultRequest, ConnectionDeletionPreviewRequest, ConnectionDeletionRequest,
)
from src.core.speech.store import ConnectionConflictError

router = APIRouter(prefix="/speech", tags=["speech"])
from .speech_cleanup import router as cleanup_router
router.include_router(cleanup_router)
MAX_REFERENCE_UPLOAD = 100 * 1024 * 1024
REFERENCE_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma"}


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


@router.get("/connections")
def connections(svc=Depends(get_speech_service)):
    return {"connections": call(svc.list_connections), "defaults": call(svc.connection_defaults)}


def connection_change(fn, *args, **kwargs):
    from src.app.services.preset_catalog_service import PresetConflictError
    try:
        return fn(*args, **kwargs)
    except (ConnectionConflictError, PresetConflictError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, TypeError, FileNotFoundError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/connections/{connection_id}/default")
def default_connection(connection_id: str, body: ConnectionDefaultRequest, svc=Depends(get_speech_service)):
    return connection_change(svc.set_default_connection, connection_id, **body.model_dump())


@router.post("/connections/{connection_id}/deletion-preview")
def connection_deletion_preview(connection_id: str, body: ConnectionDeletionPreviewRequest,
                                svc=Depends(get_speech_service)):
    return connection_change(svc.connection_deletion_preview, connection_id)


@router.post("/connections/{connection_id}/deletion-execute")
def delete_connection(connection_id: str, body: ConnectionDeletionRequest, svc=Depends(get_speech_service)):
    return connection_change(svc.delete_connection, connection_id, **body.model_dump())


@router.post("/connections")
def connection(body: dict, svc=Depends(get_speech_service)):
    return call(svc.save_connection, body)


@router.post("/connections/local-default")
def local_default_connection(body: dict, svc=Depends(get_speech_service)):
    return call(svc.resolve_local_connection, required(body, "provider_id"),
                required(body, "model"), required(body, "mode"))


@router.post("/connections/{connection_id}/probe")
def probe(connection_id: str, body: dict | None = None, svc=Depends(get_speech_service)):
    item = call(svc.store.get, "connections", connection_id)
    context = call(svc.connection_context, item)
    context.update({k: v for k, v in (body or {}).items() if k in {"model", "mode"}})
    return call(get_provider(item["provider_id"]).probe, context)


@router.get("/connections/{connection_id}/voices")
def connection_voices(connection_id: str, title: str = Query("", max_length=200),
                      page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100),
                      workspace_only: bool = True,
                      scope: Literal["workspace", "mine_public", "public"] | None = None,
                      svc=Depends(get_speech_service)):
    item = call(svc.store.get, "connections", connection_id)
    if item.get("provider_id") != "fish_audio":
        raise HTTPException(422, "此连接不支持获取声音列表，请手填 Voice ID")
    context = call(svc.connection_context, item)
    return call(get_provider("fish_audio").list_hosted_voices, context,
                title=title, page=page, page_size=page_size, workspace_only=workspace_only, scope=scope)


@router.post("/voices")
def voice(body: dict, svc=Depends(get_speech_service)):
    if not str(body.get("name", "")).strip():
        raise HTTPException(422, "请填写声音名称")
    for binding in body.get("bindings", []):
        call(get_provider, required(binding, "provider_id"))
    if body.get("id"):
        return call(svc.store.update, "voices", body["id"], body, expected_revision=body.get("revision"))
    return call(svc.store.create, "voices", body)


def fish_clones(svc):
    from src.app.services.fish_clone_service import FishCloneService
    return FishCloneService(svc)


@router.get("/fish-clones")
def list_fish_clones(include_deleted: bool = False, svc=Depends(get_speech_service)):
    return {"items": call(fish_clones(svc).list, include_deleted=include_deleted)}


@router.delete("/fish-clones/{clone_id}")
def delete_fish_clone_record(clone_id: str, svc=Depends(get_speech_service)):
    return call(fish_clones(svc).set_deleted, clone_id, True)


@router.post("/fish-clones/{clone_id}/restore")
def restore_fish_clone_record(clone_id: str, svc=Depends(get_speech_service)):
    return call(fish_clones(svc).set_deleted, clone_id, False)


@router.post("/fish-clones/preview")
def preview_fish_clone(body: dict, svc=Depends(get_speech_service)):
    return call(fish_clones(svc).preview, body)


@router.post("/fish-clones")
def create_fish_clone(body: dict, svc=Depends(get_speech_service)):
    return call(fish_clones(svc).create, body)


@router.post("/fish-clones/{clone_id}/refresh")
def refresh_fish_clone(clone_id: str, svc=Depends(get_speech_service)):
    return call(fish_clones(svc).refresh, clone_id)


@router.post("/fish-clones/{clone_id}/rule")
def fish_clone_rule(clone_id: str, svc=Depends(get_speech_service)):
    return call(fish_clones(svc).save_rule, clone_id)


@router.post("/recipes")
def recipe(body: dict, svc=Depends(get_speech_service)):
    return call(svc.save_recipe, body)


@router.post("/rules")
def save_rule(body: dict, svc=Depends(get_speech_service)):
    return call(svc.save_rule, body)


@router.get("/rules")
def rules(include_archived: bool = False, svc=Depends(get_speech_service)):
    return {"recipes": call(svc.active_recipes, include_archived=include_archived)}


@router.delete("/rules/{id}")
def archive_rule(id: str, svc=Depends(get_speech_service)):
    return call(svc.archive_rule, id)


@router.patch("/rules/{id}")
def rule_archive_status(id: str, body: dict, svc=Depends(get_speech_service)):
    if set(body) != {"archived"} or type(body["archived"]) is not bool:
        raise HTTPException(422, "请提供 archived 布尔值")
    return call(svc.archive_rule, id, archived=body["archived"])


@router.post("/plans")
def plan(body: dict, svc=Depends(get_speech_service)):
    return call(svc.create_plan, body)


@router.post("/plan-performance")
def performance(body: dict, svc=Depends(get_speech_service)):
    return call(svc.auto_performance, required(body, "plan_id"), body.get("connection_ref"))


@router.post("/compile")
def compile_plan(body: dict, svc=Depends(get_speech_service)):
    if set(body) - {"recipe_id", "recipe_draft", "plan_id"}:
        raise HTTPException(422, "编译请求包含未知字段")
    if ("recipe_id" in body) == ("recipe_draft" in body):
        raise HTTPException(422, "recipe_id 与 recipe_draft 必须且只能提供一个")
    return {"requests": call(svc.compile, body.get("recipe_id"), required(body, "plan_id"), body.get("recipe_draft"))}


@router.post("/references/inspect")
def inspect_reference(body: dict, svc=Depends(get_speech_service)):
    return call(svc.store.inspect_reference, required(body, "path"))


@router.post("/references/upload")
async def upload_reference(request: Request, filename: str, svc=Depends(get_speech_service)):
    """Stream a browser-selected file into the same inspection flow as native paths."""
    suffix = Path(filename).suffix.lower()
    if suffix not in REFERENCE_EXTENSIONS:
        raise HTTPException(422, "请选择支持的音频文件")
    length = request.headers.get("content-length")
    if length is not None:
        try:
            size = int(length)
        except ValueError as exc:
            raise HTTPException(400, "无效的文件长度") from exc
        if size > MAX_REFERENCE_UPLOAD:
            raise HTTPException(413, "参考音频不能超过 100 MB，请先裁剪")
    directory = svc.store.root / "_uploads"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (uuid4().hex + suffix)
    received = 0
    try:
        with path.open("xb") as stream:
            async for chunk in request.stream():
                received += len(chunk)
                if received > MAX_REFERENCE_UPLOAD:
                    raise HTTPException(413, "参考音频不能超过 100 MB，请先裁剪")
                stream.write(chunk)
        if not received:
            raise HTTPException(422, "音频文件为空")
        return await run_in_threadpool(call, svc.store.inspect_reference, path)
    finally:
        path.unlink(missing_ok=True)


@router.post("/references/analyze")
def analyze_reference(body: dict, svc=Depends(get_speech_service)):
    return call(svc.analyze_reference, body)


@router.post("/references/analyze-tasks", status_code=202)
def start_reference_analysis(body: dict, svc=Depends(get_speech_service)):
    return TaskStatusResponse.from_task_status(call(svc.start_reference_analysis, body))


@router.get("/references/analyze-tasks/{task_id}")
def reference_analysis(task_id: str, svc=Depends(get_speech_service)):
    status, result = call(svc.reference_analysis, task_id)
    return {"status": TaskStatusResponse.from_task_status(status), "result": result}


@router.post("/references/transcribe-tasks", status_code=202)
def start_reference_transcription(body: dict, svc=Depends(get_speech_service)):
    return TaskStatusResponse.from_task_status(call(svc.start_reference_transcription, body))


@router.post("/references")
def reference(body: dict, svc=Depends(get_speech_service)):
    return _process_reference(body, svc)


def _process_reference(body, svc, preview=False):
    return call(svc.store.import_reference, required(body, "path"), body.get("start", 0), body.get("end"),
        body.get("transcript", ""), body.get("language", "auto"), confirmed=body.get("confirmed", False),
        name=body.get("name", ""), notes=body.get("notes", ""), gain_db=body.get("gain_db", 0),
        fade_in=body.get("fade_in", 0), fade_out=body.get("fade_out", 0), preview=preview)


@router.post("/references/preview")
def preview_reference(body: dict, svc=Depends(get_speech_service)):
    return _process_reference(body, svc, preview=True)


@router.get("/references")
def references(query: str = "", include_archived: bool = False, svc=Depends(get_speech_service)):
    return {"assets": [a for a in svc.store.list("assets") if (include_archived or not a.get("archived"))
        and query.casefold() in (a.get("name", "") + " " + a.get("notes", "")).casefold()]}


@router.patch("/references/{id}")
def reference_metadata(id: str, body: dict, svc=Depends(get_speech_service)):
    return call(svc.store.reference_metadata, id, body)


@router.delete("/references/{id}")
def archive_reference(id: str, svc=Depends(get_speech_service)):
    # Archive only: recipes, frozen task snapshots and audio paths remain valid.
    return call(svc.store.reference_metadata, id, {"archived": True})


@router.post("/references/subtitles")
def reference_subtitles(body: dict):
    from src.core.subtitles.parser import SubtitleParser
    if body.get("format", "srt") not in {"srt", "vtt"}:
        raise HTTPException(422, "仅支持 SRT 或 VTT")
    doc = call(SubtitleParser().parse_text, required(body, "text"), body.get("format", "srt"))
    return {"segments": [{"start": s.start, "end": s.end, "text": s.text} for s in doc.segments]}


def reference_record(svc, asset_id):
    try:
        return svc.store.get("assets", asset_id)
    except (ValueError, KeyError):
        return svc.store.get_inspection(asset_id)


@router.get("/references/{asset_id}/waveform")
def waveform(asset_id: str, svc=Depends(get_speech_service)):
    return call(reference_record, svc, asset_id)


@router.get("/references/{asset_id}/audio")
def reference_audio(asset_id: str, source: bool = False, download: bool = False, svc=Depends(get_speech_service)):
    asset = call(reference_record, svc, asset_id)
    path = (asset.get("source_playback_path") or asset.get("source_path")) if source else asset.get("path")
    audio_path = Path(path or asset["path"])
    return FileResponse(audio_path, filename=audio_path.name if download else None)


@router.post("/experiments")
def experiment(body: dict, svc=Depends(get_speech_service)):
    if "media_root" in body:
        raise HTTPException(422, "正式配音文件目录由任务创建，不能在试听中指定")
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


@router.post("/takes/{take_id}/rule")
def rule_from_take(take_id: str, body: dict, svc=Depends(get_speech_service)):
    return call(svc.save_rule_from_take, take_id, body)


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
