"""Pure Pydantic v2 data structures for MCP JSON-RPC 2.0 over stdio."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


MCP_PROTOCOL_VERSION = "2024-11-05"
JSONRPC_VERSION = "2.0"

# Standard JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class McpRpcException(Exception):
    """Structured JSON-RPC 2.0 protocol exception."""

    def __init__(self, code: int, message: str, data: Any | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class JsonRpcErrorData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: int
    message: str
    data: Any | None = None

    def to_wire_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.data is not None:
            payload["data"] = self.data
        return payload


class JsonRpcRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    jsonrpc: str
    id: int | str | None = None
    method: str
    params: dict[str, Any] | list[Any] | None = None

    @property
    def is_notification(self) -> bool:
        return "id" not in self.model_fields_set


class JsonRpcResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jsonrpc: str = JSONRPC_VERSION
    id: int | str | None = None
    result: Any | None = None
    error: JsonRpcErrorData | None = None

    def to_wire_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"jsonrpc": self.jsonrpc, "id": self.id}
        if self.error is not None:
            payload["error"] = self.error.to_wire_dict()
        else:
            payload["result"] = self.result
        return payload


class McpToolDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    inputSchema: dict[str, Any]


class McpTextContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"] = "text"
    text: str


class McpToolCallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: list[McpTextContent] = Field(default_factory=list)
    structuredContent: dict[str, Any] | None = None
    isError: bool = False

    def to_wire_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "content": [item.model_dump() for item in self.content],
            "isError": self.isError,
        }
        if self.structuredContent is not None:
            payload["structuredContent"] = self.structuredContent
        return payload
