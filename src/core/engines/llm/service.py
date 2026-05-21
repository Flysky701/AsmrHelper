"""Core LLM operation runtime."""

from __future__ import annotations

from typing import Any

from .registry import get_llm_registry


class LlmOperationRuntime:
    """Execute derived LLM operations through the LLM registry."""

    def __init__(self, registry=None) -> None:
        self._registry = registry or get_llm_registry()

    def _get_translator(self, profile: dict[str, Any]):
        provider_id = str(profile["provider"])
        model_name = str(profile.get("model", ""))
        provider_options = dict(profile.get("provider_options", {}))
        return self._registry.get(
            provider_id,
            model=model_name,
            base_url=provider_options.get("base_url"),
        )

    def translate_texts(
        self,
        *,
        texts: list[str],
        profile: dict[str, Any],
        source_lang: str,
        target_lang: str,
    ) -> list[str]:
        translator = self._get_translator(profile)
        return translator.translate_batch(
            texts,
            source_lang=source_lang,
            target_lang=target_lang,
        )

    def clean_script(
        self,
        *,
        text: str,
        profile: dict[str, Any],
    ) -> str:
        from src.core.script_to_subtitle.llm_processor import LLMProcessor

        translator = self._get_translator(profile)
        processor = LLMProcessor(translator=translator)
        return processor.clean_script(text)

    def rewrite_text(
        self,
        *,
        text: str,
        profile: dict[str, Any],
        prompt: str = "",
    ) -> str:
        translator = self._get_translator(profile)
        system_prompt = prompt.strip() or (
            "你是一个文本润色助手。保持原意，不要扩写，只做清晰、自然、简洁的重写。"
        )
        response = translator.get_client().chat.completions.create(
            model=translator.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            max_tokens=4096,
            temperature=0.2,
        )
        if not response.choices or not response.choices[0].message.content:
            raise ValueError("llm rewrite returned empty response")
        return response.choices[0].message.content.strip()
