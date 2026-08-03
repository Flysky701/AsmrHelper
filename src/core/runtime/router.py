from __future__ import annotations

import json
import logging
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT

from .profiles import RuntimeProfileResolver, get_runtime_profile_resolver

logger = logging.getLogger(__name__)


class RuntimeWorkerError(RuntimeError):
    pass


class RuntimeRouter:
    """Run providers with conflicting dependencies in short-lived workers."""

    _ASR_PROFILES = {
        "fun_asr": "fun_asr",
        "qwen3_asr": "qwen_asr",
    }
    _TTS_PROFILES = {"qwen3": "qwen_tts"}

    def __init__(
        self,
        resolver: RuntimeProfileResolver | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.resolver = resolver or get_runtime_profile_resolver()
        self.project_root = (project_root or PROJECT_ROOT).resolve()

    def tts_profile(self, provider: str) -> str | None:
        return self._TTS_PROFILES.get(provider)

    def asr_profile(self, provider: str) -> str | None:
        return self._ASR_PROFILES.get(provider)

    def transcribe_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = dict(payload.get("profile") or {})
        provider = str(profile.get("provider") or "")
        return self._run_worker(
            "asr.transcribe_file",
            payload,
            self.asr_profile(provider),
        )

    def synthesize_text(self, payload: dict[str, Any]) -> str:
        result = self._run_worker("tts.synthesize_text", payload, self.tts_profile(str(payload["profile"]["provider"])))
        return str(result["output_path"])

    def synthesize_segments(self, payload: dict[str, Any]) -> str:
        result = self._run_worker(
            "tts.synthesize_segments",
            payload,
            self.tts_profile(str(payload["profile"]["provider"])),
        )
        return str(result["output_path"])

    def _run_worker(
        self,
        operation: str,
        payload: dict[str, Any],
        profile_id: str | None,
    ) -> dict[str, Any]:
        if not profile_id:
            raise RuntimeWorkerError(f"no isolated runtime profile for operation: {operation}")
        profile = self.resolver.resolve(profile_id)
        if not profile.python_executable.is_file():
            raise RuntimeWorkerError(
                f"runtime environment is not installed: {profile.id}; install the selected model dependencies first"
            )

        exchange_dir = self.project_root / ".tmp" / "runtime-workers"
        exchange_dir.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        request_path = exchange_dir / f"{token}.request.json"
        response_path = exchange_dir / f"{token}.response.json"
        request_path.write_text(
            json.dumps({"operation": operation, "payload": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
        try:
            result = subprocess.run(
                [
                    str(profile.python_executable),
                    "-m",
                    "src.core.runtime.stage_worker",
                    "--request",
                    str(request_path),
                    "--response",
                    str(response_path),
                ],
                cwd=str(self.project_root),
                env=self.resolver.subprocess_env(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,
                check=False,
            )
            if not response_path.is_file():
                detail = (result.stderr or result.stdout or "worker produced no response").strip()[-2000:]
                raise RuntimeWorkerError(f"runtime worker failed ({profile.id}): {detail}")
            response = json.loads(response_path.read_text(encoding="utf-8"))
            if not response.get("success"):
                error = response.get("error") or {}
                message = str(error.get("message") or "runtime worker failed")
                logger.error(
                    "runtime worker %s failed: %s\n%s\nstdout:\n%s\nstderr:\n%s",
                    profile.id,
                    message,
                    error.get("traceback") or "",
                    (result.stdout or "")[-2000:],
                    (result.stderr or "")[-2000:],
                )
                raise RuntimeWorkerError(f"runtime worker failed ({profile.id}): {message}")
            return dict(response.get("result") or {})
        except subprocess.TimeoutExpired as exc:
            raise RuntimeWorkerError(f"runtime worker timed out ({profile.id})") from exc
        finally:
            request_path.unlink(missing_ok=True)
            response_path.unlink(missing_ok=True)


_router: RuntimeRouter | None = None
_lock = threading.Lock()


def get_runtime_router() -> RuntimeRouter:
    global _router
    if _router is None:
        with _lock:
            if _router is None:
                _router = RuntimeRouter()
    return _router
