"""Bounded 3-tier download policy (ModelScope -> HF-Mirror -> HuggingFace) and lightweight HTTP snapshot client."""
from __future__ import annotations

import fnmatch
import hashlib
import json
import logging
import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

PYPI = "https://pypi.org/simple"
TUNA = "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple"
ALIYUN_PYPI = "https://mirrors.aliyun.com/pypi/simple"
HUGGINGFACE = "https://huggingface.co"
HF_MIRROR = "https://hf-mirror.com"
MODELSCOPE = "https://www.modelscope.cn"
DEMUCS_DEFAULT_BASE_URL = "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer"

DOMESTIC_MIRROR_ALIASES = frozenset({
    "modelscope",
    "auto-cn",
    "cn",
    "domestic",
    "https://www.modelscope.cn",
    "https://modelscope.cn",
})
DOMESTIC_REGIONS = frozenset({"cn", "auto-cn", "domestic", "china", "modelscope"})

# Curated ModelScope repository mappings keyed by catalog model id and upstream HF repo id.
CURATED_MODELSCOPE_REPOS: dict[str, str] = {
    # Faster-Whisper CTranslate2 family
    "faster-whisper-tiny": "Systran/faster-whisper-tiny",
    "Systran/faster-whisper-tiny": "Systran/faster-whisper-tiny",
    "faster-whisper-base": "Systran/faster-whisper-base",
    "Systran/faster-whisper-base": "Systran/faster-whisper-base",
    "faster-whisper-small": "Systran/faster-whisper-small",
    "Systran/faster-whisper-small": "Systran/faster-whisper-small",
    "faster-whisper-medium": "Systran/faster-whisper-medium",
    "Systran/faster-whisper-medium": "Systran/faster-whisper-medium",
    "faster-whisper-large-v3": "Systran/faster-whisper-large-v3",
    "Systran/faster-whisper-large-v3": "Systran/faster-whisper-large-v3",
    # Fun-ASR & FSMN-VAD
    "fun-asr-nano-2512": "FunAudioLLM/Fun-ASR-Nano-2512",
    "FunAudioLLM/Fun-ASR-Nano-2512": "FunAudioLLM/Fun-ASR-Nano-2512",
    "fun-asr-mlt-nano-2512": "FunAudioLLM/Fun-ASR-MLT-Nano-2512",
    "FunAudioLLM/Fun-ASR-MLT-Nano-2512": "FunAudioLLM/Fun-ASR-MLT-Nano-2512",
    "fun-asr-fsmn-vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    "funasr/fsmn-vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    # Qwen3-ASR & Forced Aligner
    "qwen3-asr-0.6b": "Qwen/Qwen3-ASR-0.6B",
    "Qwen/Qwen3-ASR-0.6B": "Qwen/Qwen3-ASR-0.6B",
    "qwen3-asr-1.7b": "Qwen/Qwen3-ASR-1.7B",
    "Qwen/Qwen3-ASR-1.7B": "Qwen/Qwen3-ASR-1.7B",
    "qwen3-forced-aligner-0.6b": "Qwen/Qwen3-ForcedAligner-0.6B",
    "Qwen/Qwen3-ForcedAligner-0.6B": "Qwen/Qwen3-ForcedAligner-0.6B",
    # Qwen3-TTS family
    "qwen3-custom-voice": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
    "qwen3-voice-design": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign": "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "qwen3-base": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base": "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
    # VoxCPM2
    "voxcpm2": "OpenBMB/VoxCPM2",
    "openbmb/VoxCPM2": "OpenBMB/VoxCPM2",
    "OpenBMB/VoxCPM2": "OpenBMB/VoxCPM2",
}


@dataclass(frozen=True)
class DownloadSource:
    type: str
    endpoint: str
    repo_id: str
    revision: str = "master"


def transient_network_error(detail: str) -> bool:
    detail = detail.lower()
    # Do not hide dependency conflicts, authentication, TLS, or corrupt files.
    if any(word in detail for word in ("certificate", "sslerror", "401", "403", "hash mismatch")):
        return False
    return any(word in detail for word in (
        "timeout", "timed out", "connection", "connecterror", "network is unreachable",
        "name resolution", "failed to fetch", "urlopen error", "reset by peer",
        "incomplete read", "remote end closed", "temporary failure",
        "429", "500", "502", "503", "504",
    ))


