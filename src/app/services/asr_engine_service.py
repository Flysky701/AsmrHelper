"""ASR engine registry and execution service."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from src.core.engines import AsrEngineRuntime

from ..dto import SubtitleSegment, TranscriptionResult
from ..errors import AppExecutionError, AppValidationError
from .capability_descriptor_service import CapabilityDescriptorService, get_capability_descriptor_service
from .execution_profile_builder import ExecutionProfileBuilder, get_execution_profile_builder


class AsrEngineService:
    """Resolve ASR providers through a stable registry facade."""

    def __init__(
        self,
        capability_service: CapabilityDescriptorService | None = None,
        profile_builder: ExecutionProfileBuilder | None = None,
        runtime: AsrEngineRuntime | None = None,
    ) -> None:
        self._capability_service = capability_service or get_capability_descriptor_service()
        self._profile_builder = profile_builder or get_execution_profile_builder()
        self._runtime = runtime or AsrEngineRuntime()

    def list_engines(self) -> list[dict[str, Any]]:
        return self._capability_service.list_descriptors(category="asr")

    def get_engine(self, engine_id: str) -> dict[str, Any]:
        return self._capability_service.get_descriptor("asr", engine_id)

    def list_supported_models(self, engine_id: str) -> list[str]:
        descriptor = self.get_engine(engine_id)
        return descriptor.get("supported_models", [])

    def get_default_model(self, engine_id: str) -> str:
        descriptor = self.get_engine(engine_id)
        return descriptor.get("default_model", "")

    def engine_supports(self, engine_id: str, feature: str) -> bool:
        descriptor = self.get_engine(engine_id)
        return bool(descriptor.get("supports", {}).get(feature, False))

    def transcribe_file(
        self,
        *,
        input_path: str,
        output_path: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        language: str = "ja",
        common_options: dict[str, Any] | None = None,
        provider_options: dict[str, Any] | None = None,
    ) -> TranscriptionResult:
        source_path = Path(input_path)
        if not source_path.exists():
            raise AppValidationError(f"input file does not exist: {input_path}")

        merged_common = dict(common_options or {})
        merged_common.setdefault("language", language)
        profile = self._profile_builder.build(
            category="asr",
            provider=provider,
            model=model,
            common_options=merged_common,
            provider_options=provider_options,
        )

        try:
            document = self._runtime.transcribe_file(
                input_path=str(source_path),
                output_path=output_path,
                profile=profile,
            )
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        segments = [
            SubtitleSegment(
                start=segment.start,
                end=segment.end,
                text=segment.text,
                language=segment.language,
                confidence=segment.confidence,
            )
            for segment in document.segments
        ]
        return TranscriptionResult(
            segments=segments,
            output_path=output_path,
            text="\n".join(segment.text for segment in segments if segment.text),
        )


_service: AsrEngineService | None = None
_lock = threading.Lock()


def get_asr_engine_service() -> AsrEngineService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = AsrEngineService()
    return _service
