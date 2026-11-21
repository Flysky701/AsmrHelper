"""Optional batch voice conversion using an isolated Seed-VC checkout."""

from __future__ import annotations

import base64
from pathlib import Path
import tempfile

from packages.protocol.compute import VcBatchItemResult, VcBatchRequest, VcBatchResult
from packages.protocol.errors import ComputeErrorCode, ComputeRemoteError

from .handlers import (
    classify_compute_exception,
    decode_audio_bytes_to_file,
    encode_audio_file_bytes,
    materialize_audio_bytes_to_path,
)
from .optional_model_process import run_optional_model_process
from .vram_lease import ModelLeaseManager

STAGE = "vc_batch"


def _resolve_audio(
    path: str | None, encoded: str | None, upload: bytes | None, workdir: Path,
) -> Path:
    if upload is not None or encoded is not None:
        if upload is None:
            try:
                upload = base64.b64decode(encoded or "", validate=True)
            except ValueError as exc:
                raise ComputeRemoteError(
                    code=ComputeErrorCode.AUDIO_DECODE_ERROR, message="Invalid base64 voice audio",
                    stage=STAGE, retryable=False,
                ) from exc
        staged, _, _ = decode_audio_bytes_to_file(upload, workdir, stage=STAGE)
        return staged
    if path and Path(path).is_file():
        return Path(path).resolve()
    raise ComputeRemoteError(
        code=ComputeErrorCode.INVALID_REQUEST, message="Missing source or reference voice audio",
        stage=STAGE, retryable=False,
    )


def run_seed_vc_batch(
    manager: ModelLeaseManager,
    request: VcBatchRequest,
    *,
    source_uploads: dict[str, bytes] | None = None,
    reference_uploads: dict[str, bytes] | None = None,
    include_audio_b64: bool = False,
) -> VcBatchResult:
    with tempfile.TemporaryDirectory(prefix="gpu-vc-") as temp:
        workdir = Path(temp).resolve()
        refs: dict[str, Path] = {}
        results: dict[str, VcBatchItemResult] = {}
        jobs = {}
        for index, item in enumerate(request.items):
            try:
                if item.reference_id not in refs:
                    refs[item.reference_id] = _resolve_audio(
                        request.references.get(item.reference_id),
                        request.references_b64.get(item.reference_id),
                        (reference_uploads or {}).get(item.reference_id),
                        workdir,
                    )
                source = _resolve_audio(
                    item.source_audio_path, item.source_audio_b64,
                    (source_uploads or {}).get(item.id), workdir,
                )
                jobs[item.id] = {
                    "source": str(source), "reference": str(refs[item.reference_id]),
                    "output": str(workdir / f"converted-{index}.wav"),
                    "diffusion_steps": request.diffusion_steps,
                }
            except Exception as exc:
                results[item.id] = VcBatchItemResult(
                    id=item.id, ok=False, output_format=request.output_format,
                    error=classify_compute_exception(exc, STAGE).payload,
                )
        errors = run_optional_model_process(
            manager, request.provider_id, {"items": list(jobs.values())}, workdir, stage=STAGE,
        ) if jobs else {}
        for item in request.items:
            if item.id not in jobs:
                continue
            produced = jobs[item.id]["output"]
            try:
                if produced in errors:
                    raise RuntimeError(errors[produced])
                encoded, rate, duration = encode_audio_file_bytes(produced, request.output_format, stage=STAGE)
                target = item.output_path if not include_audio_b64 else None
                if target:
                    materialize_audio_bytes_to_path(encoded, target, stage=STAGE)
                results[item.id] = VcBatchItemResult(
                    id=item.id, output_path=target, output_format=request.output_format,
                    sample_rate=rate, duration_seconds=duration,
                    audio_b64=None if target else base64.b64encode(encoded).decode("ascii"),
                )
            except Exception as exc:
                results[item.id] = VcBatchItemResult(
                    id=item.id, ok=False, output_format=request.output_format,
                    error=classify_compute_exception(exc, STAGE).payload,
                )
        return VcBatchResult(
            output_format=request.output_format,
            items=[results[item.id] for item in request.items],
        )
