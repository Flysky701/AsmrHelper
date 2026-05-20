"""Pydantic schemas for translation endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TranslateRequest(BaseModel):
    input_path: str = Field(..., description="Path to text/subtitle file")
    output_path: str | None = Field(None, description="Path to save translation output")
    provider: str = Field("deepseek", description="Translation provider (deepseek/openai)")
    source_lang: str = Field("ja", description="Source language code")
    target_lang: str = Field("zh", description="Target language code")


class TranslateResponse(BaseModel):
    items: list[str] = Field(default_factory=list)
    provider: str = ""
    source_lang: str = ""
    target_lang: str = ""


class LlmProviderDescriptorResponse(BaseModel):
    category: str
    provider: str
    display_name: str
    models: list[str] = Field(default_factory=list)
    common_options: list[dict[str, Any]] = Field(default_factory=list)
    provider_options: list[dict[str, Any]] = Field(default_factory=list)
    supports: dict[str, Any] = Field(default_factory=dict)


class LlmProviderListResponse(BaseModel):
    providers: list[LlmProviderDescriptorResponse] = Field(default_factory=list)
