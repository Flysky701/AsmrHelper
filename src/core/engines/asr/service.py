"""Core ASR engine runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.resources.model_reference import resolve_model_reference
from src.core.subtitles import SubtitleDocument, SubtitleSegment

from .registry import get_asr_registry


def _resolve_model_name(provider: str, model_id: str) -> str:
    """Convert a catalog model_id to the upstream name the engine library expects.

    Supports both catalog IDs (e.g. 'fun-asr-nano-2512') and upstream names
    (e.g. 'FunAudioLLM/Fun-ASR-Nano-2512'). If the model_id is not found in
    the catalog, it is returned as-is for backwards compatibility.
    """
    if not model_id:
        return model_id

    resolved = resolve_model_reference(model_id)
    if resolved != model_id:
        return resolved

    if provider == "faster_whisper":
        prefix = "faster-whisper-"
        return model_id[len(prefix) :] if model_id.startswith(prefix) else model_id

    return model_id


class AsrEngineRuntime:
    """Execute ASR transcription against the legacy recognizer."""

    def __init__(self, registry=None, *, runtime_router=None, enable_runtime_routing: bool = True) -> None:
        self._registry = registry or get_asr_registry()
        self._runtime_router = runtime_router
        # Injected registries are primarily used by in-process tests and
        # extensions. Keep those calls local unless a router is explicitly
        # supplied; the application path uses the default runtime router.
        if enable_runtime_routing and self._runtime_router is None and registry is None:
            from src.core.runtime import get_runtime_router

            self._runtime_router = get_runtime_router()

    def transcribe_file(
        self,
        *,
        input_path: str,
        output_path: str | None,
        profile: dict[str, Any],
    ) -> SubtitleDocument:
        source_path = Path(input_path)
        if not source_path.exists():
            raise ValueError(f"input file does not exist: {input_path}")

        common_options = dict(profile.get("common_options", {}))
        provider_options = dict(profile.get("provider_options", {}))
        provider = str(profile.get("provider", "faster_whisper"))

        if self._runtime_router and self._runtime_router.asr_profile(provider):
            result = self._runtime_router.transcribe_file(
                {
                    "input_path": str(source_path),
                    "output_path": output_path,
                    "profile": profile,
                }
            )
            return self._document_from_worker_result(result, output_path=output_path)

        recognizer = self._registry.get(
            provider,
            **self._build_provider_kwargs(
                provider=provider,
                model=str(profile.get("model", "")),
                common_options=common_options,
                provider_options=provider_options,
            ),
        )
        entries = recognizer.recognize(str(source_path), output_path)
        segments = [
            SubtitleSegment(
                start=float(entry.get("start", 0.0)),
                end=float(entry.get("end", 0.0)),
                text=str(entry.get("text", "")),
            )
            for entry in entries
        ]
        return SubtitleDocument(
            segments=segments,
            language=str(common_options.get("language", "ja")),
            format="srt" if output_path else "",
            source_path=output_path or "",
        )

    @staticmethod
    def _document_from_worker_result(
        result: dict[str, Any], *, output_path: str | None
    ) -> SubtitleDocument:
        payload = dict(result.get("document") or {})
        segments = [
            SubtitleSegment(
                start=float(item.get("start", 0.0)),
                end=float(item.get("end", 0.0)),
                text=str(item.get("text", "")),
                language=str(item.get("language", "")),
                confidence=float(item.get("confidence", 0.0)),
            )
            for item in payload.get("segments", [])
            if isinstance(item, dict)
        ]
        return SubtitleDocument(
            segments=segments,
            language=str(payload.get("language", "")),
            format=str(payload.get("format", "")),
            source_path=str(payload.get("source_path") or output_path or ""),
            warnings=[str(item) for item in payload.get("warnings", [])],
        )

    @staticmethod
    def _build_provider_kwargs(
        *,
        provider: str,
        model: str,
        common_options: dict[str, Any],
        provider_options: dict[str, Any],
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model_size": _resolve_model_name(provider, model),
            "language": str(common_options.get("language", "ja")),
        }

        if provider == "faster_whisper":
            supported = (
                "vad_filter",
                "beam_size",
                "initial_prompt",
                "no_speech_threshold",
            )
            for key in supported:
                if key in provider_options:
                    kwargs[key] = provider_options[key]
            return kwargs

        if provider == "fun_asr":
            supported = (
                "hub",
                "device",
                "batch_size",
                "sentence_timestamp",
                "trust_remote_code",
                "remote_code_path",
                "hotwords",
                "vad_model",
                "vad_kwargs",
            )
            for key in supported:
                if key in provider_options:
                    kwargs[key] = provider_options[key]
            return kwargs

        if provider == "qwen3_asr":
            supported = (
                "device_map",
                "dtype",
                "attn_implementation",
                "max_inference_batch_size",
                "max_new_tokens",
                "forced_aligner",
                "forced_aligner_kwargs",
                "return_time_stamps",
                "context",
            )
            for key in supported:
                if key in provider_options:
                    kwargs[key] = provider_options[key]
            return kwargs

        kwargs.update(provider_options)
        return kwargs