def recoverable_source_error(detail: str) -> bool:
    """Return whether a failed mirror tier may safely fall back to the next source tier."""
    lowered = detail.lower()
    if any(word in lowered for word in ("certificate", "sslerror", "401", "403", "hash mismatch")):
        return False
    return True


def _is_valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def is_domestic_download_mode(mirror: str | None = None) -> bool:
    raw = (mirror or "").strip().lower().rstrip("/")
    if raw in DOMESTIC_MIRROR_ALIASES:
        return True
    if raw:
        return False
    region = os.environ.get("ASMR_HELPER_DOWNLOAD_REGION", "").strip().lower()
    return region in DOMESTIC_REGIONS


def is_custom_mirror_url(mirror: str | None) -> bool:
    if not mirror:
        return False
    raw = mirror.strip()
    normalized = raw.lower().rstrip("/")
    if normalized in DOMESTIC_MIRROR_ALIASES or normalized in {
        "hf-mirror",
        "huggingface",
        HF_MIRROR,
        HUGGINGFACE,
    }:
        return False
    return _is_valid_http_url(raw)


def package_sources() -> list[str]:
    policy = os.environ.get("ASMR_HELPER_PYPI_FALLBACK", "tuna")
    if policy not in {"tuna", "aliyun", "domestic", "none"}:
        raise ValueError("ASMR_HELPER_PYPI_FALLBACK must be tuna, aliyun, domestic, or none")
    if is_domestic_download_mode() or policy == "domestic":
        return [ALIYUN_PYPI, TUNA, PYPI]
    if policy == "aliyun":
        return [ALIYUN_PYPI, TUNA]
    return [PYPI, TUNA] if policy == "tuna" else [PYPI, PYPI]


def _extract_entry_hf_repo(entry_or_repo: Any, explicit_hf_repo: str | None = None) -> str:
    if explicit_hf_repo:
        return explicit_hf_repo
    if isinstance(entry_or_repo, str):
        return entry_or_repo
    meta = getattr(entry_or_repo, "download_sources", None) or []
    for item in meta:
        if isinstance(item, dict) and item.get("type") in {"huggingface", "hf-mirror"} and item.get("repo_id"):
            return str(item["repo_id"])
    upstream = getattr(entry_or_repo, "upstream_name", None)
    if upstream and "/" in str(upstream):
        return str(upstream)
    model_id = str(getattr(entry_or_repo, "id", "") or "")
    if model_id in CURATED_MODELSCOPE_REPOS:
        return CURATED_MODELSCOPE_REPOS[model_id]
    return str(upstream or model_id)


def resolve_modelscope_repo(
    entry_or_repo: Any,
    download_sources_meta: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str]:
    """Return (modelscope_repo_id, revision) if the model supports ModelScope, else (None, 'master')."""
    meta = download_sources_meta
    if meta is None and not isinstance(entry_or_repo, str):
        meta = getattr(entry_or_repo, "download_sources", None)
    if meta:
        for item in meta:
            if isinstance(item, dict) and item.get("type") == "modelscope" and item.get("repo_id"):
                return str(item["repo_id"]), str(item.get("revision") or "master")
        # Model explicitly declared download_sources without a modelscope entry (e.g. anime-whisper).
        return None, "master"

    if isinstance(entry_or_repo, str):
        repo = CURATED_MODELSCOPE_REPOS.get(entry_or_repo)
        return repo, "master"

    model_id = str(getattr(entry_or_repo, "id", "") or "")
    upstream = str(getattr(entry_or_repo, "upstream_name", "") or "")
    repo = CURATED_MODELSCOPE_REPOS.get(model_id) or CURATED_MODELSCOPE_REPOS.get(upstream)
    return repo, "master"


def _hf_fallback_policy() -> str:
    policy = os.environ.get("ASMR_HELPER_HF_FALLBACK", "hf-mirror")
    if policy not in {"hf-mirror", "none"}:
        raise ValueError("ASMR_HELPER_HF_FALLBACK must be hf-mirror or none")
    return policy


