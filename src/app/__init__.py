"""Application layer for ASMR Helper."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "AppError",
    "AppExecutionError",
    "AppValidationError",
    "AudioToolService",
    "ArtifactSet",
    "BatchItemResult",
    "BatchPipelineRequest",
    "BatchPipelineResult",
    "BatchPipelineService",
    "ModelService",
    "ModelOperationResult",
    "ModelStatusView",
    "ModelSummary",
    "PipelineRequest",
    "PipelineResult",
    "PipelineService",
    "ResourceService",
    "ResourceStatus",
    "ResourceUnavailableError",
    "ResourceValidationError",
    "ScriptSubtitleRequest",
    "ScriptSubtitleResult",
    "ScriptSubtitleService",
    "SubtitleDocument",
    "SubtitleSegment",
    "SubtitleService",
    "SynthesisResult",
    "TaskService",
    "TaskStatus",
    "TranscriptionResult",
    "TranslationService",
    "TranslationResult",
    "VoiceService",
    "get_audio_tool_service",
    "get_batch_pipeline_service",
    "get_model_service",
    "get_pipeline_service",
    "get_resource_service",
    "get_script_subtitle_service",
    "get_subtitle_service",
    "get_task_service",
    "get_translation_service",
    "get_voice_service",
]

_EXPORTS = {
    "AppError": ("src.app.errors", "AppError"),
    "AppExecutionError": ("src.app.errors", "AppExecutionError"),
    "AppValidationError": ("src.app.errors", "AppValidationError"),
    "AudioToolService": ("src.app.services", "AudioToolService"),
    "ArtifactSet": ("src.app.dto", "ArtifactSet"),
    "BatchItemResult": ("src.app.dto", "BatchItemResult"),
    "BatchPipelineRequest": ("src.app.dto", "BatchPipelineRequest"),
    "BatchPipelineResult": ("src.app.dto", "BatchPipelineResult"),
    "BatchPipelineService": ("src.app.services", "BatchPipelineService"),
    "ModelService": ("src.app.services", "ModelService"),
    "ModelOperationResult": ("src.app.dto", "ModelOperationResult"),
    "ModelStatusView": ("src.app.dto", "ModelStatusView"),
    "ModelSummary": ("src.app.dto", "ModelSummary"),
    "PipelineRequest": ("src.app.dto", "PipelineRequest"),
    "PipelineResult": ("src.app.dto", "PipelineResult"),
    "PipelineService": ("src.app.services", "PipelineService"),
    "ResourceService": ("src.app.services", "ResourceService"),
    "ResourceStatus": ("src.app.dto", "ResourceStatus"),
    "ResourceUnavailableError": ("src.app.errors", "ResourceUnavailableError"),
    "ResourceValidationError": ("src.app.errors", "ResourceValidationError"),
    "ScriptSubtitleRequest": ("src.app.dto", "ScriptSubtitleRequest"),
    "ScriptSubtitleResult": ("src.app.dto", "ScriptSubtitleResult"),
    "ScriptSubtitleService": ("src.app.services", "ScriptSubtitleService"),
    "SubtitleDocument": ("src.app.dto", "SubtitleDocument"),
    "SubtitleSegment": ("src.app.dto", "SubtitleSegment"),
    "SubtitleService": ("src.app.services", "SubtitleService"),
    "SynthesisResult": ("src.app.dto", "SynthesisResult"),
    "TaskService": ("src.app.services", "TaskService"),
    "TaskStatus": ("src.app.dto", "TaskStatus"),
    "TranscriptionResult": ("src.app.dto", "TranscriptionResult"),
    "TranslationService": ("src.app.services", "TranslationService"),
    "TranslationResult": ("src.app.dto", "TranslationResult"),
    "VoiceService": ("src.app.services", "VoiceService"),
    "get_audio_tool_service": ("src.app.services", "get_audio_tool_service"),
    "get_batch_pipeline_service": ("src.app.services", "get_batch_pipeline_service"),
    "get_model_service": ("src.app.services", "get_model_service"),
    "get_pipeline_service": ("src.app.services", "get_pipeline_service"),
    "get_resource_service": ("src.app.services", "get_resource_service"),
    "get_script_subtitle_service": ("src.app.services", "get_script_subtitle_service"),
    "get_subtitle_service": ("src.app.services", "get_subtitle_service"),
    "get_task_service": ("src.app.services", "get_task_service"),
    "get_translation_service": ("src.app.services", "get_translation_service"),
    "get_voice_service": ("src.app.services", "get_voice_service"),
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
