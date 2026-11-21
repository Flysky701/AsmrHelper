"""Stateless FastAPI HTTP server for remote/Colab GPU compute workers.

Supports Bearer token authentication, capability discovery, manual VRAM lease eviction,
and lossless FLAC/WAV binary multipart or JSON base64 payloads for separation, ASR,
forced alignment, and batch local TTS — without requiring `python-multipart`.
"""

from __future__ import annotations

import base64
from email.parser import BytesParser
import email.policy
import hmac
from importlib.util import find_spec
import json
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from packages.protocol.compute import (
    PROTOCOL_VERSION,
    AlignmentRequest,
    AlignmentResult,
    AsrRequest,
    AsrResult,
    LeaseEvictRequest,
    LeaseEvictResult,
    SeparationRequest,
    SeparationResult,
    TtsBatchRequest,
    TtsBatchResult,
    VcBatchRequest,
    VcBatchResult,
    WorkerCapabilities,
)
from packages.protocol.errors import ComputeErrorCode, ComputeErrorPayload, ComputeRemoteError

from .handlers import WorkerHandlers, classify_compute_exception
from .optional_model_process import optional_model_available
from .seed_vc_handler import run_seed_vc_batch
from .vram_lease import ModelLeaseManager

MAX_UPLOAD_BYTES = 512 * 1024 * 1024  # 512 MB guard for full-length ASMR tracks


def _status_for_error(exc: ComputeRemoteError) -> int:
    if exc.status_code is not None:
        return exc.status_code
    mapping = {
        ComputeErrorCode.AUTH_REQUIRED: 401,
        ComputeErrorCode.AUTH_INVALID: 401,
        ComputeErrorCode.INVALID_REQUEST: 400,
        ComputeErrorCode.AUDIO_DECODE_ERROR: 422,
        ComputeErrorCode.MODEL_NOT_AVAILABLE: 503,
        ComputeErrorCode.LEASE_CONFLICT: 503,
        ComputeErrorCode.OOM_ERROR: 503,
        ComputeErrorCode.TIMEOUT: 504,
    }
    return mapping.get(exc.code, 500)  # type: ignore[arg-type]


