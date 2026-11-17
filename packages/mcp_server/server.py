"""Zero-dependency MCP JSON-RPC 2.0 stdio server (`python -m packages.mcp_server.server`)."""

from __future__ import annotations

from contextlib import redirect_stdout
import json
import sys
from typing import Any, BinaryIO, TextIO

from pydantic import ValidationError

from packages.mcp_server.protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JSONRPC_VERSION,
    MCP_PROTOCOL_VERSION,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JsonRpcErrorData,
    JsonRpcRequest,
    JsonRpcResponse,
    McpRpcException,
)
from packages.mcp_server.tools import McpToolRegistry


SERVER_NAME = "asmr-helper-mcp"
SERVER_VERSION = "2.0.0"


class McpStdioServer:
    """Standard Model Context Protocol (`2024-11-05`) JSON-RPC 2.0 server over stdio."""

    def __init__(
        self,
        *,
        registry: McpToolRegistry | None = None,
        server_name: str = SERVER_NAME,
        server_version: str = SERVER_VERSION,
    ) -> None:
        self.registry = registry or McpToolRegistry()
        self.server_name = server_name
        self.server_version = server_version
        self.initialized = False

    def handle_json_line(self, raw_line: str) -> dict[str, Any] | list[dict[str, Any]] | None:
        """Parse and handle one JSON-RPC text payload, returning a response dict (or None for notifications)."""
        text = raw_line.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return JsonRpcResponse(
                id=None,
                error=JsonRpcErrorData(code=PARSE_ERROR, message=f"Parse error: {exc.msg}"),
            ).to_wire_dict()

        if isinstance(parsed, list):
            if not parsed:
                return JsonRpcResponse(
                    id=None,
                    error=JsonRpcErrorData(code=INVALID_REQUEST, message="Empty JSON-RPC batch"),
                ).to_wire_dict()
            responses = []
            for item in parsed:
                resp = self.handle_message(item)
                if resp is not None:
                    responses.append(resp)
            return responses or None

        return self.handle_message(parsed)

    def handle_message(self, message: Any) -> dict[str, Any] | None:
        """Dispatch a decoded JSON-RPC 2.0 message object."""
        if not isinstance(message, dict):
            return JsonRpcResponse(
                id=None,
                error=JsonRpcErrorData(code=INVALID_REQUEST, message="JSON-RPC message must be an object"),
            ).to_wire_dict()

        raw_id = message.get("id") if isinstance(message.get("id"), (int, str)) or message.get("id") is None else None
        has_id = "id" in message

        try:
            req = JsonRpcRequest.model_validate(message)
        except ValidationError as exc:
            return JsonRpcResponse(
                id=raw_id,
                error=JsonRpcErrorData(
                    code=INVALID_REQUEST,
                    message="Invalid JSON-RPC 2.0 request",
                    data=exc.errors(),
                ),
            ).to_wire_dict()

        if req.jsonrpc != JSONRPC_VERSION or not req.method:
            return JsonRpcResponse(
                id=req.id,
                error=JsonRpcErrorData(code=INVALID_REQUEST, message="jsonrpc must be '2.0' with a method"),
            ).to_wire_dict()

        # Notifications (no 'id' member) never produce JSON-RPC responses
        if not has_id:
            if req.method == "notifications/initialized":
                self.initialized = True
            return None

        try:
            result = self._dispatch_method(req.method, req.params)
            return JsonRpcResponse(id=req.id, result=result).to_wire_dict()
        except McpRpcException as exc:
            return JsonRpcResponse(
                id=req.id,
                error=JsonRpcErrorData(code=exc.code, message=exc.message, data=exc.data),
            ).to_wire_dict()
        except Exception as exc:
            return JsonRpcResponse(
                id=req.id,
                error=JsonRpcErrorData(code=INTERNAL_ERROR, message=f"Internal server error: {exc}"),
            ).to_wire_dict()

    def _dispatch_method(
        self,
        method: str,
        params: dict[str, Any] | list[Any] | None,
    ) -> dict[str, Any]:
        if params is not None and not isinstance(params, dict):
            raise McpRpcException(INVALID_PARAMS, "MCP method params must be a JSON object")
        params_dict = params or {}

        if method == "initialize":
            self.initialized = True
            return {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {"listChanged": False},
                },
                "serverInfo": {
                    "name": self.server_name,
                    "version": self.server_version,
                },
            }

        if method == "ping":
            return {}

        if method == "tools/list":
            return {"tools": self.registry.list_tools()}

        if method == "tools/call":
            tool_name = params_dict.get("name")
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise McpRpcException(INVALID_PARAMS, "tools/call requires non-empty string 'name'")
            arguments = params_dict.get("arguments")
            if arguments is not None and not isinstance(arguments, dict):
                raise McpRpcException(INVALID_PARAMS, "tools/call 'arguments' must be an object")
            call_result = self.registry.call_tool(tool_name, arguments)
            return call_result.to_wire_dict()

        raise McpRpcException(METHOD_NOT_FOUND, f"Method not found: {method}")

    def serve_stdio(
        self,
        *,
        stdin: TextIO | BinaryIO | None = None,
        stdout: TextIO | BinaryIO | None = None,
        stderr: TextIO | None = None,
    ) -> int:
        """Run blocking JSON-RPC 2.0 stdio loop until EOF."""
        in_stream = stdin if stdin is not None else sys.stdin
        out_stream = stdout if stdout is not None else sys.stdout
        err_stream = stderr if stderr is not None else sys.stderr

        for stream in (in_stream, out_stream, err_stream):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                try:
                    reconfigure(encoding="utf-8")
                except Exception:
                    pass

        def _write_frame(payload_obj: dict[str, Any] | list[dict[str, Any]], *, content_length_framing: bool = False) -> None:
            serialized = json.dumps(payload_obj, ensure_ascii=False, separators=(",", ":"))
            if content_length_framing:
                raw_bytes = serialized.encode("utf-8")
                header = f"Content-Length: {len(raw_bytes)}\r\n\r\n"
                if hasattr(out_stream, "buffer"):
                    out_stream.buffer.write(header.encode("ascii") + raw_bytes)
                    out_stream.buffer.flush()
                else:
                    out_stream.write(header + serialized)  # type: ignore[arg-type]
                    out_stream.flush()
            else:
                out_stream.write(serialized + "\n")  # type: ignore[arg-type]
                out_stream.flush()

        # Redirect global `sys.stdout` to `err_stream` so internal library `print()` calls
        # (e.g., Mixer or SubtitleLoader) never corrupt the MCP JSON-RPC stdout pipe.
        with redirect_stdout(err_stream):
            while True:
                line = in_stream.readline()
                if not line:
                    break
                if isinstance(line, bytes):
                    line_str = line.decode("utf-8", errors="replace")
                else:
                    line_str = line

                stripped = line_str.strip()
                if not stripped:
                    continue

                if stripped.lower().startswith("content-length:"):
                    try:
                        length = int(stripped.split(":", 1)[1].strip())
                    except ValueError:
                        continue
                    # Consume remaining headers up to blank line
                    while True:
                        hdr = in_stream.readline()
                        if not hdr:
                            return 0
                        hdr_str = hdr.decode("utf-8", errors="replace") if isinstance(hdr, bytes) else hdr
                        if not hdr_str.strip():
                            break
                    if hasattr(in_stream, "buffer"):
                        body_bytes = in_stream.buffer.read(length)
                        body_str = body_bytes.decode("utf-8", errors="replace")
                    else:
                        body_raw = in_stream.read(length)
                        body_str = body_raw.decode("utf-8", errors="replace") if isinstance(body_raw, bytes) else body_raw
                    response = self.handle_json_line(body_str)
                    if response is not None:
                        _write_frame(response, content_length_framing=True)
                else:
                    response = self.handle_json_line(stripped)
                    if response is not None:
                        _write_frame(response, content_length_framing=False)

        return 0


def create_mcp_server(*, registry: McpToolRegistry | None = None) -> McpStdioServer:
    return McpStdioServer(registry=registry)


def main() -> int:
    server = create_mcp_server()
    return server.serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
