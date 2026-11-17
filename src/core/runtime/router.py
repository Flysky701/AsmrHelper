from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import json
import logging
import os
import subprocess
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.config import PROJECT_ROOT
from src.workspace_paths import temporary_directory, freeze_directories

from .profiles import RuntimeProfileResolver, get_runtime_profile_resolver

if TYPE_CHECKING:
    import httpx
    from packages.gpu_worker.client import ComputeClient

logger = logging.getLogger(__name__)

_REMOTE_OPTION_KEYS = frozenset({
    "remote_worker_url",
    "remote_worker_token",
    "remote_worker_timeout",
})


class RuntimeWorkerError(RuntimeError):
    pass


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _strip_remote_options(profile: Mapping[str, Any]) -> dict[str, Any]:
    cleaned = {k: v for k, v in profile.items() if k not in _REMOTE_OPTION_KEYS}
    if isinstance(cleaned.get("common_options"), Mapping):
        cleaned["common_options"] = {
            k: v for k, v in cleaned["common_options"].items() if k not in _REMOTE_OPTION_KEYS
        }
    if isinstance(cleaned.get("provider_options"), Mapping):
        cleaned["provider_options"] = {
            k: v for k, v in cleaned["provider_options"].items() if k not in _REMOTE_OPTION_KEYS
        }
    return cleaned


class RuntimeRouter:
    """Run providers with conflicting dependencies in short-lived local or remote workers."""

    _ASR_PROFILES = {
        "fun_asr": "fun_asr",
        "qwen3_asr": "qwen_asr",
        "anime_whisper": "anime_whisper",
    }

    def __init__(
        self,
        resolver: RuntimeProfileResolver | None = None,
        project_root: Path | None = None,
        *,
        remote_worker_url: str | None = None,
        remote_worker_token: str | None = None,
        remote_worker_timeout: float = 600.0,
        remote_client: ComputeClient | None = None,
        remote_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.resolver = resolver or get_runtime_profile_resolver()
        self.project_root = (project_root or PROJECT_ROOT).resolve()
        self._remote_worker_url = _clean_str(remote_worker_url)
        self._remote_worker_token = _clean_str(remote_worker_token)
        self._remote_worker_timeout = float(remote_worker_timeout)
        self._remote_client = remote_client
        self._remote_transport = remote_transport

    def asr_profile(self, provider: str) -> str | None:
        return self._ASR_PROFILES.get(provider)

    def _resolve_remote_config(
        self,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[str | None, str | None, float]:
        data = payload or {}
        profile = data.get("profile") if isinstance(data.get("profile"), Mapping) else {}
        prov_opts = (
            profile.get("provider_options")
            if isinstance(profile.get("provider_options"), Mapping)
            else {}
        )
        common_opts = (
            profile.get("common_options")
            if isinstance(profile.get("common_options"), Mapping)
            else {}
        )

        url = (
            _clean_str(data.get("remote_worker_url"))
            or _clean_str(profile.get("remote_worker_url"))
            or _clean_str(prov_opts.get("remote_worker_url"))
            or _clean_str(common_opts.get("remote_worker_url"))
            or self._remote_worker_url
            or _clean_str(os.getenv("ASMR_HELPER_REMOTE_WORKER_URL"))
        )
        token = (
            _clean_str(data.get("remote_worker_token"))
            or _clean_str(profile.get("remote_worker_token"))
            or _clean_str(prov_opts.get("remote_worker_token"))
            or _clean_str(common_opts.get("remote_worker_token"))
            or self._remote_worker_token
            or _clean_str(os.getenv("ASMR_HELPER_REMOTE_WORKER_TOKEN"))
            or _clean_str(os.getenv("ASMR_WORKER_TOKEN"))
        )

        raw_timeout = (
            data.get("remote_worker_timeout")
            or profile.get("remote_worker_timeout")
            or prov_opts.get("remote_worker_timeout")
            or common_opts.get("remote_worker_timeout")
            or _clean_str(os.getenv("ASMR_HELPER_REMOTE_WORKER_TIMEOUT"))
        )
        timeout = float(raw_timeout) if raw_timeout is not None else self._remote_worker_timeout
        return url, token, timeout

    def has_remote_worker(self, payload: Mapping[str, Any] | None = None) -> bool:
        if self._remote_client is not None:
            return True
        url, _, _ = self._resolve_remote_config(payload)
        return bool(url)

    @contextmanager
    def _open_remote_client(self, payload: Mapping[str, Any]):
        if self._remote_client is not None:
            yield self._remote_client
            return

        from packages.gpu_worker.client import ComputeClient, RemoteHttpTransport

        url, token, timeout = self._resolve_remote_config(payload)
        if not url:
            raise RuntimeWorkerError("remote_worker_url is not configured")

        client = ComputeClient(
            RemoteHttpTransport(
                base_url=url,
                api_key=token,
                timeout=timeout,
                transport=self._remote_transport,
            )
        )
        try:
            yield client
        finally:
            client.close()

    def transcribe_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.has_remote_worker(payload):
            return self._transcribe_remote(payload)

        profile = dict(payload.get("profile") or {})
        provider = str(profile.get("provider") or "")
        return self._run_worker(
            "asr.transcribe_file",
            payload,
            self.asr_profile(provider),
        )

    def align_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.has_remote_worker(payload):
            return self._align_remote(payload)

        return self._run_worker("alignment.align_file", payload, "qwen_asr")

    def _transcribe_remote(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        from packages.protocol.compute import AsrRequest
        from packages.protocol.errors import ComputeRemoteError

        raw_profile = payload.get("profile")
        clean_profile = (
            _strip_remote_options(raw_profile) if isinstance(raw_profile, Mapping) else None
        )
        request = AsrRequest(
            input_path=str(payload["input_path"]) if payload.get("input_path") else None,
            output_path=str(payload["output_path"]) if payload.get("output_path") else None,
            profile=clean_profile,
        )
        try:
            with self._open_remote_client(payload) as client:
                result = client.asr(request)
        except ComputeRemoteError as exc:
            raise RuntimeWorkerError(
                f"remote runtime worker failed ({exc.code}): {exc}"
            ) from exc
        return result.to_worker_document()

    def _align_remote(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        from packages.protocol.compute import AlignmentRequest
        from packages.protocol.errors import ComputeRemoteError

        request = AlignmentRequest(
            input_path=str(payload["input_path"]) if payload.get("input_path") else None,
            segments=[dict(seg) for seg in (payload.get("segments") or [])],
            language=str(payload.get("language") or "ja"),
            model=str(payload.get("model") or "qwen3-forced-aligner-0.6b"),
        )
        try:
            with self._open_remote_client(payload) as client:
                result = client.align(request)
        except ComputeRemoteError as exc:
            raise RuntimeWorkerError(
                f"remote runtime worker failed ({exc.code}): {exc}"
            ) from exc
        return result.to_runtime_dict()

    @freeze_directories
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

        exchange_dir = temporary_directory(project_root=self.project_root) / "runtime-workers"
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
