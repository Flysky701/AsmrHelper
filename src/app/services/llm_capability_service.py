"""LLM provider registry and derived operation service."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from src.core.engines import LlmOperationRuntime

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
        runtime: LlmOperationRuntime | None = None,
    ) -> None:
        self._capability_service = capability_service or get_capability_descriptor_service()
        self._profile_builder = profile_builder or get_execution_profile_builder()
        self._runtime = runtime or LlmOperationRuntime()

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

        try:
            items = self._runtime.translate_texts(
                texts,
                profile=profile,
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

    def run_operation(
        self,
        *,
        operation: str,
        content: str,
        provider: str | None = None,
        model: str | None = None,
        source_lang: str = "ja",
        target_lang: str = "zh",
        common_options: dict[str, Any] | None = None,
        provider_options: dict[str, Any] | None = None,
        operation_options: dict[str, Any] | None = None,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        profile = self._profile_builder.build(
            category="llm",
            provider=provider,
            model=model,
            common_options=common_options,
            provider_options=provider_options,
        )
        provider_id = profile["provider"]
        operation_options = dict(operation_options or {})

        try:
            if operation == "translate":
                items = self._runtime.translate_texts(
                    [line for line in content.splitlines() if line.strip()],
                    profile=profile,
                    source_lang=source_lang,
                    target_lang=target_lang,
                )
                text = "\n".join(items)
            elif operation == "clean_script":
                text = self._runtime.clean_script(
                    text=content,
                    profile=profile,
                )
                items = [line for line in text.splitlines() if line.strip()]
            elif operation == "rewrite_text":
                text = self._runtime.rewrite_text(
                    text=content,
                    profile=profile,
                    prompt=str(operation_options.get("prompt", "")),
                )
                items = [text] if text else []
            else:
                raise AppValidationError(f"unsupported llm operation: {operation}")
        except AppValidationError:
            raise
        except ValueError as exc:
            raise AppValidationError(str(exc)) from exc
        except Exception as exc:
            raise AppExecutionError(str(exc)) from exc

        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(text, encoding="utf-8")

        return {
            "operation": operation,
            "items": items,
            "text": text,
            "provider": provider_id,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }


_service: LlmCapabilityService | None = None
_lock = threading.Lock()


def get_llm_capability_service() -> LlmCapabilityService:
    global _service
    if _service is None:
        with _lock:
            if _service is None:
                _service = LlmCapabilityService()
    return _service
