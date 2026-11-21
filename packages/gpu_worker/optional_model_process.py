"""Run an optional GPU model in its own Python environment for a batch."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any
from uuid import uuid4

from packages.protocol.errors import ComputeErrorCode, ComputeRemoteError

from .vram_lease import ModelLeaseManager


def optional_model_available(provider_id: str) -> bool:
    prefix = "ASMR_" + provider_id.upper()
    root = os.environ.get(f"{prefix}_ROOT")
    python = os.environ.get(f"{prefix}_PYTHON")
    return bool(root and python and Path(root).is_dir() and Path(python).is_file())


def run_optional_model_process(
    manager: ModelLeaseManager,
    provider_id: str,
    payload: dict[str, Any],
    workdir: Path,
    *,
    stage: str,
) -> dict[str, str]:
    prefix = "ASMR_" + provider_id.upper()
    if not optional_model_available(provider_id):
        raise ComputeRemoteError(
            code=ComputeErrorCode.MODEL_NOT_AVAILABLE,
            message=f"Configure {prefix}_ROOT and {prefix}_PYTHON on the GPU Worker.",
            stage=stage,
            retryable=False,
        )
    root = Path(os.environ[f"{prefix}_ROOT"]).resolve()
    executable = Path(os.environ[f"{prefix}_PYTHON"]).absolute()
    env = os.environ.copy()
    cuda_libraries = sorted(executable.parent.parent.glob("lib/python*/site-packages/nvidia/*/lib"))
    if cuda_libraries:
        env["LD_LIBRARY_PATH"] = os.pathsep.join([*map(str, cuda_libraries), env.get("LD_LIBRARY_PATH", "")]).rstrip(os.pathsep)
    runner = Path(__file__).with_name("optional_model_runner.py").resolve()
    request_file = workdir / "model-request.json"
    result_file = workdir / "model-result.json"
    request_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    lease_key = f"{provider_id}:{uuid4().hex}"
    family = provider_id if stage == "tts_batch" else "vc"
    try:
        with manager.lease(lease_key, object, family=family):
            with (workdir / "model.log").open("w+b") as log:
                try:
                    process = subprocess.run(
                        [str(executable), str(runner), provider_id, str(request_file), str(result_file)],
                        cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1800, check=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise ComputeRemoteError(
                        code=ComputeErrorCode.TIMEOUT, message=f"{provider_id} batch timed out.",
                        stage=stage, retryable=True,
                    ) from exc
                if process.returncode:
                    log.seek(max(0, log.tell() - 8192))
                    model_log = log.read().decode("utf-8", errors="replace")
                    oom = "out of memory" in model_log.lower()
                    unavailable = "ModuleNotFoundError" in model_log or "FileNotFoundError" in model_log
                    code = ComputeErrorCode.EXECUTION_ERROR
                    if oom:
                        code = ComputeErrorCode.OOM_ERROR
                    elif unavailable:
                        code = ComputeErrorCode.MODEL_NOT_AVAILABLE
                    raise ComputeRemoteError(
                        code=code,
                        message=f"{provider_id} process failed (exit {process.returncode}). "
                        "Check the Worker model installation and configuration.",
                        stage=stage, retryable=oom,
                    )
    finally:
        manager.evict(key=lease_key)
    return json.loads(result_file.read_text(encoding="utf-8"))
