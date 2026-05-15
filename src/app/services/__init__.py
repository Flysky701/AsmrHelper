"""Application-layer service entrypoints."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ModelService",
    "PipelineService",
    "ResourceService",
    "SubtitleService",
    "TaskService",
    "get_model_service",
    "get_pipeline_service",
    "get_resource_service",
    "get_subtitle_service",
    "get_task_service",
]

_EXPORTS = {
    "ModelService": ("src.app.services.model_service", "ModelService"),
    "PipelineService": ("src.app.services.pipeline_service", "PipelineService"),
    "ResourceService": ("src.app.services.resource_service", "ResourceService"),
    "SubtitleService": ("src.app.services.subtitle_service", "SubtitleService"),
    "TaskService": ("src.app.services.task_service", "TaskService"),
    "get_model_service": ("src.app.services.model_service", "get_model_service"),
    "get_pipeline_service": ("src.app.services.pipeline_service", "get_pipeline_service"),
    "get_resource_service": ("src.app.services.resource_service", "get_resource_service"),
    "get_subtitle_service": ("src.app.services.subtitle_service", "get_subtitle_service"),
    "get_task_service": ("src.app.services.task_service", "get_task_service"),
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
