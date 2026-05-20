"""Core engine runtime exports with lazy loading."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "AsrEngineRuntime",
    "AsrRegistry",
    "LlmOperationRuntime",
    "LlmRegistry",
    "SeparatorEngineRuntime",
    "SeparatorRegistry",
    "TtsEngineRuntime",
    "TtsRegistry",
    "get_asr_registry",
    "get_llm_registry",
    "get_separator_registry",
    "get_tts_registry",
]

_EXPORTS = {
    "AsrEngineRuntime": ("src.core.engines.asr", "AsrEngineRuntime"),
    "AsrRegistry": ("src.core.engines.asr", "AsrRegistry"),
    "LlmOperationRuntime": ("src.core.engines.llm", "LlmOperationRuntime"),
    "LlmRegistry": ("src.core.engines.llm", "LlmRegistry"),
    "SeparatorEngineRuntime": ("src.core.engines.separator", "SeparatorEngineRuntime"),
    "SeparatorRegistry": ("src.core.engines.separator", "SeparatorRegistry"),
    "TtsEngineRuntime": ("src.core.engines.tts", "TtsEngineRuntime"),
    "TtsRegistry": ("src.core.engines.tts", "TtsRegistry"),
    "get_asr_registry": ("src.core.engines.asr", "get_asr_registry"),
    "get_llm_registry": ("src.core.engines.llm", "get_llm_registry"),
    "get_separator_registry": ("src.core.engines.separator", "get_separator_registry"),
    "get_tts_registry": ("src.core.engines.tts", "get_tts_registry"),
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
