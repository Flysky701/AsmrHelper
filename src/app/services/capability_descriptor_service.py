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
    enum: list[Any] | None = None,
    min_value: float | int | None = None,
    max_value: float | int | None = None,
    advanced: bool = False,
    secret: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "type": type_name,
        "required": required,
        "default": default,
        "description": description,
        "enum": list(enum or []),
        "min": min_value,
        "max": max_value,
        "advanced": advanced,
        "secret": secret,
    }


def _matches_option_type(type_name: str, value: Any) -> bool:
    if type_name == "boolean":
        return isinstance(value, bool)
    if type_name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if type_name == "string":
        return isinstance(value, str)
    if type_name == "array":
        return isinstance(value, list)
    if type_name == "object":
        return isinstance(value, dict)
    return False


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

    def validate_options(
        self,
        *,
        category: str,
        provider: str,
        common_options: dict[str, Any] | None = None,
        provider_options: dict[str, Any] | None = None,
        allow_unknown_common: bool = False,
    ) -> None:
        """Validate runtime options against the advertised capability schema."""
        descriptor = self.get_descriptor(category, provider)
        self._validate_option_group(
            descriptor["common_option_schema"],
            common_options or {},
            label=f"{category}/{provider}.common_options",
            allow_unknown=allow_unknown_common,
        )
        self._validate_option_group(
            descriptor["provider_option_schema"],
            provider_options or {},
            label=f"{category}/{provider}.provider_options",
            allow_unknown=False,
        )

    @staticmethod
    def _validate_option_group(
        schema: list[dict[str, Any]],
        values: dict[str, Any],
        *,
        label: str,
        allow_unknown: bool,
    ) -> None:
        entries = {entry["name"]: entry for entry in schema}
        unknown = sorted(set(values) - set(entries))
        if unknown and not allow_unknown:
            raise AppValidationError(
                f"{label} contains unsupported options: {', '.join(unknown)}"
            )

        for name, entry in entries.items():
            if name not in values:
                if entry.get("required") and entry.get("default") is None:
                    raise AppValidationError(f"{label}.{name} is required")
                continue

            value = values[name]
            if not _matches_option_type(str(entry["type"]), value):
                raise AppValidationError(
                    f"{label}.{name} must be {entry['type']}"
                )
            enum = list(entry.get("enum") or [])
            if enum and value not in enum:
                raise AppValidationError(
                    f"{label}.{name} must be one of {enum}"
                )
            min_value = entry.get("min")
            max_value = entry.get("max")
            if min_value is not None and value < min_value:
                raise AppValidationError(
                    f"{label}.{name} must be >= {min_value}"
                )
            if max_value is not None and value > max_value:
                raise AppValidationError(
                    f"{label}.{name} must be <= {max_value}"
                )

    def _build_descriptors(self) -> list[dict[str, Any]]:
        from src.core.engines.llm import get_llm_registry

        llm_registry = get_llm_registry()
        descriptors = [
            {
                "category": "tts",
                "provider": "edge",
                "display_name": "Edge TTS",
                "kind": "cloud",
                "supported_models": ["default"],
                "default_model": "default",
                "common_option_schema": [
                    _option("voice", "string", required=True, default="zh-CN-XiaoxiaoNeural", description="TTS voice"),
                    _option(
                        "speed",
                        "number",
                        required=False,
                        default=1.0,
                        min_value=0.5,
                        max_value=2.0,
                        description="Speech speed multiplier mapped to Edge rate",
                    ),
                ],
                "provider_option_schema": [
                    _option(
                        "proxy",
                        "string",
                        required=False,
                        description="Optional HTTP proxy, for example http://127.0.0.1:7890",
                    ),
                ],
                "supports": {
                    "voice_list": True,
                    "voice_clone": False,
                    "preview": False,
                    "streaming": False,
                },
                "runtime_requirements": {
                    "python_modules": ["edge_tts"],
                    "system_tools": [],
                },
            },
            {
                "category": "tts",
                "provider": "qwen3",
                "display_name": "Qwen3 TTS",
                "kind": "local",
                "supported_models": [
                    "qwen3-custom-voice",
                    "qwen3-voice-design",
                    "qwen3-base",
                ],
                "default_model": "qwen3-custom-voice",
                "common_option_schema": [
                    _option("voice", "string", required=False, default="Vivian", description="Preset voice or speaker"),
                    _option("speed", "number", required=False, default=1.0, description="Synthesis speed"),
                    _option(
                        "language",
                        "string",
                        required=False,
                        default="auto",
                        enum=["auto", "zh", "en", "ja", "ko", "de", "fr", "ru", "pt", "es", "it"],
                        description="Target synthesis language",
                    ),
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
                "provider": "voxcpm2",
                "display_name": "VoxCPM2",
                "kind": "local",
                "supported_models": ["voxcpm2"],
                "default_model": "voxcpm2",
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
                "supported_models": llm_registry.list_models("deepseek"),
                "default_model": llm_registry.default_model("deepseek"),
                "common_option_schema": [],
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
                "supported_models": llm_registry.list_models("openai"),
                "default_model": llm_registry.default_model("openai"),
                "common_option_schema": [],
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
                    _option(
                        "vad_filter",
                        "boolean",
                        required=False,
                        default=False,
                        description="Filter non-speech with Silero VAD",
                    ),
                    _option(
                        "beam_size",
                        "integer",
                        required=False,
                        default=5,
                        min_value=1,
                        description="Beam size used for decoding",
                    ),
                    _option(
                        "initial_prompt",
                        "string",
                        required=False,
                        description="Optional transcription context prompt",
                    ),
                    _option(
                        "no_speech_threshold",
                        "number",
                        required=False,
                        default=0.9,
                        min_value=0.0,
                        max_value=1.0,
                        description="No-speech probability threshold",
                    ),
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
                "provider": "demucs",
                "display_name": "Demucs",
                "kind": "local",
                "supported_models": ["htdemucs", "htdemucs_ft", "htdemucs_6s"],
                "default_model": "htdemucs",
                "common_option_schema": [],
                "provider_option_schema": [],
                "supports": {
                    "multi_stem": True,
                },
            },
        ]
        for descriptor in descriptors:
            descriptor.setdefault(
                "runtime_requirements",
                {"python_modules": [], "system_tools": []},
            )
            for option in descriptor["provider_option_schema"]:
                option["advanced"] = True
        return descriptors


_service: CapabilityDescriptorService | None = None
_lock = threading.Lock()


def get_capability_descriptor_service() -> CapabilityDescriptorService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = CapabilityDescriptorService()
    return _service
