"""Download the same verified CTranslate2 weights through bounded source fallback."""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from .download_sources import HUGGINGFACE, model_sources, transient_network_error

logger = logging.getLogger(__name__)


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


def official_manifest(repo: str, target: Path) -> dict:
    from huggingface_hub import HfApi
    cache = target / ".cache" / "asmr-official-manifest.json"
    for attempt in range(2):
        try:
            info = HfApi(endpoint=HUGGINGFACE, token=False).model_info(repo, files_metadata=True, timeout=15)
            files = []
            for item in info.siblings:
                if item.rfilename not in {"model.bin", "config.json", "tokenizer.json", "vocabulary.txt", "vocabulary.json", "preprocessor_config.json"}:
                    continue
                lfs = item.lfs
                files.append({"name": item.rfilename, "size": item.size,
                              "algorithm": "sha256" if lfs else "sha1",
                              "digest": lfs.sha256 if lfs else item.blob_id})
            manifest = {"repo": repo, "revision": info.sha, "files": files}
            required = {"model.bin", "config.json", "tokenizer.json"}
            if not required <= {item["name"] for item in files}:
                raise RuntimeError("official model metadata lacks required files")
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            return manifest
        except Exception as exc:
            if not transient_network_error(str(exc)):
                raise
            logger.warning("official model metadata network failure attempt=%s/2: %s", attempt + 1, type(exc).__name__)
    if cache.is_file():
        manifest = json.loads(cache.read_text(encoding="utf-8"))
        if manifest.get("repo") == repo:
            logger.warning("using previously cached official revision=%s", manifest["revision"])
            return manifest
    raise RuntimeError("official model metadata unavailable; cache retained, fallback cannot be verified")


def download(repo: str, target: str, mirror: str | None = None) -> None:
    from huggingface_hub import snapshot_download
    sources = model_sources(mirror)
    target_path = Path(target)
    manifest = official_manifest(repo, target_path)
    for attempt, source in enumerate(sources, 1):
        logger.info("FasterWhisper model source=%s attempt=%s/%s revision=%s cache retained",
                    source, attempt, len(sources), manifest["revision"])
        try:
            # Do not execute repository code or send cached HF credentials to a mirror.
            snapshot_download(repo, revision=manifest["revision"], endpoint=source,
                              local_dir=target, allow_patterns=[item["name"] for item in manifest["files"]],
                              max_workers=1, token=False)
            verify_files(target_path, manifest)
            logger.info("FasterWhisper weights verified bytes=%s revision=%s",
                        sum(item["size"] for item in manifest["files"]), manifest["revision"])
            return
        except Exception as exc:
            if attempt == len(sources) or not transient_network_error(str(exc)):
                raise RuntimeError(f"FasterWhisper model download failed source={source} attempt={attempt}: {exc}") from exc
            logger.warning("model network failure (%s); resuming on %s", type(exc).__name__, sources[attempt])
            time.sleep(2)
