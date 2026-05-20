"""Core package exports with lazy loading."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "ASRRecognizer",
    "AsrEngineRuntime",
    "ArtifactIndex",
    "ArtifactRecord",
    "ArtifactSet",
    "InputAsset",
    "InputCatalog",
    "LegacyPipelineOrchestrator",
    "LlmOperationRuntime",
    "Mixer",
    "ModelManager",
    "ModelService",
    "Pipeline",
    "PipelineConfig",
    "PipelineExecutionContext",
    "ProcessingSession",
    "ResourceStatus",
    "RuntimeWorkspace",
    "RuntimeWorkspaceManager",
    "SeparatorEngineRuntime",
    "SessionRegistry",
    "SubtitleAsset",
    "SubtitleCleaner",
    "SubtitleDocument",
    "SubtitleDomainService",
    "SubtitleExporter",
    "SubtitleNormalizer",
    "SubtitleParser",
    "SubtitleSegment",
    "TTSEngine",
    "TtsEngineRuntime",
    "TaskRegistry",
    "TaskSpec",
    "TaskStatus",
    "Translator",
    "ToolTaskCatalog",
    "ToolTaskDefinition",
    "VocalSeparator",
    "WorkspaceContext",
    "WorkspaceResolver",
    "get_model_manager",
    "get_model_service",
]

_EXPORTS = {
    "ASRRecognizer": ("src.core.asr", "ASRRecognizer"),
    "AsrEngineRuntime": ("src.core.engines", "AsrEngineRuntime"),
    "ArtifactIndex": ("src.core.artifacts", "ArtifactIndex"),
    "ArtifactRecord": ("src.core.artifacts", "ArtifactRecord"),
    "ArtifactSet": ("src.core.artifacts", "ArtifactSet"),
    "InputAsset": ("src.core.sessions", "InputAsset"),
    "InputCatalog": ("src.core.sessions", "InputCatalog"),
    "LegacyPipelineOrchestrator": ("src.core.orchestration", "LegacyPipelineOrchestrator"),
    "LlmOperationRuntime": ("src.core.engines", "LlmOperationRuntime"),
    "Mixer": ("src.mixer", "Mixer"),
    "ModelManager": ("src.core.model_manager", "ModelManager"),
    "ModelService": ("src.core.resources", "ModelService"),
    "Pipeline": ("src.core.pipeline", "Pipeline"),
    "PipelineConfig": ("src.core.pipeline", "PipelineConfig"),
    "PipelineExecutionContext": ("src.core.orchestration", "PipelineExecutionContext"),
    "ProcessingSession": ("src.core.sessions", "ProcessingSession"),
    "ResourceStatus": ("src.core.runtime", "ResourceStatus"),
    "RuntimeWorkspace": ("src.core.runtime", "RuntimeWorkspace"),
    "RuntimeWorkspaceManager": ("src.core.runtime", "RuntimeWorkspaceManager"),
    "SeparatorEngineRuntime": ("src.core.engines", "SeparatorEngineRuntime"),
    "SessionRegistry": ("src.core.sessions", "SessionRegistry"),
    "SubtitleAsset": ("src.core.subtitles", "SubtitleAsset"),
    "SubtitleCleaner": ("src.core.subtitles", "SubtitleCleaner"),
    "SubtitleDocument": ("src.core.subtitles", "SubtitleDocument"),
    "SubtitleDomainService": ("src.core.subtitles", "SubtitleDomainService"),
    "SubtitleExporter": ("src.core.subtitles", "SubtitleExporter"),
    "SubtitleNormalizer": ("src.core.subtitles", "SubtitleNormalizer"),
    "SubtitleParser": ("src.core.subtitles", "SubtitleParser"),
    "SubtitleSegment": ("src.core.subtitles", "SubtitleSegment"),
    "TTSEngine": ("src.core.tts", "TTSEngine"),
    "TtsEngineRuntime": ("src.core.engines", "TtsEngineRuntime"),
    "TaskRegistry": ("src.core.tasks", "TaskRegistry"),
    "TaskSpec": ("src.core.tasks", "TaskSpec"),
    "TaskStatus": ("src.core.tasks", "TaskStatus"),
    "Translator": ("src.core.translate", "Translator"),
    "ToolTaskCatalog": ("src.core.orchestration", "ToolTaskCatalog"),
    "ToolTaskDefinition": ("src.core.orchestration", "ToolTaskDefinition"),
    "VocalSeparator": ("src.core.vocal_separator", "VocalSeparator"),
    "WorkspaceContext": ("src.core.sessions", "WorkspaceContext"),
    "WorkspaceResolver": ("src.core.sessions", "WorkspaceResolver"),
    "get_model_manager": ("src.core.model_manager", "get_model_manager"),
    "get_model_service": ("src.core.resources", "get_model_service"),
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
