"""Application-layer service entrypoints."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "AsrEngineService",
    "ArtifactService",
    "AudioToolService",
    "BatchPipelineService",
    "CapabilityDescriptorService",
    "ExecutionProfileBuilder",
    "InputCatalogService",
    "LlmCapabilityService",
    "ModelService",
    "PipelineService",
    "PipelineTaskOrchestrator",
    "ResourceService",
    "ScriptSubtitleService",
    "SessionService",
    "SettingsService",
    "SubtitleService",
    "TaskService",
    "ToolRegistry",
    "TranslationService",
    "TtsEngineService",
    "VoiceService",
    "WorkspaceService",
    "get_asr_engine_service",
    "get_artifact_service",
    "get_audio_tool_service",
    "get_batch_pipeline_service",
    "get_capability_descriptor_service",
    "get_execution_profile_builder",
    "get_input_catalog_service",
    "get_llm_capability_service",
    "get_model_service",
    "get_pipeline_service",
    "get_pipeline_task_orchestrator",
    "get_resource_service",
    "get_script_subtitle_service",
    "get_session_service",
    "get_settings_service",
    "get_subtitle_service",
    "get_task_service",
    "get_tool_registry",
    "get_translation_service",
    "get_tts_engine_service",
    "get_voice_service",
    "get_workspace_service",
]

_EXPORTS = {
    "AsrEngineService": ("src.app.services.asr_engine_service", "AsrEngineService"),
    "ArtifactService": ("src.app.services.artifact_service", "ArtifactService"),
    "AudioToolService": ("src.app.services.audio_tool_service", "AudioToolService"),
    "BatchPipelineService": ("src.app.services.batch_pipeline_service", "BatchPipelineService"),
    "CapabilityDescriptorService": (
        "src.app.services.capability_descriptor_service",
        "CapabilityDescriptorService",
    ),
    "ExecutionProfileBuilder": (
        "src.app.services.execution_profile_builder",
        "ExecutionProfileBuilder",
    ),
    "InputCatalogService": ("src.app.services.input_catalog_service", "InputCatalogService"),
    "LlmCapabilityService": (
        "src.app.services.llm_capability_service",
        "LlmCapabilityService",
    ),
    "ModelService": ("src.app.services.model_service", "ModelService"),
    "PipelineService": ("src.app.services.pipeline_service", "PipelineService"),
    "PipelineTaskOrchestrator": (
        "src.app.services.pipeline_task_orchestrator",
        "PipelineTaskOrchestrator",
    ),
    "ResourceService": ("src.app.services.resource_service", "ResourceService"),
    "ScriptSubtitleService": (
        "src.app.services.script_subtitle_service",
        "ScriptSubtitleService",
    ),
    "SessionService": ("src.app.services.session_service", "SessionService"),
    "SettingsService": ("src.app.services.settings_service", "SettingsService"),
    "SubtitleService": ("src.app.services.subtitle_service", "SubtitleService"),
    "TaskService": ("src.app.services.task_service", "TaskService"),
    "ToolRegistry": ("src.app.services.tool_registry", "ToolRegistry"),
    "TranslationService": ("src.app.services.translation_service", "TranslationService"),
    "TtsEngineService": ("src.app.services.tts_engine_service", "TtsEngineService"),
    "VoiceService": ("src.app.services.voice_service", "VoiceService"),
    "WorkspaceService": ("src.app.services.workspace_service", "WorkspaceService"),
    "get_asr_engine_service": ("src.app.services.asr_engine_service", "get_asr_engine_service"),
    "get_artifact_service": ("src.app.services.artifact_service", "get_artifact_service"),
    "get_audio_tool_service": ("src.app.services.audio_tool_service", "get_audio_tool_service"),
    "get_batch_pipeline_service": (
        "src.app.services.batch_pipeline_service",
        "get_batch_pipeline_service",
    ),
    "get_capability_descriptor_service": (
        "src.app.services.capability_descriptor_service",
        "get_capability_descriptor_service",
    ),
    "get_execution_profile_builder": (
        "src.app.services.execution_profile_builder",
        "get_execution_profile_builder",
    ),
    "get_input_catalog_service": (
        "src.app.services.input_catalog_service",
        "get_input_catalog_service",
    ),
    "get_llm_capability_service": (
        "src.app.services.llm_capability_service",
        "get_llm_capability_service",
    ),
    "get_model_service": ("src.app.services.model_service", "get_model_service"),
    "get_pipeline_service": ("src.app.services.pipeline_service", "get_pipeline_service"),
    "get_pipeline_task_orchestrator": (
        "src.app.services.pipeline_task_orchestrator",
        "get_pipeline_task_orchestrator",
    ),
    "get_resource_service": ("src.app.services.resource_service", "get_resource_service"),
    "get_script_subtitle_service": (
        "src.app.services.script_subtitle_service",
        "get_script_subtitle_service",
    ),
    "get_session_service": ("src.app.services.session_service", "get_session_service"),
    "get_settings_service": ("src.app.services.settings_service", "get_settings_service"),
    "get_subtitle_service": ("src.app.services.subtitle_service", "get_subtitle_service"),
    "get_task_service": ("src.app.services.task_service", "get_task_service"),
    "get_tool_registry": ("src.app.services.tool_registry", "get_tool_registry"),
    "get_translation_service": ("src.app.services.translation_service", "get_translation_service"),
    "get_tts_engine_service": ("src.app.services.tts_engine_service", "get_tts_engine_service"),
    "get_voice_service": ("src.app.services.voice_service", "get_voice_service"),
    "get_workspace_service": ("src.app.services.workspace_service", "get_workspace_service"),
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
