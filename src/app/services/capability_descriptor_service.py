"""Capability descriptor registry service."""

from __future__ import annotations

import threading
from copy import deepcopy
from typing import Any

from ..errors import AppValidationError


def _option(
    name: str,
    type_name: str,
    *,
    required: bool = False,
    default: Any = None,
    description: str = "",
) -> dict[str, Any]:
    return {
        "name": name,
        "type": type_name,
        "required": required,
        "default": default,
        "description": description,
    }


class CapabilityDescriptorService:
    """Registry of supported capability descriptors."""

    def __init__(self):
        self._descriptors = self._build_descriptors()

    def list_descriptors(
        self,
        *,
        category: str | None = None,
        provider: str | None = None,
    ) -> list[dict[str, Any]]:
        descriptors = self._descriptors
        if category is not None:
            descriptors = [item for item in descriptors if item["category"] == category]
        if provider is not None:
            descriptors = [item for item in descriptors if item["provider"] == provider]
        return deepcopy(descriptors)

    def list_categories(self) -> list[str]:
        return sorted({item["category"] for item in self._descriptors})

    def get_descriptor(self, category: str, provider: str) -> dict[str, Any]:
        for item in self._descriptors:
            if item["category"] == category and item["provider"] == provider:
                return deepcopy(item)
        raise AppValidationError(f"capability descriptor not found: {category}/{provider}")

    def _build_descriptors(self) -> list[dict[str, Any]]:
        return [
            {
                "category": "tts",
                "provider": "edge",
                "display_name": "Edge TTS",
                "kind": "cloud",
                "supported_models": ["default"],
                "default_model": "default",
                "common_option_schema": [
                    _option("voice", "string", required=True, default="zh-CN-XiaoxiaoNeural", description="TTS voice"),
                    _option("speed", "number", required=False, default=1.0, description="Playback speed"),
                ],
                "provider_option_schema": [],
                "supports": {
                    "voice_list": True,
                    "voice_clone": False,
                    "preview": False,
                    "streaming": False,
                },
            },
            {
                "category": "tts",
                "provider": "qwen3",
                "display_name": "Qwen3 TTS",
                "kind": "local",
                "supported_models": ["default"],
                "default_model": "default",
                "common_option_schema": [
                    _option("voice", "string", required=False, default="Vivian", description="Preset voice or speaker"),
                    _option("speed", "number", required=False, default=1.0, description="Synthesis speed"),
                ],
                "provider_option_schema": [
                    _option("voice_profile_id", "string", required=False, description="Custom profile identifier"),
                    _option("emotion", "string", required=False, description="Optional synthesis emotion"),
                    _option("temperature", "number", required=False, description="Optional model temperature"),
                ],
                "supports": {
                    "voice_list": True,
                    "voice_clone": True,
                    "preview": True,
                    "streaming": False,
                },
            },
            {
                "category": "llm",
                "provider": "deepseek",
                "display_name": "DeepSeek",
                "kind": "cloud",
                "supported_models": ["default"],
                "default_model": "default",
                "common_option_schema": [
                    _option("temperature", "number", required=False, default=0.2, description="Sampling temperature"),
                    _option("max_tokens", "integer", required=False, description="Optional output token limit"),
                ],
                "provider_option_schema": [],
                "supports": {
                    "chat_completion": True,
                    "structured_output": False,
                    "json_mode": False,
                    "streaming": False,
                },
            },
            {
                "category": "llm",
                "provider": "openai",
                "display_name": "OpenAI-compatible",
                "kind": "cloud",
                "supported_models": ["default"],
                "default_model": "default",
                "common_option_schema": [
                    _option("temperature", "number", required=False, default=0.2, description="Sampling temperature"),
                    _option("max_tokens", "integer", required=False, description="Optional output token limit"),
                ],
                "provider_option_schema": [],
                "supports": {
                    "chat_completion": True,
                    "structured_output": True,
                    "json_mode": True,
                    "streaming": True,
                },
            },
            {
                "category": "asr",
                "provider": "faster_whisper",
                "display_name": "faster-whisper",
                "kind": "local",
                "supported_models": ["tiny", "base", "small", "medium", "large-v3"],
                "default_model": "base",
                "common_option_schema": [
                    _option("language", "string", required=False, default="ja", description="Language hint"),
                ],
                "provider_option_schema": [
                    _option("disable_vad", "boolean", required=False, default=True, description="Disable VAD filtering"),
                    _option("beam_size", "integer", required=False, description="Optional beam size"),
                ],
                "supports": {
                    "language_hint": True,
                    "language_auto_detect": True,
                    "vad": True,
                    "word_timestamps": False,
                    "diarization": False,
                    "streaming": False,
                },
            },
            {
                "category": "separator",
                "provider": "htdemucs",
                "display_name": "HTDemucs",
                "kind": "local",
                "supported_models": ["htdemucs", "htdemucs_ft", "htdemucs_6s"],
                "default_model": "htdemucs",
                "common_option_schema": [],
                "provider_option_schema": [],
                "supports": {
                    "multi_stem": True,
                },
            },
            {
                "category": "separator",
                "provider": "mdx",
                "display_name": "MDX",
                "kind": "local",
                "supported_models": ["mdx", "mdx_extra"],
                "default_model": "mdx",
                "common_option_schema": [],
                "provider_option_schema": [],
                "supports": {
                    "multi_stem": False,
                },
            },
        ]


_service: CapabilityDescriptorService | None = None
_lock = threading.Lock()


def get_capability_descriptor_service() -> CapabilityDescriptorService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = CapabilityDescriptorService()
    return _service
