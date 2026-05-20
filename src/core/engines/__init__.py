"""Core engine runtime exports with lazy loading."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "AsrEngineRuntime",
    "LlmOperationRuntime",
    "SeparatorEngineRuntime",
    "TtsEngineRuntime",
]

_EXPORTS = {
    "AsrEngineRuntime": ("src.core.engines.asr", "AsrEngineRuntime"),
    "LlmOperationRuntime": ("src.core.engines.llm", "LlmOperationRuntime"),
    "SeparatorEngineRuntime": ("src.core.engines.separator", "SeparatorEngineRuntime"),
    "TtsEngineRuntime": ("src.core.engines.tts", "TtsEngineRuntime"),
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
