"""Strict public Graph V2 request values; internal task snapshots are never client fields."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.orchestration.pipeline.graph_validation import validate_graph


GraphLanguage = Literal["ja", "zh", "en"]
GraphNodeKind = Literal["separate", "asr", "align", "translate", "tts", "mix", "export", "audio_export"]


class GraphValueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class GraphNodeRequest(GraphValueRequest):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    kind: GraphNodeKind
    provider: str = Field(min_length=1)
    model: str | None = None
    source_lang: GraphLanguage | None = None
    target_lang: GraphLanguage | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    provider_options: dict[str, Any] = Field(default_factory=dict)


class GraphInputSlotRequest(GraphValueRequest):
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
    type: Literal["audio", "subtitle"]
    label: str = Field(min_length=1, max_length=100)
    language: GraphLanguage | None = None


class GraphSlotSourceRequest(GraphValueRequest):
    kind: Literal["slot"]
    slot_id: str


class GraphNodeSourceRequest(GraphValueRequest):
    kind: Literal["node"]
    node_id: str
    port: str


class GraphTargetRequest(GraphValueRequest):
    node_id: str
    port: str


class GraphEdgeRequest(GraphValueRequest):
    source: GraphSlotSourceRequest | GraphNodeSourceRequest = Field(discriminator="kind")
    target: GraphTargetRequest


class GraphOutputRequest(GraphTargetRequest):
    label: str | None = Field(default=None, max_length=100)


class GraphDefinitionRequest(GraphValueRequest):
    version: Literal[2]
    nodes: list[GraphNodeRequest] = Field(min_length=1, max_length=64)
    edges: list[GraphEdgeRequest] = Field(max_length=256)
    input_slots: list[GraphInputSlotRequest] = Field(max_length=64)
    outputs: list[GraphOutputRequest] = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_definition(self):
        validate_graph(self.model_dump())
        return self


class GraphMaterialBindingRequest(GraphValueRequest):
    path: str = Field(min_length=1)
    language: GraphLanguage | None = None
    language_confirmed: bool = False
    audio_path: str | None = None
    pair_confirmed: bool = False
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")


class GraphExecutionProfileRequest(GraphValueRequest):
    version: Literal[2]
    graph: GraphDefinitionRequest
    bindings: dict[str, GraphMaterialBindingRequest] = Field(default_factory=dict)
