"""Zero-dependency MCP JSON-RPC 2.0 server package for ASMR Helper."""

from packages.mcp_server.protocol import MCP_PROTOCOL_VERSION
from packages.mcp_server.server import McpStdioServer, create_mcp_server
from packages.mcp_server.tools import McpToolRegistry

__all__ = [
    "MCP_PROTOCOL_VERSION",
    "McpStdioServer",
    "McpToolRegistry",
    "create_mcp_server",
]
