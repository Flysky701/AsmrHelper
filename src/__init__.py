"""Top-level package exports for ASMR Helper."""

from __future__ import annotations

from importlib import import_module

__version__ = "0.2.0"

__all__ = [
    "ASRRecognizer",
    "Mixer",
    "Pipeline",
    "PipelineConfig",
    "TTSEngine",
    "Translator",
    "VocalSeparator",
]

_EXPORTS = {
    "ASRRecognizer": ("src.core", "ASRRecognizer"),
    "Mixer": ("src.core", "Mixer"),
    "Pipeline": ("src.core", "Pipeline"),
    "PipelineConfig": ("src.core", "PipelineConfig"),
    "TTSEngine": ("src.core", "TTSEngine"),
    "Translator": ("src.core", "Translator"),
    "VocalSeparator": ("src.core", "VocalSeparator"),
}


def __getattr__(name: str):
    try:
        module_name, export_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    value = getattr(import_module(module_name), export_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