def resolve_download_sources(
    entry_or_repo: Any,
    mirror: str | None = None,
    *,
    hf_repo: str | None = None,
    download_sources_meta: list[dict[str, Any]] | None = None,
) -> list[DownloadSource]:
    """Resolve ordered download sources according to mirror / region policy.

    - Explicit custom URLs (e.g. ``https://custom.mirror``) are preserved verbatim.
    - Domestic mode (``mirror="modelscope"``, ``mirror="auto-cn"``, or
      ``ASMR_HELPER_DOWNLOAD_REGION=cn``) resolves ``ModelScope -> HF-Mirror -> HuggingFace``
      (skipping ModelScope when a model has no ModelScope repository).
    - Standard HuggingFace / HF-Mirror endpoints respect ``ASMR_HELPER_HF_FALLBACK``.
    """
    policy = _hf_fallback_policy()
    resolved_hf_repo = _extract_entry_hf_repo(entry_or_repo, explicit_hf_repo=hf_repo)
    ms_repo, ms_revision = resolve_modelscope_repo(
        entry_or_repo,
        download_sources_meta=download_sources_meta,
    )

    raw_mirror = (mirror or "").strip()
    if is_domestic_download_mode(raw_mirror):
        sources: list[DownloadSource] = []
        if ms_repo:
            ms_endpoint = MODELSCOPE
            meta = download_sources_meta
            if meta is None and not isinstance(entry_or_repo, str):
                meta = getattr(entry_or_repo, "download_sources", None)
            for item in meta or []:
                if isinstance(item, dict) and item.get("type") == "modelscope" and item.get("endpoint"):
                    ms_endpoint = str(item["endpoint"]).rstrip("/")
                    break
            sources.append(
                DownloadSource(
                    type="modelscope",
                    endpoint=ms_endpoint,
                    repo_id=ms_repo,
                    revision=ms_revision,
                )
            )
        sources.append(DownloadSource(type="hf-mirror", endpoint=HF_MIRROR, repo_id=resolved_hf_repo))
        if policy == "hf-mirror":
            sources.append(DownloadSource(type="huggingface", endpoint=HUGGINGFACE, repo_id=resolved_hf_repo))
        return sources

    effective = raw_mirror or os.environ.get("HF_ENDPOINT", "").strip()
    if not effective:
        primary = DownloadSource(type="huggingface", endpoint=HUGGINGFACE, repo_id=resolved_hf_repo)
        if policy == "hf-mirror":
            return [
                primary,
                DownloadSource(type="hf-mirror", endpoint=HF_MIRROR, repo_id=resolved_hf_repo),
            ]
        return [primary]

    normalized = effective.lower().rstrip("/")
    if normalized in {"hf-mirror", HF_MIRROR}:
        first = DownloadSource(type="hf-mirror", endpoint=HF_MIRROR, repo_id=resolved_hf_repo)
        if policy == "hf-mirror":
            return [
                first,
                DownloadSource(type="huggingface", endpoint=HUGGINGFACE, repo_id=resolved_hf_repo),
            ]
        return [first]

    if normalized in {"huggingface", HUGGINGFACE}:
        first = DownloadSource(type="huggingface", endpoint=HUGGINGFACE, repo_id=resolved_hf_repo)
        if policy == "hf-mirror":
            return [
                first,
                DownloadSource(type="hf-mirror", endpoint=HF_MIRROR, repo_id=resolved_hf_repo),
            ]
        return [first]

    if _is_valid_http_url(effective):
        # Preserve explicit custom mirror URLs verbatim.
        return [DownloadSource(type="custom", endpoint=effective, repo_id=resolved_hf_repo)]

    raise ValueError(
        f"Unsupported mirror source {effective!r}; expected modelscope, auto-cn, "
        f"{HF_MIRROR}, {HUGGINGFACE}, or an explicit http(s) mirror URL"
    )


def model_sources(mirror: str | None, repo: str | None = None) -> list[str]:
    """Return ordered endpoint URLs for model downloads (preserving custom URLs verbatim)."""
    policy = _hf_fallback_policy()
    raw_mirror = (mirror or "").strip()
    if is_domestic_download_mode(raw_mirror):
        urls: list[str] = []
        if repo is None:
            urls.append(MODELSCOPE)
        else:
            ms_repo, _ = resolve_modelscope_repo(repo)
            if ms_repo:
                urls.append(MODELSCOPE)
        urls.append(HF_MIRROR)
        if policy == "hf-mirror":
            urls.append(HUGGINGFACE)
        return urls

    effective = raw_mirror or os.environ.get("HF_ENDPOINT", "").strip()
    if not effective:
        return [HUGGINGFACE, HF_MIRROR] if policy == "hf-mirror" else [HUGGINGFACE]

    normalized = effective.lower().rstrip("/")
    if normalized in {"hf-mirror", HF_MIRROR}:
        return [HF_MIRROR, HUGGINGFACE] if policy == "hf-mirror" else [HF_MIRROR]
    if normalized in {"huggingface", HUGGINGFACE}:
        return [HUGGINGFACE, HF_MIRROR] if policy == "hf-mirror" else [HUGGINGFACE]
    if _is_valid_http_url(effective):
        return [effective]

    raise ValueError(
        f"Unsupported mirror source {effective!r}; expected modelscope, auto-cn, "
        f"{HF_MIRROR}, {HUGGINGFACE}, or an explicit http(s) mirror URL"
    )