async def _parse_compute_request(
    request: Request,
    *,
    stage: str,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> tuple[dict[str, Any], dict[str, tuple[str | None, bytes]], bytes | None]:
    """Parse multipart/form-data, application/json, or raw audio bytes without python-multipart."""
    raw_body = await request.body()
    if len(raw_body) > max_bytes:
        raise ComputeRemoteError(
            code=ComputeErrorCode.INVALID_REQUEST,
            message=f"Request payload exceeds maximum limit ({max_bytes} bytes)",
            retryable=False,
            stage=stage,
            status_code=413,
        )

    content_type = (request.headers.get("content-type") or "").strip()
    lower_ct = content_type.lower()

    options_data: dict[str, Any] = {}
    header_opts = request.headers.get("x-compute-options")
    if header_opts:
        try:
            options_data.update(json.loads(header_opts))
        except Exception as exc:
            raise ComputeRemoteError(
                code=ComputeErrorCode.INVALID_REQUEST,
                message=f"Invalid JSON in X-Compute-Options header: {exc}",
                retryable=False,
                stage=stage,
                status_code=400,
            ) from exc

    for qk, qv in request.query_params.items():
        options_data.setdefault(qk, qv)

    if lower_ct.startswith("multipart/form-data"):
        if "boundary=" not in lower_ct:
            raise ComputeRemoteError(
                code=ComputeErrorCode.INVALID_REQUEST,
                message="Malformed multipart/form-data Content-Type (missing boundary)",
                retryable=False,
                stage=stage,
                status_code=400,
            )
        envelope = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1")
        msg = BytesParser(policy=email.policy.HTTP).parsebytes(envelope + raw_body)
        if not msg.is_multipart():
            raise ComputeRemoteError(
                code=ComputeErrorCode.INVALID_REQUEST,
                message="Failed to parse multipart/form-data payload",
                retryable=False,
                stage=stage,
                status_code=400,
            )

        files: dict[str, tuple[str | None, bytes]] = {}
        for part in msg.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            if not field_name:
                continue
            field_str = str(field_name)
            filename = part.get_filename()
            payload_bytes = part.get_payload(decode=True) or b""
            part_ct = (part.get_content_type() or "").lower()

            if filename is not None or part_ct.startswith("audio/") or field_str in {
                "audio",
                "file",
                "reference_audio",
            } or field_str.startswith("ref_"):
                files[field_str] = (filename, payload_bytes)
            else:
                text_val = payload_bytes.decode("utf-8", errors="replace").strip()
                if field_str in {"options", "request", "metadata", "payload"} and text_val:
                    try:
                        parsed = json.loads(text_val)
                    except Exception as exc:
                        raise ComputeRemoteError(
                            code=ComputeErrorCode.INVALID_REQUEST,
                            message=f"Invalid JSON in multipart field {field_str!r}: {exc}",
                            retryable=False,
                            stage=stage,
                            status_code=400,
                        ) from exc
                    if isinstance(parsed, dict):
                        options_data.update(parsed)
                else:
                    options_data[field_str] = text_val
        return options_data, files, None

    if lower_ct.startswith("application/json") or (not lower_ct and raw_body.startswith(b"{")):
        if not raw_body:
            return options_data, {}, None
        try:
            parsed_json = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            raise ComputeRemoteError(
                code=ComputeErrorCode.INVALID_REQUEST,
                message=f"Invalid JSON request body: {exc}",
                retryable=False,
                stage=stage,
                status_code=400,
            ) from exc
        if not isinstance(parsed_json, dict):
            raise ComputeRemoteError(
                code=ComputeErrorCode.INVALID_REQUEST,
                message="JSON request body must be an object",
                retryable=False,
                stage=stage,
                status_code=400,
            )
        options_data.update(parsed_json)
        return options_data, {}, None

    return options_data, {}, raw_body


def _extract_primary_audio(
    files: dict[str, tuple[str | None, bytes]],
    raw_body: bytes | None,
) -> tuple[bytes | None, str | None]:
    for key in ("audio", "file"):
        if key in files:
            fname, data = files[key]
            return data, fname
    if raw_body is not None and len(raw_body) > 0:
        return raw_body, None
    return None, None


def create_worker_app(
    token: str | None = None,
    *,
    handlers: WorkerHandlers | None = None,
    lease_manager: ModelLeaseManager | None = None,
) -> FastAPI:
    """Create the stateless FastAPI application for a GPU compute worker."""
    expected_token = token.strip() if token and token.strip() else None
    mgr = lease_manager or (handlers.lease_manager if handlers is not None else ModelLeaseManager())
    worker_handlers = handlers or WorkerHandlers(lease_manager=mgr)

    app = FastAPI(
        title="ASMR Helper GPU Worker",
        version=PROTOCOL_VERSION,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.handlers = worker_handlers
    app.state.lease_manager = mgr

    def verify_bearer(request: Request) -> None:
        if expected_token is None:
            return
        auth_header = request.headers.get("authorization") or ""
        scheme, _, credentials = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not credentials.strip():
            raise ComputeRemoteError(
                code=ComputeErrorCode.AUTH_REQUIRED,
                message="Missing Authorization: Bearer <token> header",
                retryable=False,
                stage="auth",
                status_code=401,
            )
        if not hmac.compare_digest(credentials.strip(), expected_token):
            raise ComputeRemoteError(
                code=ComputeErrorCode.AUTH_INVALID,
                message="Invalid Bearer token",
                retryable=False,
                stage="auth",
                status_code=401,
            )

    @app.exception_handler(ComputeRemoteError)
    async def _handle_compute_error(_req: Request, exc: ComputeRemoteError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for_error(exc),
            content=exc.payload.model_dump(),
        )

    @app.exception_handler(ValidationError)
    async def _handle_validation_error(_req: Request, exc: ValidationError) -> JSONResponse:
        payload = ComputeErrorPayload(
            code=ComputeErrorCode.INVALID_REQUEST,
            message=str(exc),
            retryable=False,
            stage="validation",
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    @app.get(
        "/v1/capabilities",
        response_model=WorkerCapabilities,
        dependencies=[Depends(verify_bearer)],
    )
    async def get_capabilities() -> WorkerCapabilities:
        caps = worker_handlers.lease_manager.capabilities()
        caps.optional_tts_providers = [
            provider for provider in ("cosyvoice2", "gpt_sovits") if optional_model_available(provider)
        ]
        if handlers is not None:
            return caps
        modules = {
            "separate": {"demucs": "demucs", "roformer": "audio_separator"},
            "asr": {"faster_whisper": "faster_whisper", "fun_asr": "funasr",
                    "qwen3_asr": "qwen_asr", "anime_whisper": "transformers"},
            "align": {"qwen3_forced_aligner": "qwen_asr"},
            "tts_batch": {"qwen3": "qwen_tts", "voxcpm2": "voxcpm"},
        }
        caps.installed_providers = {
            task: [provider for provider, module in providers.items() if find_spec(module) is not None]
            for task, providers in modules.items()
        }
        caps.installed_providers["tts_batch"].extend(caps.optional_tts_providers)
        caps.installed_providers["vc_batch"] = ["seed_vc"] if optional_model_available("seed_vc") else []
        return caps

    @app.post(
        "/v1/lease/evict",
        response_model=LeaseEvictResult,
        dependencies=[Depends(verify_bearer)],
    )
    async def evict_leases(request: Request) -> LeaseEvictResult:
        raw = await request.body()
        evict_req = LeaseEvictRequest()
        if raw.strip():
            try:
                evict_req = LeaseEvictRequest.model_validate_json(raw)
            except ValidationError:
                raise
            except Exception as exc:
                raise ComputeRemoteError(
                    code=ComputeErrorCode.INVALID_REQUEST,
                    message=f"Invalid eviction JSON payload: {exc}",
                    retryable=False,
                    stage="lease",
                    status_code=400,
                ) from exc
        evicted = await run_in_threadpool(
            worker_handlers.lease_manager.evict,
            evict_req.family,
            key=evict_req.key,
        )
        return LeaseEvictResult(
            evicted=evicted,
            loaded_models=worker_handlers.lease_manager.loaded_models(),
        )

    @app.post(
        "/v1/asr",
        response_model=AsrResult,
        dependencies=[Depends(verify_bearer)],
    )
    async def run_asr(request: Request) -> AsrResult:
        options, files, raw_body = await _parse_compute_request(request, stage="asr")
        audio_bytes, filename = _extract_primary_audio(files, raw_body)
        if filename and not options.get("audio_filename"):
            options["audio_filename"] = filename
        asr_req = AsrRequest.model_validate(options)
        # Never write subtitle files to client-specified local paths on a remote server.
        asr_req.output_path = None
        if audio_bytes is not None:
            asr_req.input_path = None
        try:
            return await run_in_threadpool(
                worker_handlers.asr,
                asr_req,
                audio_bytes=audio_bytes,
            )
        except Exception as exc:
            raise classify_compute_exception(exc, "asr") from exc

    @app.post(
        "/v1/separate",
        response_model=SeparationResult,
        dependencies=[Depends(verify_bearer)],
    )
    async def run_separate(request: Request) -> SeparationResult:
        options, files, raw_body = await _parse_compute_request(request, stage="separate")
        audio_bytes, filename = _extract_primary_audio(files, raw_body)
        if filename and not options.get("audio_filename"):
            options["audio_filename"] = filename
        if isinstance(options.get("stems"), str):
            options["stems"] = [s.strip() for s in options["stems"].split(",") if s.strip()]
        sep_req = SeparationRequest.model_validate(options)
        sep_req.output_dir = None
        if audio_bytes is not None:
            sep_req.input_path = None
        try:
            return await run_in_threadpool(
                worker_handlers.separate,
                sep_req,
                audio_bytes=audio_bytes,
                include_audio_b64=True,
            )
        except Exception as exc:
            raise classify_compute_exception(exc, "separate") from exc

    @app.post(
        "/v1/align",
        response_model=AlignmentResult,
        dependencies=[Depends(verify_bearer)],
    )
    async def run_align(request: Request) -> AlignmentResult:
        options, files, raw_body = await _parse_compute_request(request, stage="align")
        audio_bytes, filename = _extract_primary_audio(files, raw_body)
        if filename and not options.get("audio_filename"):
            options["audio_filename"] = filename
        if isinstance(options.get("segments"), str):
            options["segments"] = json.loads(options["segments"])
        align_req = AlignmentRequest.model_validate(options)
        if audio_bytes is not None:
            align_req.input_path = None
        try:
            return await run_in_threadpool(
                worker_handlers.align,
                align_req,
                audio_bytes=audio_bytes,
            )
        except Exception as exc:
            raise classify_compute_exception(exc, "align") from exc

    @app.post(
        "/v1/tts/batch",
        response_model=TtsBatchResult,
        dependencies=[Depends(verify_bearer)],
    )
    async def run_tts_batch(request: Request) -> TtsBatchResult:
        options, files, _raw_body = await _parse_compute_request(request, stage="tts_batch")
        if isinstance(options.get("items"), str):
            options["items"] = json.loads(options["items"])

        ref_bytes: bytes | None = None
        for ref_field in ("reference_audio", "audio", "file"):
            if ref_field in files:
                fname, data = files[ref_field]
                ref_bytes = data
                if fname and not options.get("reference_audio_filename"):
                    options["reference_audio_filename"] = fname
                break

        refs_b64 = dict(options.get("references_b64") or {})
        for field_key, (_fname, data) in files.items():
            if field_key.startswith("ref_"):
                ref_id = field_key[len("ref_") :]
                if ref_id:
                    refs_b64[ref_id] = base64.b64encode(data).decode("ascii")
        if refs_b64:
            options["references_b64"] = refs_b64

        tts_req = TtsBatchRequest.model_validate(options)
        # Keep server stateless: clear client-side paths before running in temp workspace.
        tts_req.reference_audio_path = None
        tts_req.references = {}
        for item in tts_req.items:
            item.output_path = None

        try:
            return await run_in_threadpool(
                worker_handlers.tts_batch,
                tts_req,
                reference_audio_bytes=ref_bytes,
                include_audio_b64=True,
            )
        except Exception as exc:
            raise classify_compute_exception(exc, "tts_batch") from exc

    @app.post("/v1/vc/batch", response_model=VcBatchResult, dependencies=[Depends(verify_bearer)])
    async def run_vc_batch(request: Request) -> VcBatchResult:
        options, files, _ = await _parse_compute_request(request, stage="vc_batch")
        vc_req = VcBatchRequest.model_validate(options)
        reference_ids = options.get("uploaded_reference_ids", [])
        if not isinstance(reference_ids, list) or not all(isinstance(i, str) for i in reference_ids):
            raise ComputeRemoteError(
                code=ComputeErrorCode.INVALID_REQUEST, message="Invalid uploaded_reference_ids",
                stage="vc_batch", retryable=False,
            )
        refs = {
            ref_id: files[f"reference_{index}"][1]
            for index, ref_id in enumerate(reference_ids) if f"reference_{index}" in files
        }
        sources = {
            item.id: files[f"source_{index}"][1]
            for index, item in enumerate(vc_req.items) if f"source_{index}" in files
        }
        vc_req.references = {}
        for item in vc_req.items:
            item.source_audio_path = None
            item.output_path = None
        try:
            return await run_in_threadpool(
                run_seed_vc_batch, worker_handlers.lease_manager, vc_req,
                source_uploads=sources, reference_uploads=refs, include_audio_b64=True,
            )
        except Exception as exc:
            raise classify_compute_exception(exc, "vc_batch") from exc

    return app
