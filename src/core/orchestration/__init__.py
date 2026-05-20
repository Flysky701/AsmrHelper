"""Core orchestration exports with lazy loading."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ArtifactResultMapper",
    "LANG_MAP",
    "LegacyPipelineOrchestrator",
    "MixConfig",
    "PipelineExecutionContext",
    "PipelineExecutionPlan",
    "PipelineMode",
    "StageBinding",
    "StageKind",
    "SubtitleConfig",
    "ToolTaskCatalog",
    "ToolTaskDefinition",
    "build_execution_plan",
]

_EXPORTS = {
    "ArtifactResultMapper": ("src.core.orchestration.pipeline", "ArtifactResultMapper"),
    "LANG_MAP": ("src.core.orchestration.pipeline", "LANG_MAP"),
    "LegacyPipelineOrchestrator": ("src.core.orchestration.pipeline", "LegacyPipelineOrchestrator"),
    "MixConfig": ("src.core.orchestration.pipeline", "MixConfig"),
    "PipelineExecutionContext": ("src.core.orchestration.pipeline", "PipelineExecutionContext"),
    "PipelineExecutionPlan": ("src.core.orchestration.pipeline", "PipelineExecutionPlan"),
    "PipelineMode": ("src.core.orchestration.pipeline", "PipelineMode"),
    "StageBinding": ("src.core.orchestration.pipeline", "StageBinding"),
    "StageKind": ("src.core.orchestration.pipeline", "StageKind"),
    "SubtitleConfig": ("src.core.orchestration.pipeline", "SubtitleConfig"),
    "ToolTaskCatalog": ("src.core.orchestration.tools", "ToolTaskCatalog"),
    "ToolTaskDefinition": ("src.core.orchestration.tools", "ToolTaskDefinition"),
    "build_execution_plan": ("src.core.orchestration.pipeline", "build_execution_plan"),
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
