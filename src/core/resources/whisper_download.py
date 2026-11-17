"""Download verified CTranslate2 weights through 3-tier source fallback (ModelScope -> HF-Mirror -> HuggingFace)."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from .download_sources import (
    HF_MIRROR,
    HUGGINGFACE,
    download_modelscope_snapshot,
    recoverable_source_error,
    resolve_download_sources,
    transient_network_error,
)

logger = logging.getLogger(__name__)

WHISPER_ALLOWED_FILES = frozenset({
    "model.bin",
    "config.json",
    "tokenizer.json",
    "vocabulary.txt",
    "vocabulary.json",
    "preprocessor_config.json",
})
WHISPER_REQUIRED_FILES = frozenset({"model.bin", "config.json", "tokenizer.json"})


def verify_files(target: Path, manifest: dict) -> None:
    for item in manifest["files"]:
        path = target / item["name"]
        if not path.is_file() or path.stat().st_size != item["size"]:
            raise RuntimeError(f"model file missing or size mismatch: {item['name']}")
        digest = hashlib.new(item["algorithm"])
        if item["algorithm"] == "sha1":
            digest.update(f"blob {item['size']}\0".encode())
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != item["digest"]:
            raise RuntimeError(f"model hash mismatch: {item['name']}")


def official_manifest(
    repo: str,
    target: Path,
    *,
    endpoints: list[str] | None = None,
) -> dict:
    from huggingface_hub import HfApi

    cache = target / ".cache" / "asmr-official-manifest.json"
    candidate_endpoints = list(dict.fromkeys(endpoints or [HUGGINGFACE, HF_MIRROR]))
    for attempt, endpoint in enumerate(candidate_endpoints, 1):
        try:
            info = HfApi(endpoint=endpoint, token=False).model_info(
                repo, files_metadata=True, timeout=15
            )
            files = []
            for item in info.siblings:
                if item.rfilename not in WHISPER_ALLOWED_FILES:
                    continue
                lfs = item.lfs
                files.append({
                    "name": item.rfilename,
                    "size": item.size,
                    "algorithm": "sha256" if lfs else "sha1",
                    "digest": lfs.sha256 if lfs else item.blob_id,
                })
            manifest = {"repo": repo, "revision": info.sha, "files": files}
            if not WHISPER_REQUIRED_FILES <= {item["name"] for item in files}:
                raise RuntimeError("official model metadata lacks required files")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            return manifest
        except Exception as exc:
            if not transient_network_error(str(exc)):
                raise
            logger.warning(
                "model metadata network failure endpoint=%s attempt=%s/%s: %s",
                endpoint,
                attempt,
                len(candidate_endpoints),
                type(exc).__name__,
            )
    if cache.is_file():
        manifest = json.loads(cache.read_text(encoding="utf-8"))
        if manifest.get("repo") == repo:
            logger.warning("using previously cached official revision=%s", manifest["revision"])
            return manifest
    raise RuntimeError("official model metadata unavailable; cache retained, fallback cannot be verified")


def download(
    repo: str,
    target: str,
    mirror: str | None = None,
    *,
    modelscope_repo: str | None = None,
) -> None:
    meta = [{"type": "modelscope", "repo_id": modelscope_repo}] if modelscope_repo else None
    sources = resolve_download_sources(repo, mirror=mirror, download_sources_meta=meta)
    target_path = Path(target)
    manifest: dict | None = None

    for attempt, source in enumerate(sources, 1):
        logger.info(
            "FasterWhisper model source=%s (%s) attempt=%s/%s repo=%s",
            source.endpoint,
            source.type,
            attempt,
            len(sources),
            source.repo_id,
        )
        try:
            if source.type == "modelscope":
                download_modelscope_snapshot(
                    source.repo_id,
                    target_path,
                    revision=source.revision,
                    endpoint=source.endpoint,
                    allow_patterns=sorted(WHISPER_ALLOWED_FILES),
                    required_files=sorted(WHISPER_REQUIRED_FILES),
                )
                return

            from huggingface_hub import snapshot_download

            if manifest is None:
                manifest_endpoints = (
                    [source.endpoint, HUGGINGFACE]
                    if source.type == "custom"
                    else [HF_MIRROR, HUGGINGFACE]
                    if source.endpoint == HF_MIRROR
                    else [HUGGINGFACE, HF_MIRROR]
                )
                manifest = official_manifest(
                    source.repo_id,
                    target_path,
                    endpoints=manifest_endpoints,
                )

            # Do not execute repository code or send cached HF credentials to a mirror.
            snapshot_download(
                source.repo_id,
                revision=manifest["revision"],
                endpoint=source.endpoint,
                local_dir=target,
                allow_patterns=[item["name"] for item in manifest["files"]],
                max_workers=1,
                token=False,
            )
            verify_files(target_path, manifest)
            logger.info(
                "FasterWhisper weights verified bytes=%s revision=%s",
                sum(item["size"] for item in manifest["files"]),
                manifest["revision"],
            )
            return
        except Exception as exc:
            if attempt == len(sources) or not recoverable_source_error(str(exc)):
                raise RuntimeError(
                    f"FasterWhisper model download failed source={source.endpoint} attempt={attempt}: {exc}"
                ) from exc
            logger.warning(
                "model download failure on %s (%s); falling back to %s",
                source.endpoint,
                type(exc).__name__,
                sources[attempt].endpoint,
            )
            time.sleep(1)
