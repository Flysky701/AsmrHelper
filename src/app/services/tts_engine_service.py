"""TTS engine registry and execution service."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from src.core.engines import TtsEngineRuntime

from ..dto import SynthesisResult
from ..errors import AppExecutionError, AppValidationError
from .capability_descriptor_service import CapabilityDescriptorService, get_capability_descriptor_service
from .execution_profile_builder import ExecutionProfileBuilder, get_execution_profile_builder


class TtsEngineService:
    """Resolve TTS providers through a stable registry facade."""

    def __init__(
        self,
        capability_service: CapabilityDescriptorService | None = None,
        profile_builder: ExecutionProfileBuilder | None = None,
        runtime: TtsEngineRuntime | None = None,
    ) -> None:
        self._capability_service = capability_service or get_capability_descriptor_service()
        self._profile_builder = profile_builder or get_execution_profile_builder()
        self._runtime = runtime or TtsEngineRuntime()

    def list_engines(self) -> list[dict[str, Any]]:
        return self._capability_service.list_descriptors(category="tts")

    def get_engine(self, engine_id: str) -> dict[str, Any]:
        return self._capability_service.get_descriptor("tts", engine_id)

    def list_supported_models(self, engine_id: str) -> list[str]:
        descriptor = self.get_engine(engine_id)
        return descriptor.get("supported_models", [])

    def get_default_voice(self, engine_id: str) -> str:
        descriptor = self.get_engine(engine_id)
        for opt in descriptor.get("common_option_schema", []):
            if opt.get("name") == "voice":
                return str(opt.get("default", ""))
        return ""

    def engine_supports(self, engine_id: str, feature: str) -> bool:
        descriptor = self.get_engine(engine_id)
        return bool(descriptor.get("supports", {}).get(feature, False))

    def synthesize_file(
        self,
        input_path: str,
        output_path: str,
        provider: str | None = None,
        voice: str | None = None,
    ) -> SynthesisResult:
        """Convenience wrapper: read text file and synthesize."""
        source_path = Path(input_path)
        if not source_path.exists():
            raise AppValidationError(f"input file does not exist: {input_path}")
        text = source_path.read_text(encoding="utf-8")
        common_options: dict[str, Any] = {}
        if voice is not None:
            common_options["voice"] = voice
        return self.synthesize_text(
            text=text,
            output_path=output_path,
            provider=provider,
            common_options=common_options if common_options else None,
        )

    def synthesize_text(
        self,
        *,
        text: str,
        output_path: str,
        provider: str | None = None,
        model: str | None = None,
        common_options: dict[str, Any] | None = None,
        provider_options: dict[str, Any] | None = None,
    ) -> SynthesisResult:
        profile = self._profile_builder.build(
            category="tts",
            provider=provider,
            model=model,
            common_options=common_options,
            provider_options=provider_options,
        )
        engine_id = profile["provider"]
        voice = str(profile["common_options"].get("voice", ""))

        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            result_path = self._runtime.synthesize_text(
                text=text,
                output_path=output_path,
                profile=profile,
            )
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        return SynthesisResult(
            engine=engine_id,
            voice=voice,
            output_path=result_path,
        )


_service: TtsEngineService | None = None
_lock = threading.Lock()


def get_tts_engine_service() -> TtsEngineService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = TtsEngineService()
    return _service
