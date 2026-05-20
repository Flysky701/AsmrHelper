"""LLM provider registry and derived operation service."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ..dto import TranslationResult
from ..errors import AppExecutionError, AppValidationError
from .capability_descriptor_service import CapabilityDescriptorService, get_capability_descriptor_service
from .execution_profile_builder import ExecutionProfileBuilder, get_execution_profile_builder


class LlmCapabilityService:
    """Resolve LLM providers through a stable registry facade."""

    def __init__(
        self,
        capability_service: CapabilityDescriptorService | None = None,
        profile_builder: ExecutionProfileBuilder | None = None,
    ) -> None:
        self._capability_service = capability_service or get_capability_descriptor_service()
        self._profile_builder = profile_builder or get_execution_profile_builder()

    def list_providers(self) -> list[dict[str, Any]]:
        return self._capability_service.list_descriptors(category="llm")

    def get_provider(self, provider_id: str) -> dict[str, Any]:
        return self._capability_service.get_descriptor("llm", provider_id)

    def list_supported_models(self, provider_id: str) -> list[str]:
        descriptor = self.get_provider(provider_id)
        return descriptor.get("supported_models", [])

    def get_default_model(self, provider_id: str) -> str:
        descriptor = self.get_provider(provider_id)
        return descriptor.get("default_model", "")

    def provider_supports(self, provider_id: str, feature: str) -> bool:
        descriptor = self.get_provider(provider_id)
        return bool(descriptor.get("supports", {}).get(feature, False))

    def translate_texts(
        self,
        *,
        texts: list[str],
        provider: str | None = None,
        model: str | None = None,
        source_lang: str = "ja",
        target_lang: str = "zh",
        common_options: dict[str, Any] | None = None,
        provider_options: dict[str, Any] | None = None,
        output_path: str | None = None,
    ) -> TranslationResult:
        profile = self._profile_builder.build(
            category="llm",
            provider=provider,
            model=model,
            common_options=common_options,
            provider_options=provider_options,
        )
        provider_id = profile["provider"]
        model_name = profile["model"]

        try:
            from src.core.translate import Translator

            translator = Translator(
                provider=provider_id,
                model=model_name,
                base_url=profile["provider_options"].get("base_url"),
            )
            items = translator.translate_batch(
                texts,
                source_lang=source_lang,
                target_lang=target_lang,
            )
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text("\n".join(items), encoding="utf-8")

        return TranslationResult(
            items=items,
            provider=provider_id,
            source_lang=source_lang,
            target_lang=target_lang,
        )


_service: LlmCapabilityService | None = None
_lock = threading.Lock()


def get_llm_capability_service() -> LlmCapabilityService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = LlmCapabilityService()
    return _service
