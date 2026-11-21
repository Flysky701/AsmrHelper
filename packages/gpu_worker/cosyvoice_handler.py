"""Optional CosyVoice 2 and GPT-SoVITS reference-cloning Worker providers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from packages.protocol.compute import TtsBatchItemResult, TtsBatchRequest
from packages.protocol.errors import ComputeErrorCode, ComputeRemoteError

from .handlers import classify_compute_exception
from .optional_model_process import run_optional_model_process

if TYPE_CHECKING:
    from .handlers import WorkerHandlers


def _gpt_language(language: str, default: str) -> str:
    key = language.lower().strip().replace("_", "-").split("-", 1)[0]
    return {
        "chinese": "zh", "english": "en", "japanese": "ja",
        "jp": "ja", "korean": "ko", "cantonese": "yue",
    }.get(key, key or default)


def run_optional_tts_batch(
    handlers: WorkerHandlers,
    request: TtsBatchRequest,
    resolved_refs: dict[str, str],
    temp_dir: Path,
    *,
    include_audio_b64: bool,
) -> list[TtsBatchItemResult]:
    workdir = temp_dir.resolve()
    jobs = {}
    results = {}
    for index, item in enumerate(request.items):
        options = {**request.options, **item.options}
        reference = resolved_refs.get(item.reference_id or "default")
        if not reference and len(resolved_refs) == 1:
            reference = resolved_refs.get("default")
        if not reference:
            error = ComputeRemoteError(
                code=ComputeErrorCode.INVALID_REQUEST,
                message=f"{request.provider_id} requires reference audio for cue {item.item_id}.",
                stage="tts_batch",
                retryable=False,
            )
            results[index] = TtsBatchItemResult(
                item_id=item.item_id, ok=False, output_format=request.output_format, error=error.payload,
            )
            continue
        ref_text = item.reference_transcript or str(options.get("reference_text") or "")
        jobs[index] = {
            "text": item.text,
            "language": _gpt_language(item.language, "auto"),
            "reference": str(Path(reference).resolve()),
            "reference_text": ref_text,
            "reference_language": _gpt_language(str(options.get("reference_language") or ""), "auto"),
            "seed": options.get("seed", -1),
            "temperature": options.get("temperature", 1.0),
            "output": str(workdir / f"tts-{index}.wav"),
        }

    errors = run_optional_model_process(
        handlers.lease_manager, request.provider_id, {"items": list(jobs.values())}, workdir,
        stage="tts_batch",
    ) if jobs else {}
    for index, job in jobs.items():
        item = request.items[index]
        produced = str(job["output"])
        try:
            if produced in errors:
                raise RuntimeError(errors[produced])
            results[index] = handlers._finalize_tts_item_file(
                item=item, produced_file=Path(produced), output_format=request.output_format,
                include_audio_b64=include_audio_b64,
            )
        except Exception as exc:
            results[index] = TtsBatchItemResult(
                item_id=item.item_id, ok=False, output_format=request.output_format,
                error=classify_compute_exception(exc, "tts_batch").payload,
            )
    return [results[index] for index in range(len(request.items))]
