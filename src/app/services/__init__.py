"""Application-layer service entrypoints."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "AsrService",
    "ModelService",
    "PipelineService",
    "ResourceService",
    "SubtitleService",
    "TaskService",
    "TranslationService",
    "TtsService",
    "get_asr_service",
    "get_model_service",
    "get_pipeline_service",
    "get_resource_service",
    "get_subtitle_service",
    "get_task_service",
    "get_translation_service",
    "get_tts_service",
]

_EXPORTS = {
    "AsrService": ("src.app.services.asr_service", "AsrService"),
    "ModelService": ("src.app.services.model_service", "ModelService"),
    "PipelineService": ("src.app.services.pipeline_service", "PipelineService"),
    "ResourceService": ("src.app.services.resource_service", "ResourceService"),
    "SubtitleService": ("src.app.services.subtitle_service", "SubtitleService"),
    "TaskService": ("src.app.services.task_service", "TaskService"),
    "TranslationService": ("src.app.services.translation_service", "TranslationService"),
    "TtsService": ("src.app.services.tts_service", "TtsService"),
    "get_asr_service": ("src.app.services.asr_service", "get_asr_service"),
    "get_model_service": ("src.app.services.model_service", "get_model_service"),
    "get_pipeline_service": ("src.app.services.pipeline_service", "get_pipeline_service"),
    "get_resource_service": ("src.app.services.resource_service", "get_resource_service"),
    "get_subtitle_service": ("src.app.services.subtitle_service", "get_subtitle_service"),
    "get_task_service": ("src.app.services.task_service", "get_task_service"),
    "get_translation_service": ("src.app.services.translation_service", "get_translation_service"),
    "get_tts_service": ("src.app.services.tts_service", "get_tts_service"),
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