def resolve_demucs_base_urls(
    mirror: str | None = None,
    *,
    base_url: str | None = None,
    download_sources_meta: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Resolve ordered HTTP base URLs for Demucs weight checkpoints."""
    urls: list[str] = []
    if base_url and base_url.strip():
        candidate = base_url.strip().rstrip("/")
        if not _is_valid_http_url(candidate):
            raise ValueError(f"Invalid Demucs mirror base_url: {base_url!r}")
        urls.append(candidate)

    if is_custom_mirror_url(mirror):
        assert mirror is not None
        urls.append(mirror.strip().rstrip("/"))

    env_override = os.environ.get("ASMR_HELPER_DEMUCS_MIRROR", "").strip()
    if env_override:
        candidate = env_override.rstrip("/")
        if not _is_valid_http_url(candidate):
            raise ValueError(f"Invalid ASMR_HELPER_DEMUCS_MIRROR: {env_override!r}")
        if candidate not in urls:
            urls.append(candidate)

    for item in download_sources_meta or []:
        if isinstance(item, dict) and item.get("type") == "http":
            endpoint = str(item.get("endpoint") or item.get("base_url") or "").strip().rstrip("/")
            if endpoint and _is_valid_http_url(endpoint) and endpoint not in urls:
                urls.append(endpoint)

    if DEMUCS_DEFAULT_BASE_URL not in urls:
        urls.append(DEMUCS_DEFAULT_BASE_URL)
    return urls


def _validate_safe_rel_path(rel_path: str) -> PurePosixPath:
    normalized = rel_path.replace("\\", "/").lstrip("/")
    posix = PurePosixPath(normalized)
    if not normalized or posix.is_absolute() or ".." in posix.parts:
        raise ValueError(f"Unsafe relative file path in repository manifest: {rel_path!r}")
    return posix


def fetch_modelscope_files(
    repo_id: str,
    *,
    revision: str = "master",
    endpoint: str = MODELSCOPE,
    timeout: float = 30.0,
    opener: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """Fetch repository file metadata via ModelScope's public HTTP JSON API (no SDK needed)."""
    if not repo_id or "/" not in repo_id:
        raise ValueError(f"Invalid ModelScope repo_id: {repo_id!r}")
    http_open = opener or urlopen
    base = endpoint.rstrip("/")
    rev_q = quote(revision, safe="")
    url = f"{base}/api/v1/models/{repo_id}/repo/files?Revision={rev_q}&Recursive=true"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "asmr-helper/2.0",
        },
    )
    with http_open(request, timeout=timeout) as response:
        raw = response.read()
    payload = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw))
    code = payload.get("Code")
    if code not in (None, 200) or payload.get("Success", True) is False:
        raise RuntimeError(
            f"ModelScope API error for {repo_id} (Code={code}): {payload.get('Message', 'unknown error')}"
        )

    raw_files = (payload.get("Data") or {}).get("Files")
    if raw_files is None:
        raw_files = payload.get("files") or []

    files: list[dict[str, Any]] = []
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        if item.get("Type", "blob") != "blob":
            continue
        raw_path = str(item.get("Path") or item.get("Name") or "").strip()
        if not raw_path:
            continue
        posix_path = _validate_safe_rel_path(raw_path)
        rel_str = posix_path.as_posix()
        if rel_str == ".git" or rel_str.startswith(".git/") or rel_str == ".gitattributes":
            continue
        raw_size = item.get("Size")
        size = int(raw_size) if isinstance(raw_size, int) and not isinstance(raw_size, bool) else None
        sha256 = str(item.get("Sha256") or "").strip().lower() or None
        files.append({
            "path": rel_str,
            "size": size,
            "sha256": sha256,
            "revision": str(item.get("Revision") or revision),
        })

    if not files:
        raise RuntimeError(f"ModelScope repository {repo_id} returned no downloadable files")
    return files


