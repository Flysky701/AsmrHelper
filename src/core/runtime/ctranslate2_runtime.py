"""Expose separately installed NVIDIA runtime libraries without importing Torch."""
from __future__ import annotations

import os
import sysconfig
from pathlib import Path

_dll_handles = []


def existing_cuda_directory() -> Path | None:
    if os.name != "nt":
        return None
    explicit = os.environ.get("ASMR_HELPER_CUDA_LIBRARY_DIR", "").strip()
    candidate = Path(explicit) if explicit else Path(sysconfig.get_path("purelib")) / "torch" / "lib"
    required = ("cublas64_12.dll", "cublasLt64_12.dll", "cudnn64_9.dll", "cudnn_ops64_9.dll",
                "cudnn_cnn64_9.dll", "cudnn_engines_precompiled64_9.dll")
    if all((candidate / name).is_file() for name in required):
        return candidate.resolve()
    if explicit:
        raise RuntimeError("ASMR_HELPER_CUDA_LIBRARY_DIR must contain complete CUDA 12/cuDNN 9 libraries")
    return None


def configure_cuda_libraries() -> None:
    if os.name != "nt":
        return
    site = Path(sysconfig.get_path("purelib"))
    directories = [site / "nvidia" / library / "bin" for library in ("cublas", "cudnn")]
    existing = existing_cuda_directory()
    if existing:
        directories.insert(0, existing)
    for directory in directories:
        if directory.is_dir():
            value = str(directory)
            if value not in os.environ.get("PATH", "").split(os.pathsep):
                os.environ["PATH"] = value + os.pathsep + os.environ.get("PATH", "")
                _dll_handles.append(os.add_dll_directory(value))


def cuda_available() -> bool:
    configure_cuda_libraries()
    import ctranslate2

    return ctranslate2.get_cuda_device_count() > 0


def selected_device(mode: str) -> str:
    if mode == "cpu":
        return "cpu"
    available = cuda_available()
    if mode == "cuda" and not available:
        raise RuntimeError("CTranslate2 CUDA was explicitly requested but no CUDA device is available")
    return "cuda" if available else "cpu"


def verify_runtime(mode: str) -> dict:
    configure_cuda_libraries()
    import ctranslate2
    import faster_whisper

    device = selected_device(mode)
    types = ctranslate2.get_supported_compute_types(device)
    if device == "cuda" and "float16" not in types:
        raise RuntimeError("CTranslate2 CUDA float16 is unavailable")
    return {"device": device, "ctranslate2": ctranslate2.__version__,
            "faster_whisper": faster_whisper.__version__, "compute_types": sorted(types)}
