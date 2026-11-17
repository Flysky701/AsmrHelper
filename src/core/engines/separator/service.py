"""Core separator engine runtime with transparent remote GPU worker delegation."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from .registry import get_separator_registry

if TYPE_CHECKING:
    import httpx
    from packages.gpu_worker.client import ComputeClient


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class SeparatorEngineRuntime:
    """Execute source separation locally via Demucs or remotely via GPU worker."""

    def __init__(
        self,
        registry=None,
        *,
        remote_worker_url: str | None = None,
        remote_worker_token: str | None = None,
        remote_worker_timeout: float = 600.0,
        remote_client: ComputeClient | None = None,
        remote_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._registry = registry or get_separator_registry()
        self._remote_worker_url = _clean_str(remote_worker_url)
        self._remote_worker_token = _clean_str(remote_worker_token)
        self._remote_worker_timeout = float(remote_worker_timeout)
        self._remote_client = remote_client
        self._remote_transport = remote_transport

    def _resolve_remote_config(
        self,
        *,
        provider_options: Mapping[str, Any] | None = None,
        common_options: Mapping[str, Any] | None = None,
        remote_worker_url: str | None = None,
        remote_worker_token: str | None = None,
        remote_worker_timeout: float | None = None,
    ) -> tuple[str | None, str | None, float, Any]:
        prov_opts = dict(provider_options or {})
        comm_opts = dict(common_options or {})

        url = (
            _clean_str(remote_worker_url)
            or _clean_str(prov_opts.get("remote_worker_url"))
            or _clean_str(comm_opts.get("remote_worker_url"))
            or self._remote_worker_url
            or _clean_str(os.environ.get("ASMR_HELPER_REMOTE_WORKER_URL"))
        )
        token = (
            _clean_str(remote_worker_token)
            or _clean_str(prov_opts.get("remote_worker_token"))
            or _clean_str(comm_opts.get("remote_worker_token"))
            or self._remote_worker_token
            or _clean_str(os.environ.get("ASMR_HELPER_REMOTE_WORKER_TOKEN"))
            or _clean_str(os.environ.get("ASMR_WORKER_TOKEN"))
        )
        raw_timeout = (
            remote_worker_timeout
            if remote_worker_timeout is not None
            else (
                prov_opts.get("remote_worker_timeout")
                or comm_opts.get("remote_worker_timeout")
                or _clean_str(os.environ.get("ASMR_HELPER_REMOTE_WORKER_TIMEOUT"))
            )
        )
        timeout = float(raw_timeout) if raw_timeout is not None else self._remote_worker_timeout
        transport = (
            prov_opts.get("remote_transport")
            or comm_opts.get("remote_transport")
            or self._remote_transport
        )
        return url, token, timeout, transport

    def has_remote_worker(
        self,
        *,
        provider_options: Mapping[str, Any] | None = None,
        common_options: Mapping[str, Any] | None = None,
        remote_worker_url: str | None = None,
    ) -> bool:
        if self._remote_client is not None:
            return True
        url, _, _, _ = self._resolve_remote_config(
            provider_options=provider_options,
            common_options=common_options,
            remote_worker_url=remote_worker_url,
        )
        return bool(url)

    @contextmanager
    def _open_remote_client(
        self,
        *,
        provider_options: Mapping[str, Any] | None = None,
        common_options: Mapping[str, Any] | None = None,
        remote_worker_url: str | None = None,
        remote_worker_token: str | None = None,
        remote_worker_timeout: float | None = None,
    ):
        if self._remote_client is not None:
            yield self._remote_client
            return

        from packages.gpu_worker.client import ComputeClient, RemoteHttpTransport

        url, token, timeout, transport = self._resolve_remote_config(
            provider_options=provider_options,
            common_options=common_options,
            remote_worker_url=remote_worker_url,
            remote_worker_token=remote_worker_token,
            remote_worker_timeout=remote_worker_timeout,
        )
        if not url:
            raise ValueError("remote_worker_url is not configured")
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError(f"invalid remote_worker_url: {url!r}")

        client = ComputeClient(
            RemoteHttpTransport(
                base_url=url,
                api_key=token,
                timeout=timeout,
                transport=transport,
            )
        )
        try:
            yield client
        finally:
            client.close()

    def separate(
        self,
        *,
        input_path: str,
        output_dir: str,
        model: str = "htdemucs",
        stems: list[str] | None = None,
        provider_options: Mapping[str, Any] | None = None,
        common_options: Mapping[str, Any] | None = None,
        remote_worker_url: str | None = None,
        remote_worker_token: str | None = None,
        remote_worker_timeout: float | None = None,
    ) -> dict[str, str]:
        source = Path(input_path)
        if not source.exists():
            raise ValueError(f"input file does not exist: {input_path}")

        Path(output_dir).mkdir(parents=True, exist_ok=True)

        if self.has_remote_worker(
            provider_options=provider_options,
            common_options=common_options,
            remote_worker_url=remote_worker_url,
        ):
            from packages.protocol.compute import SeparationRequest
            from packages.protocol.errors import ComputeRemoteError

            effective_stems = list(stems) if stems is not None else ["vocals"]
            request = SeparationRequest(
                input_path=str(source),
                output_dir=str(output_dir),
                model=model or "htdemucs",
                stems=effective_stems,
                output_format="wav",
            )
            try:
                with self._open_remote_client(
                    provider_options=provider_options,
                    common_options=common_options,
                    remote_worker_url=remote_worker_url,
                    remote_worker_token=remote_worker_token,
                    remote_worker_timeout=remote_worker_timeout,
                ) as client:
                    result = client.separate(request)
            except ComputeRemoteError as exc:
                raise RuntimeError(
                    f"remote separation worker failed ({exc.code}): {exc}"
                ) from exc
            return dict(result.stem_paths)

        separator = self._registry.get("demucs", model_name=model)
        return separator.separate(str(source), output_dir, stems=stems)


# Service alias for callers importing `SeparatorEngineService` from `separator.service`.
SeparatorEngineService = SeparatorEngineRuntime

__all__ = ["SeparatorEngineRuntime", "SeparatorEngineService"]
