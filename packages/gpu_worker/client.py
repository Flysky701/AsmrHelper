"""Unified ComputeClient with LocalSubprocessTransport and RemoteHttpTransport.

Both transports expose the exact same typed `packages.protocol` interface:
- `LocalSubprocessTransport` invokes `python -m packages.gpu_worker.cli --once <job.json>`
  directly against local filesystem paths with zero network/encoding overhead.
- `RemoteHttpTransport` communicates over HTTP/HTTPS (e.g., Cloudflare Quick Tunnel to
  Colab T4/L4), automatically transcoding local input audio to lossless `.flac` via
  `soundfile` (`format="FLAC"`) before upload (~60% smaller than WAV) and writing
  returned audio payloads to the caller's target local paths.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Protocol

import httpx

from packages.protocol.compute import (
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
    WorkerCapabilities,
)
from packages.protocol.errors import ComputeErrorCode, ComputeErrorPayload, ComputeRemoteError

from .handlers import (
    encode_audio_file_bytes,
    materialize_audio_bytes_to_path,
    write_segments_srt,
)


def _default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _safe_stem_prefix(name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in " _-()" else "_" for c in Path(name).stem)
    return cleaned.strip() or "audio"


class ComputeTransport(Protocol):
    """Transport interface implemented by local subprocess and remote HTTP adapters."""

    def capabilities(self) -> WorkerCapabilities: ...

    def evict(
        self, family: str | None = None, *, key: str | None = None
    ) -> LeaseEvictResult: ...

    def separate(self, request: SeparationRequest) -> SeparationResult: ...

    def asr(self, request: AsrRequest) -> AsrResult: ...

    def align(self, request: AlignmentRequest) -> AlignmentResult: ...

    def tts_batch(self, request: TtsBatchRequest) -> TtsBatchResult: ...

    def close(self) -> None: ...


class LocalSubprocessTransport:
    """Executes compute jobs locally via `python -m packages.gpu_worker.cli --once <job.json>`."""

    def __init__(
        self,
        *,
        python_executable: str | Path | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 1800.0,
    ) -> None:
        self.python_executable = str(python_executable or sys.executable)
        self.cwd = Path(cwd or _default_repo_root()).resolve()
        self._extra_env = dict(env or {})
        self.timeout = float(timeout)

    def _build_env(self) -> dict[str, str]:
        merged = dict(os.environ)
        merged.update(self._extra_env)
        existing_pp = merged.get("PYTHONPATH", "")
        repo_str = str(self.cwd)
        parts = [p for p in existing_pp.split(os.pathsep) if p]
        if repo_str not in parts:
            parts.insert(0, repo_str)
        merged["PYTHONPATH"] = os.pathsep.join(parts)
        return merged

    def _run_once(self, task: str, request_dict: dict[str, Any]) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="gpu-local-once-") as tmp:
            tmp_dir = Path(tmp)
            job_path = tmp_dir / "job.json"
            resp_path = tmp_dir / "response.json"
            job_payload = {
                "task": task,
                "request": request_dict,
                "response_path": str(resp_path),
            }
            job_path.write_text(
                json.dumps(job_payload, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                proc = subprocess.run(
                    [
                        self.python_executable,
                        "-m",
                        "packages.gpu_worker.cli",
                        "--once",
                        str(job_path),
                    ],
                    cwd=str(self.cwd),
                    env=self._build_env(),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ComputeRemoteError(
                    code=ComputeErrorCode.TIMEOUT,
                    message=f"Local gpu-worker subprocess timed out after {self.timeout}s ({task})",
                    retryable=True,
                    stage=task,
                ) from exc

            if not resp_path.is_file():
                detail = (proc.stderr or proc.stdout or "Subprocess produced no response").strip()
                raise ComputeRemoteError(
                    code=ComputeErrorCode.EXECUTION_ERROR,
                    message=f"Local gpu-worker failed ({task}): {detail[-1500:]}",
                    retryable=False,
                    stage=task,
                )

            envelope = json.loads(resp_path.read_text(encoding="utf-8"))
            if not envelope.get("ok"):
                err_raw = envelope.get("error") or {}
                payload = ComputeErrorPayload(
                    code=str(err_raw.get("code") or ComputeErrorCode.EXECUTION_ERROR),
                    message=str(err_raw.get("message") or "Local gpu-worker execution failed"),
                    retryable=bool(err_raw.get("retryable", False)),
                    stage=str(err_raw.get("stage") or task),
                    details=dict(err_raw.get("details") or {}),
                )
                raise ComputeRemoteError(payload)
            return dict(envelope.get("result") or {})

    def capabilities(self) -> WorkerCapabilities:
        data = self._run_once("capabilities", {})
        return WorkerCapabilities.model_validate(data)

    def evict(
        self, family: str | None = None, *, key: str | None = None
    ) -> LeaseEvictResult:
        req = LeaseEvictRequest(family=family, key=key)
        data = self._run_once("evict", req.model_dump())
        return LeaseEvictResult.model_validate(data)

    def separate(self, request: SeparationRequest) -> SeparationResult:
        data = self._run_once("separate", request.model_dump())
        return SeparationResult.model_validate(data)

    def asr(self, request: AsrRequest) -> AsrResult:
        data = self._run_once("asr", request.model_dump())
        return AsrResult.model_validate(data)

    def align(self, request: AlignmentRequest) -> AlignmentResult:
        data = self._run_once("align", request.model_dump())
        return AlignmentResult.model_validate(data)

    def tts_batch(self, request: TtsBatchRequest) -> TtsBatchResult:
        data = self._run_once("tts_batch", request.model_dump())
        return TtsBatchResult.model_validate(data)

    def close(self) -> None:
        return None


class RemoteHttpTransport:
    """HTTP/HTTPS transport with automatic lossless FLAC upload transcoding."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 600.0,
        *,
        http_client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        cleaned_url = base_url.strip().rstrip("/")
        if not cleaned_url:
            raise ValueError("base_url must not be empty")
        self.base_url = cleaned_url
        self.api_key = api_key.strip() if api_key and api_key.strip() else None
        self.timeout = float(timeout)
        self._owns_client = http_client is None

        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if http_client is not None:
            self._client = http_client
            if self.api_key and "Authorization" not in self._client.headers:
                self._client.headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            self._client = httpx.Client(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
                transport=transport,
                follow_redirects=True,
            )

    def _url(self, route: str) -> str:
        if self._client.base_url and str(self._client.base_url).strip():
            return route
        return f"{self.base_url}{route}"

    def _request_json(
        self,
        method: str,
        route: str,
        *,
        stage: str,
        json_body: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        try:
            resp = self._client.request(
                method,
                self._url(route),
                json=json_body,
                data=data,
                files=files,
            )
        except httpx.TimeoutException as exc:
            raise ComputeRemoteError(
                code=ComputeErrorCode.TIMEOUT,
                message=f"Remote GPU worker request timed out ({route}): {exc}",
                retryable=True,
                stage=stage,
            ) from exc
        except httpx.HTTPError as exc:
            raise ComputeRemoteError(
                code=ComputeErrorCode.TRANSPORT_ERROR,
                message=f"Remote GPU worker transport failure ({route}): {exc}",
                retryable=True,
                stage=stage,
            ) from exc

        if resp.status_code >= 400:
            self._raise_remote_http_error(resp, stage=stage)

        try:
            parsed = resp.json()
        except Exception as exc:
            raise ComputeRemoteError(
                code=ComputeErrorCode.TRANSPORT_ERROR,
                message=f"Remote GPU worker returned non-JSON response ({resp.status_code})",
                retryable=True,
                stage=stage,
                status_code=resp.status_code,
            ) from exc
        if not isinstance(parsed, dict):
            raise ComputeRemoteError(
                code=ComputeErrorCode.TRANSPORT_ERROR,
                message="Remote GPU worker returned unexpected JSON payload type",
                retryable=False,
                stage=stage,
                status_code=resp.status_code,
            )
        return parsed

    @staticmethod
    def _raise_remote_http_error(resp: httpx.Response, *, stage: str) -> None:
        try:
            body = resp.json()
        except Exception:
            body = None

        if isinstance(body, dict):
            candidate = body.get("error") if isinstance(body.get("error"), dict) else body
            if "code" in candidate and "message" in candidate:
                payload = ComputeErrorPayload(
                    code=str(candidate["code"]),
                    message=str(candidate["message"]),
                    retryable=bool(candidate.get("retryable", resp.status_code >= 500)),
                    stage=str(candidate.get("stage") or stage),
                    details=dict(candidate.get("details") or {}),
                )
                raise ComputeRemoteError(payload, status_code=resp.status_code)
            detail_msg = str(body.get("detail") or body)
        else:
            detail_msg = resp.text[:500] or f"HTTP {resp.status_code}"

        fallback_code = (
            ComputeErrorCode.AUTH_INVALID
            if resp.status_code in {401, 403}
            else ComputeErrorCode.EXECUTION_ERROR
        )
        raise ComputeRemoteError(
            code=fallback_code,
            message=detail_msg,
            retryable=resp.status_code in {408, 429, 502, 503, 504},
            stage=stage,
            status_code=resp.status_code,
        )

    def _prepare_flac_upload(
        self,
        *,
        input_path: str | None,
        audio_b64: str | None,
        filename_hint: str | None,
        stage: str,
    ) -> tuple[str, bytes]:
        if input_path:
            flac_bytes, _sr, _dur = encode_audio_file_bytes(input_path, "flac", stage=stage)
            flac_name = f"{Path(input_path).stem}.flac"
            return flac_name, flac_bytes

        if audio_b64:
            try:
                raw = base64.b64decode(audio_b64, validate=True)
            except Exception as exc:
                raise ComputeRemoteError(
                    code=ComputeErrorCode.AUDIO_DECODE_ERROR,
                    message=f"Invalid audio_b64 on client request: {exc}",
                    retryable=False,
                    stage=stage,
                ) from exc
            if raw.startswith(b"fLaC"):
                name = Path(filename_hint or "input.flac").with_suffix(".flac").name
                return name, raw
            with tempfile.TemporaryDirectory(prefix="gpu-client-flac-") as tmp:
                src = Path(tmp) / (Path(filename_hint or "input.wav").name)
                src.write_bytes(raw)
                flac_bytes, _sr, _dur = encode_audio_file_bytes(src, "flac", stage=stage)
                return f"{src.stem}.flac", flac_bytes

        raise ComputeRemoteError(
            code=ComputeErrorCode.INVALID_REQUEST,
            message=f"{stage} request requires either input_path or audio_b64",
            retryable=False,
            stage=stage,
        )

    def capabilities(self) -> WorkerCapabilities:
        data = self._request_json("GET", "/v1/capabilities", stage="capabilities")
        return WorkerCapabilities.model_validate(data)

    def evict(
        self, family: str | None = None, *, key: str | None = None
    ) -> LeaseEvictResult:
        req = LeaseEvictRequest(family=family, key=key)
        data = self._request_json(
            "POST",
            "/v1/lease/evict",
            stage="lease",
            json_body=req.model_dump(exclude_none=True),
        )
        return LeaseEvictResult.model_validate(data)

    def asr(self, request: AsrRequest) -> AsrResult:
        flac_name, flac_bytes = self._prepare_flac_upload(
            input_path=request.input_path,
            audio_b64=request.audio_b64,
            filename_hint=request.audio_filename,
            stage="asr",
        )
        wire_opts = request.model_dump(
            exclude={"input_path", "output_path", "audio_b64"},
            exclude_none=True,
        )
        wire_opts["audio_filename"] = flac_name
        raw_res = self._request_json(
            "POST",
            "/v1/asr",
            stage="asr",
            data={"options": json.dumps(wire_opts, ensure_ascii=False)},
            files={"audio": (flac_name, flac_bytes, "audio/flac")},
        )
        result = AsrResult.model_validate(raw_res)
        if request.output_path:
            write_segments_srt(result.segments, request.output_path)
            result.source_path = str(request.output_path)
            result.format = "srt"
        return result

    def separate(self, request: SeparationRequest) -> SeparationResult:
        flac_name, flac_bytes = self._prepare_flac_upload(
            input_path=request.input_path,
            audio_b64=request.audio_b64,
            filename_hint=request.audio_filename,
            stage="separate",
        )
        wire_opts = request.model_dump(
            exclude={"input_path", "output_dir", "audio_b64"},
            exclude_none=True,
        )
        # Always transfer stems as lossless FLAC over the wire to save download bandwidth,
        # then materialize into the caller's requested local format/directory.
        wire_opts["output_format"] = "flac"
        wire_opts["audio_filename"] = flac_name

        raw_res = self._request_json(
            "POST",
            "/v1/separate",
            stage="separate",
            data={"options": json.dumps(wire_opts, ensure_ascii=False)},
            files={"audio": (flac_name, flac_bytes, "audio/flac")},
        )
        result = SeparationResult.model_validate(raw_res)

        if request.output_dir:
            out_dir = Path(request.output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            prefix = _safe_stem_prefix(request.input_path or flac_name)
            ext = ".wav" if request.output_format == "wav" else ".flac"
            stem_paths: dict[str, str] = {}
            for stem_name, b64_payload in result.stem_audio_b64.items():
                decoded_bytes = base64.b64decode(b64_payload)
                target_file = out_dir / f"{prefix}_{stem_name}{ext}"
                materialize_audio_bytes_to_path(decoded_bytes, target_file, stage="separate")
                stem_paths[stem_name] = str(target_file)
            result.stem_paths = stem_paths
            result.output_format = request.output_format
        return result

    def align(self, request: AlignmentRequest) -> AlignmentResult:
        flac_name, flac_bytes = self._prepare_flac_upload(
            input_path=request.input_path,
            audio_b64=request.audio_b64,
            filename_hint=request.audio_filename,
            stage="align",
        )
        wire_opts = request.model_dump(
            exclude={"input_path", "audio_b64"},
            exclude_none=True,
        )
        wire_opts["audio_filename"] = flac_name
        raw_res = self._request_json(
            "POST",
            "/v1/align",
            stage="align",
            data={"options": json.dumps(wire_opts, ensure_ascii=False)},
            files={"audio": (flac_name, flac_bytes, "audio/flac")},
        )
        return AlignmentResult.model_validate(raw_res)

    def tts_batch(self, request: TtsBatchRequest) -> TtsBatchResult:
        files: dict[str, tuple[str, bytes, str]] = {}
        if request.reference_audio_path:
            ref_flac, _sr, _dur = encode_audio_file_bytes(
                request.reference_audio_path, "flac", stage="tts_batch"
            )
            ref_name = f"{Path(request.reference_audio_path).stem}.flac"
            files["reference_audio"] = (ref_name, ref_flac, "audio/flac")

        for ref_id, local_ref in request.references.items():
            ref_flac, _sr, _dur = encode_audio_file_bytes(local_ref, "flac", stage="tts_batch")
            files[f"ref_{ref_id}"] = (f"{ref_id}.flac", ref_flac, "audio/flac")

        wire_req = request.model_copy(deep=True)
        wire_req.reference_audio_path = None
        wire_req.references = {}
        wire_req.output_format = "flac"
        target_paths_by_id: dict[str, str] = {}
        for item in wire_req.items:
            if item.output_path:
                target_paths_by_id[item.item_id] = item.output_path
                item.output_path = None

        wire_json = wire_req.model_dump(exclude_none=True)
        if files:
            raw_res = self._request_json(
                "POST",
                "/v1/tts/batch",
                stage="tts_batch",
                data={"request": json.dumps(wire_json, ensure_ascii=False)},
                files=files,
            )
        else:
            raw_res = self._request_json(
                "POST",
                "/v1/tts/batch",
                stage="tts_batch",
                json_body=wire_json,
            )

        result = TtsBatchResult.model_validate(raw_res)
        for item_res in result.items:
            target_path = target_paths_by_id.get(item_res.item_id)
            if item_res.ok and item_res.audio_b64 and target_path:
                audio_raw = base64.b64decode(item_res.audio_b64)
                materialize_audio_bytes_to_path(audio_raw, target_path, stage="tts_batch")
                item_res.output_path = str(target_path)
        return result

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class ComputeClient:
    """Unified stateless GPU compute client over local subprocess or remote HTTP."""

    def __init__(self, transport: ComputeTransport) -> None:
        self.transport = transport

    @classmethod
    def from_local(
        cls,
        *,
        python_executable: str | Path | None = None,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 1800.0,
    ) -> ComputeClient:
        return cls(
            LocalSubprocessTransport(
                python_executable=python_executable,
                cwd=cwd,
                env=env,
                timeout=timeout,
            )
        )

    @classmethod
    def from_remote(
        cls,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 600.0,
        *,
        http_client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> ComputeClient:
        return cls(
            RemoteHttpTransport(
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
                http_client=http_client,
                transport=transport,
            )
        )

    @classmethod
    def from_env(cls, *, timeout: float = 600.0) -> ComputeClient | None:
        """Create a remote `ComputeClient` when `ASMR_HELPER_REMOTE_WORKER_URL` is set."""
        remote_url = (os.getenv("ASMR_HELPER_REMOTE_WORKER_URL") or "").strip()
        if not remote_url:
            return None
        token = (
            os.getenv("ASMR_HELPER_REMOTE_WORKER_TOKEN")
            or os.getenv("ASMR_WORKER_TOKEN")
            or ""
        ).strip() or None
        return cls.from_remote(base_url=remote_url, api_key=token, timeout=timeout)

    def capabilities(self) -> WorkerCapabilities:
        return self.transport.capabilities()

    def evict(
        self, family: str | None = None, *, key: str | None = None
    ) -> LeaseEvictResult:
        return self.transport.evict(family, key=key)

    def separate(self, request: SeparationRequest) -> SeparationResult:
        return self.transport.separate(request)

    def asr(self, request: AsrRequest) -> AsrResult:
        return self.transport.asr(request)

    def align(self, request: AlignmentRequest) -> AlignmentResult:
        return self.transport.align(request)

    def tts_batch(self, request: TtsBatchRequest) -> TtsBatchResult:
        return self.transport.tts_batch(request)

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> ComputeClient:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()
