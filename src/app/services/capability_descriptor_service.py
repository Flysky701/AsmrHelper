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
                "category": "tts",
                "provider": "kokoro",
                "display_name": "Kokoro TTS",
                "kind": "local",
                "supported_models": ["default"],
                "default_model": "default",
                "common_option_schema": [
                    _option("voice", "string", required=False, default="af_heart", description="Kokoro voice id"),
                    _option("speed", "number", required=False, default=1.0, description="Synthesis speed"),
                ],
                "provider_option_schema": [
                    _option("lang_code", "string", required=False, description="Optional Kokoro language code"),
                    _option("repo_id", "string", required=False, description="Optional custom Hugging Face repo id"),
                    _option("split_pattern", "string", required=False, default="\\n+", description="Chunk split regex"),
                    _option("sample_rate", "integer", required=False, default=24000, description="Output sample rate"),
                ],
                "supports": {
                    "voice_list": True,
                    "voice_clone": False,
                    "preview": False,
                    "streaming": False,
                    "lightweight_local": True,
                },
            },
            {
                "category": "tts",
                "provider": "voxcpm2",
                "display_name": "VoxCPM2",
                "kind": "local",
                "supported_models": ["default"],
                "default_model": "default",
                "common_option_schema": [
                    _option("voice", "string", required=False, default="default", description="Voice mode: default / voice_design / voice_clone"),
                ],
                "provider_option_schema": [
                    _option("model_dir", "string", required=False, description="Local model directory or HuggingFace repo id (default: openbmb/VoxCPM2)"),
                    _option("cfg_value", "number", required=False, default=2.0, description="Classifier-free guidance scale"),
                    _option("inference_timesteps", "integer", required=False, default=10, description="Diffusion inference steps (10=fast, 20=quality)"),
                    _option("load_denoiser", "boolean", required=False, default=True, description="Load denoiser for higher quality output"),
                    _option("device_map", "string", required=False, default="auto", description="Device map for model loading"),
                    _option("reference_wav_path", "string", required=False, description="Reference audio path for voice cloning"),
                    _option("prompt_wav_path", "string", required=False, description="Prompt audio path for ultimate cloning (same as reference for max fidelity)"),
                    _option("prompt_text", "string", required=False, description="Transcript of prompt audio for ultimate cloning"),
                ],
                "supports": {
                    "voice_list": True,
                    "voice_clone": True,
                    "voice_design": True,
                    "ultimate_clone": True,
                    "preview": True,
                    "streaming": True,
                    "multilingual": True,
                    "languages": 30,
                    "sample_rate": 48000,
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
                "supported_models": [
                    "faster-whisper-tiny",
                    "faster-whisper-base",
                    "faster-whisper-small",
                    "faster-whisper-medium",
                    "faster-whisper-large-v3",
                ],
                "default_model": "faster-whisper-base",
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
                "category": "asr",
                "provider": "fun_asr",
                "display_name": "Fun-ASR",
                "kind": "local",
                "supported_models": [
                    "fun-asr-nano-2512",
                    "fun-asr-mlt-nano-2512",
                ],
                "default_model": "fun-asr-nano-2512",
                "common_option_schema": [
                    _option("language", "string", required=False, default="ja", description="Language hint"),
                ],
                "provider_option_schema": [
                    _option("hub", "string", required=False, default="hf", description="Model hub id (hf/ms)"),
                    _option("device", "string", required=False, default="auto", description="Inference device"),
                    _option("batch_size", "integer", required=False, default=1, description="Batch size for generate"),
                    _option(
                        "sentence_timestamp",
                        "boolean",
                        required=False,
                        default=True,
                        description="Request sentence-level timestamps when supported",
                    ),
                    _option(
                        "trust_remote_code",
                        "boolean",
                        required=False,
                        default=True,
                        description="Allow FunASR to load custom model code",
                    ),
                    _option(
                        "remote_code_path",
                        "string",
                        required=False,
                        description="Optional local Fun-ASR source model.py path",
                    ),
                    _option("hotwords", "array", required=False, description="Optional hotword list"),
                    _option("vad_model", "string", required=False, description="Optional FunASR VAD model"),
                    _option("vad_kwargs", "object", required=False, description="Optional VAD kwargs"),
                ],
                "supports": {
                    "language_hint": True,
                    "language_auto_detect": True,
                    "vad": True,
                    "word_timestamps": False,
                    "sentence_timestamps": True,
                    "diarization": False,
                    "streaming": False,
                    "hotwords": True,
                },
            },
            {
                "category": "asr",
                "provider": "qwen3_asr",
                "display_name": "Qwen3-ASR",
                "kind": "local",
                "supported_models": [
                    "qwen3-asr-0.6b",
                    "qwen3-asr-1.7b",
                ],
                "default_model": "qwen3-asr-0.6b",
                "common_option_schema": [
                    _option("language", "string", required=False, default="ja", description="Language hint"),
                ],
                "provider_option_schema": [
                    _option("device_map", "string", required=False, default="cpu", description="Transformers device map"),
                    _option("dtype", "string", required=False, default="bfloat16", description="Model dtype hint"),
                    _option(
                        "attn_implementation",
                        "string",
                        required=False,
                        description="Optional attention backend such as flash_attention_2",
                    ),
                    _option(
                        "max_inference_batch_size",
                        "integer",
                        required=False,
                        default=1,
                        description="Batch size limit for offline inference",
                    ),
                    _option(
                        "max_new_tokens",
                        "integer",
                        required=False,
                        default=512,
                        description="Maximum decoding tokens for long audio",
                    ),
                    _option(
                        "forced_aligner",
                        "string",
                        required=False,
                        description="Optional Qwen forced aligner model id or local path",
                    ),
                    _option(
                        "forced_aligner_kwargs",
                        "object",
                        required=False,
                        description="Optional forced aligner initialization kwargs",
                    ),
                    _option(
                        "return_time_stamps",
                        "boolean",
                        required=False,
                        default=False,
                        description="Return alignment-based timestamps when supported",
                    ),
                    _option("context", "string", required=False, description="Optional textual context prompt"),
                ],
                "supports": {
                    "language_hint": True,
                    "language_auto_detect": True,
                    "vad": False,
                    "word_timestamps": True,
                    "sentence_timestamps": True,
                    "diarization": False,
                    "streaming": False,
                    "language_identification": True,
                    "music_transcription": True,
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