def _matches_allow_patterns(rel_path: str, allow_patterns: list[str] | None) -> bool:
    if not allow_patterns:
        return True
    basename = PurePosixPath(rel_path).name
    return any(
        fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(basename, pattern)
        for pattern in allow_patterns
    )


def _file_already_verified(path: Path, expected_size: int | None, expected_sha256: str | None) -> bool:
    if not path.is_file():
        return False
    actual_size = path.stat().st_size
    if actual_size == 0:
        return False
    if expected_size is not None and actual_size != expected_size:
        return False
    if expected_sha256:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest().lower() != expected_sha256.lower():
            return False
    return True


def download_modelscope_snapshot(
    repo_id: str,
    local_dir: str | Path,
    *,
    revision: str = "master",
    endpoint: str = MODELSCOPE,
    allow_patterns: list[str] | None = None,
    required_files: list[str] | None = None,
    required_dirs: list[str] | None = None,
    timeout: float = 120.0,
    on_progress: Callable[[float, str], None] | None = None,
    opener: Callable[..., Any] | None = None,
) -> Path:
    """Download and SHA256-verify a repository snapshot from ModelScope over plain HTTP."""
    http_open = opener or urlopen
    target_dir = Path(local_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    all_files = fetch_modelscope_files(
        repo_id,
        revision=revision,
        endpoint=endpoint,
        timeout=min(timeout, 30.0),
        opener=http_open,
    )
    selected = [item for item in all_files if _matches_allow_patterns(item["path"], allow_patterns)]
    if not selected:
        raise RuntimeError(f"ModelScope repository {repo_id} matched no files for {allow_patterns!r}")

    available_paths = {item["path"] for item in selected}
    if required_files:
        normalized_req = [req.replace("\\", "/").strip("/") for req in required_files if req]
        missing = [req for req in normalized_req if req not in available_paths]
        if missing:
            raise RuntimeError(
                f"ModelScope repository {repo_id} missing required files: {', '.join(missing)}"
            )
    if required_dirs:
        normalized_dirs = [d.replace("\\", "/").strip("/") for d in required_dirs if d]
        missing_dirs = [
            d for d in normalized_dirs
            if not any(path.startswith(f"{d}/") for path in available_paths)
        ]
        if missing_dirs:
            raise RuntimeError(
                f"ModelScope repository {repo_id} missing required directories: {', '.join(missing_dirs)}"
            )

    total_bytes = sum(max(int(item["size"] or 0), 0) for item in selected)
    completed_bytes = 0
    base = endpoint.rstrip("/")
    rev_q = quote(revision, safe="")

    for idx, item in enumerate(selected):
        posix_path = _validate_safe_rel_path(item["path"])
        dest = (target_dir / Path(*posix_path.parts)).resolve()
        if not dest.is_relative_to(target_dir):
            raise ValueError(f"Refusing path outside target_dir: {item['path']!r}")

        expected_size: int | None = item["size"]
        expected_sha256: str | None = item["sha256"]
        if _file_already_verified(dest, expected_size, expected_sha256):
            completed_bytes += expected_size or dest.stat().st_size
            if on_progress:
                frac = (completed_bytes / total_bytes) if total_bytes > 0 else ((idx + 1) / len(selected))
                on_progress(min(frac, 0.99), f"verified existing {item['path']}")
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + ".partial")
        quoted_rel = "/".join(quote(part, safe="") for part in posix_path.parts)
        file_url = f"{base}/models/{repo_id}/resolve/{rev_q}/{quoted_rel}"
        request = Request(file_url, headers={"User-Agent": "asmr-helper/2.0"})

        if on_progress:
            frac = (completed_bytes / total_bytes) if total_bytes > 0 else (idx / len(selected))
            on_progress(min(frac, 0.99), f"downloading {item['path']} from ModelScope")

        digest = hashlib.sha256()
        written = 0
        try:
            with http_open(request, timeout=timeout) as response, partial.open("wb") as out_stream:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out_stream.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if on_progress and total_bytes > 0:
                        frac = min((completed_bytes + written) / total_bytes, 0.99)
                        on_progress(frac, f"downloading {item['path']} ({(completed_bytes + written) / (1024 * 1024):.1f} MB)")

            if expected_size is not None and written != expected_size:
                raise RuntimeError(
                    f"model file size mismatch for {item['path']}: expected {expected_size}, got {written}"
                )
            if expected_sha256 and digest.hexdigest().lower() != expected_sha256.lower():
                raise RuntimeError(f"model hash mismatch: {item['path']}")
            partial.replace(dest)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

        completed_bytes += written

    if required_files:
        for req in required_files:
            req_path = target_dir / Path(*_validate_safe_rel_path(req).parts)
            if not req_path.is_file() or req_path.stat().st_size == 0:
                raise RuntimeError(f"ModelScope snapshot missing required file after download: {req}")
    if required_dirs:
        for req_dir in required_dirs:
            dir_path = target_dir / Path(*_validate_safe_rel_path(req_dir).parts)
            if not dir_path.is_dir():
                raise RuntimeError(f"ModelScope snapshot missing required directory after download: {req_dir}")

    if on_progress:
        on_progress(1.0, f"ModelScope download complete ({repo_id})")
    logger.info("ModelScope snapshot verified repo=%s files=%d bytes=%d", repo_id, len(selected), completed_bytes)
    return target_dir


