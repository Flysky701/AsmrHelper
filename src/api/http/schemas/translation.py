"""Pydantic schemas for translation endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic import model_validator


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


class LlmOperationRunRequest(BaseModel):
    operation: str = Field("translate", description="LLM derived operation name")
    input_path: str | None = Field(None, description="Optional path to text/subtitle file")
    content: str | None = Field(None, description="Inline content for the operation")
    output_path: str | None = Field(None, description="Path to save operation output")
    provider: str = Field("deepseek", description="LLM provider id")
    model: str | None = Field(None, description="Optional provider model")
    source_lang: str = Field("ja", description="Source language code")
    target_lang: str = Field("zh", description="Target language code")
    common_options: dict[str, Any] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)
    operation_options: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_input_source(self) -> "LlmOperationRunRequest":
        if not self.input_path and not self.content:
            raise ValueError("either input_path or content is required")
        return self


class LlmOperationRunResponse(BaseModel):
    operation: str
    items: list[str] = Field(default_factory=list)
    text: str = ""
    provider: str = ""
    source_lang: str = ""
    target_lang: str = ""
