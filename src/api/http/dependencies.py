"""Shared FastAPI dependencies for service injection."""

from __future__ import annotations

from src.app.services import (
    get_asr_service,
    get_model_service,
    get_pipeline_service,
    get_resource_service,
    get_subtitle_service,
    get_task_service,
    get_translation_service,
    get_tts_service,
)


def pipeline_service():
    return get_pipeline_service()


def asr_service():
    return get_asr_service()


def translation_service():
    return get_translation_service()


def tts_service():
    return get_tts_service()


def model_service():
    return get_model_service()


def subtitle_service():
    return get_subtitle_service()


def task_service():
    return get_task_service()


def resource_service():
    return get_resource_service()