def locked_requirements(lockfile: Path, roots: list[str], output: Path) -> Path:
    """Reuse the shipped lock's exact versions and PyPI wheel hashes on every source."""
    from packaging.markers import Marker

    with lockfile.open("rb") as stream:
        lock = tomllib.load(stream)
    packages: dict[str, list[dict[str, Any]]] = {}
    for package in lock["package"]:
        if package.get("version"):
            packages.setdefault(package["name"], []).append(package)
    selected: dict[str, dict[str, Any]] = {}
    pending = list(roots)
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        candidates = packages.get(name, [])
        if len(candidates) != 1:
            raise RuntimeError(f"FasterWhisper lock must identify exactly one version of {name}")
        package = candidates[0]
        if package.get("source") != {"registry": PYPI}:
            raise RuntimeError(f"FasterWhisper package is not locked to official PyPI: {name}")
        selected[name] = package
        for dependency in package.get("dependencies", []):
            marker = dependency.get("marker")
            if not marker or Marker(marker).evaluate({"extra": ""}):
                pending.append(dependency["name"])
    lines = []
    for name, package in sorted(selected.items()):
        hashes = sorted({wheel["hash"] for wheel in package.get("wheels", [])})
        if not hashes or any(not value.startswith("sha256:") for value in hashes):
            raise RuntimeError(f"FasterWhisper lock has no trusted wheel hashes: {name}")
        lines.append(f"{name}=={package['version']} " + " ".join(f"--hash={value}" for value in hashes))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def install_locked_packages(installer: dict, requirements: Path, *, env: dict, cwd: Path) -> None:
    env = env.copy()
    # Scope changes to this child. Keep the user's proxy and all cache paths.
    for key in list(env):
        if key.startswith(("UV_INDEX", "UV_EXTRA_INDEX", "UV_DEFAULT_INDEX", "PIP_INDEX", "PIP_EXTRA_INDEX")):
            env.pop(key)
    for key in ("PIP_TRUSTED_HOST", "UV_INSECURE_HOST", "PIP_FIND_LINKS", "UV_FIND_LINKS"):
        env.pop(key, None)
    env.update(UV_HTTP_TIMEOUT="30", UV_HTTP_RETRIES="1", PIP_CONFIG_FILE=os.devnull)
    sources = package_sources()
    for attempt, source in enumerate(sources, 1):
        cmd = installer["packages_cmd"]([])
        uv = len(cmd) > 1 and cmd[1] == "pip"
        cmd.extend(["--require-hashes", "--only-binary", ":all:", "-r", str(requirements)])
        cmd.extend(["--no-config", "--default-index", source] if uv else
                   ["--index-url", source, "--timeout", "30", "--retries", "1"])
        logger.info("FasterWhisper dependencies source=%s attempt=%s/%s locked_hashes=true", source, attempt, len(sources))
        try:
            result = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True,
                                    text=True, encoding="utf-8", errors="replace", timeout=600, check=False)
            if result.returncode == 0:
                logger.info("FasterWhisper dependency install complete: %s", result.stderr.strip())
                return
            detail = (result.stderr or result.stdout or "unknown error")[-2000:]
        except subprocess.TimeoutExpired:
            detail = "dependency download timed out after 600 seconds"
        if attempt == len(sources) or not transient_network_error(detail):
            raise RuntimeError(f"FasterWhisper dependency install failed source={source} attempt={attempt}: {detail}")
        logger.warning("FasterWhisper dependency network failure; retaining cache and switching source: %s", detail)
