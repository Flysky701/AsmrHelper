"""Shared FastAPI dependencies for service injection."""

from __future__ import annotations

from src.app.services import (
    get_asr_engine_service,
    get_artifact_service,
    get_audio_tool_service,
    get_batch_pipeline_service,
    get_capability_descriptor_service,
    get_execution_profile_builder,
    get_input_catalog_service,
    get_llm_capability_service,
    get_model_service,
    get_pipeline_service,
    get_pipeline_task_orchestrator,
    get_resource_service,
    get_script_subtitle_service,
    get_session_service,
    get_settings_service,
    get_subtitle_service,
    get_task_service,
    get_tool_registry,
    get_translation_service,
    get_tts_engine_service,
    get_voice_service,
    get_workspace_service,
)


def pipeline_service():
    return get_pipeline_service()


def asr_engine_service():
    return get_asr_engine_service()


def artifact_service():
    return get_artifact_service()


def translation_service():
    return get_translation_service()


def llm_capability_service():
    return get_llm_capability_service()


def tts_engine_service():
    return get_tts_engine_service()


def model_service():
    return get_model_service()


def subtitle_service():
    return get_subtitle_service()


def task_service():
    return get_task_service()


def resource_service():
    return get_resource_service()


def audio_tool_service():
    return get_audio_tool_service()


def batch_pipeline_service():
    return get_batch_pipeline_service()


def pipeline_task_orchestrator():
    return get_pipeline_task_orchestrator()


def script_subtitle_service():
    return get_script_subtitle_service()


def voice_service():
    return get_voice_service()


def tool_registry():
    return get_tool_registry()


def settings_service():
    return get_settings_service()


def capability_descriptor_service():
    return get_capability_descriptor_service()


def execution_profile_builder():
    return get_execution_profile_builder()


def workspace_service():
    return get_workspace_service()


def input_catalog_service():
    return get_input_catalog_service()


def session_service():
    return get_session_service()
