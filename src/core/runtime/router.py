from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.config import PROJECT_ROOT

from .profiles import RuntimeProfileResolver, get_runtime_profile_resolver

if TYPE_CHECKING:
    import httpx
    from packages.gpu_worker.client import ComputeClient

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
        "faster_whisper": "main",
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

    def remote_capabilities(self, payload: Mapping[str, Any] | None = None):
        """Probe a configured worker without using the inference timeout."""
        if self._remote_client is not None:
            return self._remote_client.capabilities()
        from packages.gpu_worker.client import ComputeClient

        url, token, timeout = self._resolve_remote_config(payload)
        if not url:
            return None
        with ComputeClient.from_remote(url, token, min(timeout, 5.0), transport=self._remote_transport) as client:
            return client.capabilities()

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

    @contextmanager
    def _compute_client(self, payload, profile_id):
        from packages.gpu_worker.client import ComputeClient

        if self.has_remote_worker(payload):
            with self._open_remote_client(payload) as client:
                yield client
            return
        profile = self.resolver.resolve(profile_id)
        if not profile.python_executable.is_file():
            raise RuntimeWorkerError(f"runtime environment is not installed: {profile.id}")
        with ComputeClient.from_local(python_executable=profile.python_executable,
                                      cwd=self.project_root, env=self.resolver.subprocess_env()) as client:
            yield client

    def transcribe_file(self, payload: Mapping[str, Any]) -> dict[str, Any]:
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
            with self._compute_client(payload, self.asr_profile(request.provider)) as client:
                result = client.asr(request)
        except ComputeRemoteError as exc:
            raise RuntimeWorkerError(
                f"runtime worker failed ({exc.code}): {exc}"
            ) from exc
        return result.to_worker_document()

    def align_file(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        from packages.protocol.compute import AlignmentRequest
        from packages.protocol.errors import ComputeRemoteError

        request = AlignmentRequest(
            input_path=str(payload["input_path"]) if payload.get("input_path") else None,
            segments=[dict(seg) for seg in (payload.get("segments") or [])],
            language=str(payload.get("language") or "ja"),
            model=str(payload.get("model") or "qwen3-forced-aligner-0.6b"),
        )
        try:
            with self._compute_client(payload, "qwen_asr") as client:
                result = client.align(request)
        except ComputeRemoteError as exc:
            raise RuntimeWorkerError(
                f"runtime worker failed ({exc.code}): {exc}"
            ) from exc
        return result.to_runtime_dict()

_router: RuntimeRouter | None = None
_lock = threading.Lock()


def get_runtime_router() -> RuntimeRouter:
    global _router
    if _router is None:
        with _lock:
            if _router is None:
                _router = RuntimeRouter()
    return _router
