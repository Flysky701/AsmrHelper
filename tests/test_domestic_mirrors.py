"""Domestic download fallback, file integrity, and offline setup behavior."""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from src.config import APP_ROOT
from src.core.resources import model_assets as assets
from src.core.resources.download_sources import (
    HF_MIRROR,
    HUGGINGFACE,
    MODELSCOPE,
    download_modelscope_snapshot,
    model_sources,
    resolve_download_sources,
)
from src.core.resources.model_catalog import ModelCatalog, ModelEntry
from src.core.resources.model_installer import ModelDownloadError, ModelInstaller


class _MockHttpResponse:
    def __init__(self, body: bytes) -> None:
        self._stream = io.BytesIO(body)

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def __enter__(self) -> _MockHttpResponse:
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_domestic_region_selects_the_configured_mirror_repositories(monkeypatch):
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.delenv("ASMR_HELPER_HF_FALLBACK", raising=False)
    monkeypatch.setenv("ASMR_HELPER_DOWNLOAD_REGION", "cn")
    mirror_arg = None
    catalog = ModelCatalog()
    qwen_tts = catalog.get("qwen3-custom-voice")
    sources = resolve_download_sources(qwen_tts, mirror=mirror_arg)
    assert [(s.type, s.endpoint, s.repo_id) for s in sources] == [
        ("modelscope", MODELSCOPE, "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
        ("hf-mirror", HF_MIRROR, "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
        ("huggingface", HUGGINGFACE, "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"),
    ]

    fsmn_vad = catalog.get("fun-asr-fsmn-vad")
    vad_sources = resolve_download_sources(fsmn_vad, mirror=mirror_arg)
    assert [(s.type, s.endpoint, s.repo_id) for s in vad_sources] == [
        ("modelscope", MODELSCOPE, "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"),
        ("hf-mirror", HF_MIRROR, "funasr/fsmn-vad"),
        ("huggingface", HUGGINGFACE, "funasr/fsmn-vad"),
    ]

    assert model_sources(mirror_arg, repo="Systran/faster-whisper-base") == [
        MODELSCOPE,
        HF_MIRROR,
        HUGGINGFACE,
    ]


def test_hf_only_model_skips_modelscope_and_falls_back_cleanly(monkeypatch):
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.delenv("ASMR_HELPER_DOWNLOAD_REGION", raising=False)

    anime = ModelCatalog().get("anime-whisper")
    sources = resolve_download_sources(anime, mirror="auto-cn")
    assert [(s.type, s.endpoint, s.repo_id) for s in sources] == [
        ("hf-mirror", HF_MIRROR, "litagin/anime-whisper"),
        ("huggingface", HUGGINGFACE, "litagin/anime-whisper"),
    ]


def test_installer_with_progress_automatic_three_tier_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(assets, "sources", list)
    monkeypatch.setattr(ModelEntry, "resolved_install_root", lambda _self: tmp_path / "models")
    monkeypatch.setattr("src.core.resources.model_installer.time.sleep", lambda _s: None)

    entry = ModelCatalog().get("voxcpm2")
    installer = ModelInstaller(project_root=tmp_path)
    attempted_tiers: list[tuple[str, str | None]] = []
    progress_messages: list[str] = []

    def fake_run(cmd, env, timeout, on_progress, **kwargs):
        script = cmd[-1]
        if "download_modelscope_snapshot" in script:
            attempted_tiers.append(("modelscope", env.get("HF_ENDPOINT")))
            raise ModelDownloadError("ModelScope connection timed out", detail="connection timed out")
        endpoint = env.get("HF_ENDPOINT")
        attempted_tiers.append(("hf", endpoint))
        if endpoint == HF_MIRROR:
            raise ModelDownloadError("HF-Mirror 502 Bad Gateway", detail="HTTP Error 502")
        target = entry.managed_install_dir()
        target.mkdir(parents=True, exist_ok=True)
        (target / "config.json").write_text("{}", encoding="utf-8")
        return True

    monkeypatch.setattr(installer, "_run_with_progress", fake_run)

    ok = installer.install_with_progress(
        entry,
        mirror="auto-cn",
        on_progress=lambda _frac, msg: progress_messages.append(msg),
    )
    assert ok is True
    assert attempted_tiers == [
        ("modelscope", None),
        ("hf", HF_MIRROR),
        ("hf", HUGGINGFACE),
    ]
    assert any("falling back to hf-mirror" in msg for msg in progress_messages)
    assert any("falling back to huggingface" in msg for msg in progress_messages)
    assert progress_messages[-1] == "download complete"


def test_modelscope_http_snapshot_downloader_verifies_hashes_and_nested_dirs(tmp_path):
    files_data = {
        "config.json": b'{"model_type": "qwen3_tts"}',
        "model.safetensors": b"primary-safetensor-payload",
        "vocab.json": b'{"a": 1}',
        "speech_tokenizer/config.json": b'{"tokenizer": true}',
        "speech_tokenizer/model.safetensors": b"speech-tokenizer-payload",
    }
    api_listing = {
        "Code": 200,
        "Success": True,
        "Data": {
            "Files": [
                {"Type": "tree", "Path": "speech_tokenizer", "Size": 0},
                {"Type": "blob", "Path": ".gitattributes", "Size": 12, "Sha256": "00" * 32},
                *[
                    {
                        "Type": "blob",
                        "Path": rel_path,
                        "Size": len(payload),
                        "Sha256": hashlib.sha256(payload).hexdigest(),
                    }
                    for rel_path, payload in files_data.items()
                ],
            ]
        },
    }

    requested_urls: list[str] = []

    def fake_opener(request, timeout=30):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        requested_urls.append(url)
        if "/api/v1/models/Qwen/Sample-TTS/repo/files" in url:
            return _MockHttpResponse(json.dumps(api_listing).encode("utf-8"))
        prefix = "https://www.modelscope.cn/models/Qwen/Sample-TTS/resolve/master/"
        assert url.startswith(prefix), url
        rel = url[len(prefix):]
        return _MockHttpResponse(files_data[rel])

    progress_updates: list[tuple[float, str]] = []
    out_dir = tmp_path / "qwen-sample"
    result = download_modelscope_snapshot(
        "Qwen/Sample-TTS",
        out_dir,
        required_files=["config.json", "model.safetensors", "vocab.json"],
        required_dirs=["speech_tokenizer"],
        on_progress=lambda frac, msg: progress_updates.append((frac, msg)),
        opener=fake_opener,
    )

    assert result == out_dir.resolve()
    for rel_path, expected_bytes in files_data.items():
        assert (out_dir / rel_path).read_bytes() == expected_bytes
    assert not (out_dir / ".gitattributes").exists()
    assert progress_updates[-1][0] == 1.0

    # Repeat invocation reuses verified local files without re-downloading blobs.
    requested_urls.clear()
    download_modelscope_snapshot(
        "Qwen/Sample-TTS",
        out_dir,
        required_files=["config.json", "model.safetensors", "vocab.json"],
        required_dirs=["speech_tokenizer"],
        opener=fake_opener,
    )
    assert len(requested_urls) == 1
    assert "/repo/files" in requested_urls[0]


def test_modelscope_downloader_rejects_corrupt_hash_and_path_traversal(tmp_path):
    corrupt_listing = {
        "Code": 200,
        "Success": True,
        "Data": {
            "Files": [
                {
                    "Type": "blob",
                    "Path": "config.json",
                    "Size": 2,
                    "Sha256": "ff" * 32,
                }
            ]
        },
    }

    def corrupt_opener(request, timeout=30):
        url = request.full_url
        if "/repo/files" in url:
            return _MockHttpResponse(json.dumps(corrupt_listing).encode("utf-8"))
        return _MockHttpResponse(b"{}")

    out_dir = tmp_path / "corrupt"
    with pytest.raises(RuntimeError, match="model hash mismatch"):
        download_modelscope_snapshot("Org/Corrupt", out_dir, opener=corrupt_opener)
    assert list(out_dir.glob("*.partial")) == []
    assert not (out_dir / "config.json").exists()

    traversal_listing = {
        "Code": 200,
        "Success": True,
        "Data": {"Files": [{"Type": "blob", "Path": "../../evil.bin", "Size": 4}]},
    }
    with pytest.raises(ValueError, match="Unsafe relative file path"):
        download_modelscope_snapshot(
            "Org/Evil",
            tmp_path / "safe",
            opener=lambda _req, timeout=30: _MockHttpResponse(json.dumps(traversal_listing).encode("utf-8")),
        )


def _find_powershell() -> str:
    found = shutil.which("pwsh") or shutil.which("powershell")
    if not found:
        pytest.skip("PowerShell is not available on this platform")
    return found


def test_setup_in_offline_mode_fails_without_attempting_bootstrap(tmp_path):
    ps_exe = _find_powershell()
    setup_ps1 = APP_ROOT / "setup.ps1"
    isolated_dir = tmp_path / "empty_bin"
    isolated_dir.mkdir()
    offline_env = os.environ.copy()
    sys_root = os.environ.get("SystemRoot", r"C:\Windows")
    offline_env["PATH"] = os.pathsep.join([
        str(Path(ps_exe).parent),
        str(Path(sys_root) / "System32"),
        str(isolated_dir),
    ])
    offline_run = subprocess.run(
        [ps_exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(setup_ps1), "-Offline"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=offline_env,
        timeout=20,
        check=False,
    )
    assert offline_run.returncode != 0
    combined_output = f"{offline_run.stdout}\n{offline_run.stderr}"
    assert "Offline" in combined_output or "离线" in combined_output
    assert "astral.sh" not in combined_output
