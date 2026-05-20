"""Core orchestration exports with lazy loading."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "LANG_MAP",
    "LegacyPipelineOrchestrator",
    "PipelineExecutionContext",
    "ToolTaskCatalog",
    "ToolTaskDefinition",
]

_EXPORTS = {
    "LANG_MAP": ("src.core.orchestration.pipeline", "LANG_MAP"),
    "LegacyPipelineOrchestrator": ("src.core.orchestration.pipeline", "LegacyPipelineOrchestrator"),
    "PipelineExecutionContext": ("src.core.orchestration.pipeline", "PipelineExecutionContext"),
    "ToolTaskCatalog": ("src.core.orchestration.tools", "ToolTaskCatalog"),
    "ToolTaskDefinition": ("src.core.orchestration.tools", "ToolTaskDefinition"),
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
