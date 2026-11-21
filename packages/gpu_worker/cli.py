"""Command-line entry point for `packages.gpu_worker`.

Supports two execution modes sharing the exact same stateless handlers:
1. Local single-shot subprocess mode:
   `python -m packages.gpu_worker.cli --once <job.json>`
2. Remote / Colab HTTP server mode:
   `python -m packages.gpu_worker.cli --serve --host 127.0.0.1 --port 8765 --token <secret>`
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Any

from packages.protocol.compute import (
    AlignmentRequest,
    AsrRequest,
    LeaseEvictRequest,
    LeaseEvictResult,
    SeparationRequest,
    TtsBatchRequest,
    VcBatchRequest,
)
from packages.protocol.errors import ComputeErrorCode, ComputeRemoteError

from .handlers import WorkerHandlers, classify_compute_exception
from .vram_lease import ModelLeaseManager


def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".gpu-resp-", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def execute_once_job(
    job: dict[str, Any],
    *,
    handlers: WorkerHandlers | None = None,
) -> dict[str, Any]:
    """Execute a single deserialized `--once` job dictionary and return its envelope."""
    task = str(job.get("task") or "").strip()
    raw_req = dict(job.get("request") or {})
    worker = handlers or WorkerHandlers()

    if not task:
        raise ComputeRemoteError(
            code=ComputeErrorCode.INVALID_REQUEST,
            message="Missing 'task' field in job JSON",
            retryable=False,
            stage="cli",
        )

    if task == "capabilities":
        res_model = worker.lease_manager.capabilities()
    elif task == "evict":
        ev_req = LeaseEvictRequest.model_validate(raw_req)
        evicted = worker.lease_manager.evict(ev_req.family, key=ev_req.key)
        res_model = LeaseEvictResult(
            evicted=evicted,
            loaded_models=worker.lease_manager.loaded_models(),
        )
    elif task == "separate":
        sep_req = SeparationRequest.model_validate(raw_req)
        res_model = worker.separate(sep_req, include_audio_b64=not bool(sep_req.output_dir))
    elif task == "asr":
        asr_req = AsrRequest.model_validate(raw_req)
        res_model = worker.asr(asr_req)
    elif task == "align":
        align_req = AlignmentRequest.model_validate(raw_req)
        res_model = worker.align(align_req)
    elif task == "tts_batch":
        tts_req = TtsBatchRequest.model_validate(raw_req)
        needs_b64 = any(not item.output_path for item in tts_req.items)
        res_model = worker.tts_batch(tts_req, include_audio_b64=needs_b64)
    elif task == "vc_batch":
        from .seed_vc_handler import run_seed_vc_batch

        res_model = run_seed_vc_batch(worker.lease_manager, VcBatchRequest.model_validate(raw_req))
    else:
        raise ComputeRemoteError(
            code=ComputeErrorCode.INVALID_REQUEST,
            message=f"Unsupported gpu-worker task: {task!r}",
            retryable=False,
            stage="cli",
        )

    return {
        "ok": True,
        "task": task,
        "result": res_model.model_dump(),
    }


def run_once_file(
    job_path: str | Path,
    *,
    handlers: WorkerHandlers | None = None,
) -> int:
    """Read `<job.json>`, execute once, and emit the JSON response envelope."""
    src = Path(job_path)
    stage = "cli"
    response_path: Path | None = None
    try:
        if not src.is_file():
            raise FileNotFoundError(f"Job file not found: {src}")
        job_data = json.loads(src.read_text(encoding="utf-8"))
        if not isinstance(job_data, dict):
            raise ValueError("Job JSON root must be an object")
        stage = str(job_data.get("task") or "cli")
        if job_data.get("response_path"):
            response_path = Path(str(job_data["response_path"]))
        envelope = execute_once_job(job_data, handlers=handlers)
        exit_code = 0
    except Exception as exc:
        mapped = classify_compute_exception(exc, stage)
        envelope = {
            "ok": False,
            "error": mapped.payload.model_dump(),
        }
        exit_code = 1

    if response_path is not None:
        _atomic_write_json(response_path, envelope)
    else:
        sys.stdout.write(json.dumps(envelope, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="packages.gpu_worker.cli",
        description="ASMR Helper stateless GPU compute worker (local --once or remote --serve).",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--session", metavar="READY_FILE", help="Read local job paths from stdin with one model lease manager.")
    mode.add_argument(
        "--once",
        metavar="JOB_JSON",
        help="Execute a single compute job from a JSON file and exit.",
    )
    mode.add_argument(
        "--serve",
        action="store_true",
        help="Run the FastAPI HTTP compute worker server.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host in --serve mode (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Bind port in --serve mode (default: 8765).",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional Bearer token for --serve mode (falls back to ASMR_WORKER_TOKEN env var).",
    )
    parser.add_argument(
        "--max-heavy-models",
        type=int,
        default=None,
        help="Maximum heavy models kept resident in VRAM simultaneously.",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["critical", "error", "warning", "info", "debug"],
        help="Uvicorn log level in --serve mode.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.once:
        return run_once_file(args.once)

    if args.session:
        handlers = WorkerHandlers()
        _atomic_write_json(Path(args.session), {"status": "ready"})
        for line in sys.stdin:
            path = line.strip()
            if path == "STOP":
                break
            if path:
                run_once_file(path, handlers=handlers)
        return 0

    import uvicorn

    from .server import create_worker_app

    token = args.token if args.token is not None else os.getenv("ASMR_WORKER_TOKEN")
    lease_mgr = ModelLeaseManager(max_heavy_models=args.max_heavy_models)
    app = create_worker_app(token=token, lease_manager=lease_mgr)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
