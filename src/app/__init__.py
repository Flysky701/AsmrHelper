"""Application layer for ASMR Helper."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "AppError",
    "AppExecutionError",
    "AppValidationError",
    "ArtifactSet",
    "ModelService",
    "ModelStatusView",
    "ModelSummary",
    "PipelineRequest",
    "PipelineResult",
    "PipelineService",
    "ResourceService",
    "ResourceStatus",
    "ResourceUnavailableError",
    "ResourceValidationError",
    "SubtitleDocument",
    "SubtitleSegment",
    "SubtitleService",
    "SynthesisResult",
    "TaskService",
    "TaskStatus",
    "TranslationResult",
    "get_model_service",
    "get_pipeline_service",
    "get_resource_service",
    "get_subtitle_service",
    "get_task_service",
]

_EXPORTS = {
    "AppError": ("src.app.errors", "AppError"),
    "AppExecutionError": ("src.app.errors", "AppExecutionError"),
    "AppValidationError": ("src.app.errors", "AppValidationError"),
    "ArtifactSet": ("src.app.dto", "ArtifactSet"),
    "ModelService": ("src.app.services", "ModelService"),
    "ModelStatusView": ("src.app.dto", "ModelStatusView"),
    "ModelSummary": ("src.app.dto", "ModelSummary"),
    "PipelineRequest": ("src.app.dto", "PipelineRequest"),
    "PipelineResult": ("src.app.dto", "PipelineResult"),
    "PipelineService": ("src.app.services", "PipelineService"),
    "ResourceService": ("src.app.services", "ResourceService"),
    "ResourceStatus": ("src.app.dto", "ResourceStatus"),
    "ResourceUnavailableError": ("src.app.errors", "ResourceUnavailableError"),
    "ResourceValidationError": ("src.app.errors", "ResourceValidationError"),
    "SubtitleDocument": ("src.app.dto", "SubtitleDocument"),
    "SubtitleSegment": ("src.app.dto", "SubtitleSegment"),
    "SubtitleService": ("src.app.services", "SubtitleService"),
    "SynthesisResult": ("src.app.dto", "SynthesisResult"),
    "TaskService": ("src.app.services", "TaskService"),
    "TaskStatus": ("src.app.dto", "TaskStatus"),
    "TranslationResult": ("src.app.dto", "TranslationResult"),
    "get_model_service": ("src.app.services", "get_model_service"),
    "get_pipeline_service": ("src.app.services", "get_pipeline_service"),
    "get_resource_service": ("src.app.services", "get_resource_service"),
    "get_subtitle_service": ("src.app.services", "get_subtitle_service"),
    "get_task_service": ("src.app.services", "get_task_service"),
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
