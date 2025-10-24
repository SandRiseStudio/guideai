#!/usr/bin/env python3
"""
GuideAI MCP Server

Model Context Protocol server providing stdio-based JSON-RPC interface for GuideAI tools.
Enables AI assistants (Claude Desktop, Cursor, Cline) to authenticate and interact with
GuideAI via standardized MCP protocol.

Supported Tools:
- auth.deviceLogin - OAuth 2.0 device authorization flow
- auth.authStatus - Check authentication status
- auth.refreshToken - Refresh expired access tokens
- auth.logout - Revoke tokens and clear storage
- [Future] behaviors.*, workflows.*, runs.*, etc.

Usage:
    # Run standalone:
    python -m guideai.mcp_server

    # Configure in Claude Desktop (~/Library/Application Support/Claude/claude_desktop_config.json):
    {
      "mcpServers": {
        "guideai": {
          "command": "python",
          "args": ["-m", "guideai.mcp_server"]
        }
      }
    }

Protocol:
    - Input: JSON-RPC 2.0 requests via stdin
    - Output: JSON-RPC 2.0 responses via stdout
    - Logging: stderr (structured JSON logs)
"""

import asyncio
import json
import sys
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path

# MCP protocol types
from dataclasses import dataclass, asdict


@dataclass
class MCPRequest:
    """MCP JSON-RPC 2.0 request."""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    method: str = ""
    params: Optional[Dict[str, Any]] = None


@dataclass
class MCPResponse:
    """MCP JSON-RPC 2.0 response."""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


@dataclass
class MCPError:
    """MCP JSON-RPC error object."""
    code: int
    message: str
    data: Optional[Any] = None


class MCPServer:
    """
    GuideAI MCP server implementing JSON-RPC 2.0 over stdio.

    Handles tool discovery, capability negotiation, and tool execution
    for device flow authentication and future GuideAI capabilities.
    """

    # JSON-RPC error codes
    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    def __init__(self) -> None:
        """Initialize MCP server with tool handlers."""
        self._setup_logging()
        self._logger = logging.getLogger("guideai.mcp_server")

        # Import device flow handler
        try:
            from .mcp_device_flow import MCPDeviceFlowHandler
            self._device_flow_handler = MCPDeviceFlowHandler()
        except ImportError as e:
            self._logger.error(f"Failed to import device flow handler: {e}")
            self._device_flow_handler = None

        # Tool registry
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._load_tool_manifests()

        self._logger.info(f"GuideAI MCP Server initialized with {len(self._tools)} tools")

    def _setup_logging(self) -> None:
        """Configure structured logging to stderr."""
        logging.basicConfig(
            level=logging.INFO,
            format='{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            stream=sys.stderr,
        )

    def _load_tool_manifests(self) -> None:
        """Load MCP tool manifests from mcp/tools/ directory."""
        # Find mcp/tools directory relative to this file
        mcp_tools_dir = Path(__file__).parent.parent / "mcp" / "tools"

        if not mcp_tools_dir.exists():
            self._logger.warning(f"MCP tools directory not found: {mcp_tools_dir}")
            return

        # Load all .json tool manifests
        for manifest_path in mcp_tools_dir.glob("*.json"):
            try:
                with open(manifest_path) as f:
                    manifest = json.load(f)

                tool_name = manifest.get("name")
                if not tool_name:
                    self._logger.warning(f"Tool manifest missing 'name': {manifest_path}")
                    continue

                self._tools[tool_name] = manifest
                self._logger.info(f"Loaded tool: {tool_name}")

            except Exception as e:
                self._logger.error(f"Failed to load tool manifest {manifest_path}: {e}")

    async def handle_request(self, request_line: str) -> Optional[str]:
        """
        Handle a single JSON-RPC request.

        Args:
            request_line: JSON-RPC request as string

        Returns:
            JSON-RPC response as string, or None for notifications
        """
        try:
            request_data = json.loads(request_line)
        except json.JSONDecodeError as e:
            return self._error_response(
                None,
                self.PARSE_ERROR,
                f"Parse error: {e}",
            )

        request_id = request_data.get("id")
        method = request_data.get("method")
        params = request_data.get("params", {})

        self._logger.info(f"Received request: method={method}, id={request_id}")

        # Handle MCP protocol methods
        if method == "initialize":
            return self._handle_initialize(request_id, params)
        elif method == "tools/list":
            return self._handle_tools_list(request_id)
        elif method == "tools/call":
            return await self._handle_tools_call(request_id, params)
        elif method == "ping":
            return self._success_response(request_id, {"status": "ok"})
        else:
            return self._error_response(
                request_id,
                self.METHOD_NOT_FOUND,
                f"Method not found: {method}",
            )

    def _handle_initialize(self, request_id: Optional[str], params: Dict[str, Any]) -> str:
        """Handle MCP initialize request."""
        client_info = params.get("clientInfo", {})
        self._logger.info(f"Client connected: {client_info}")

        result = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": "guideai",
                "version": "0.1.0",
            },
            "capabilities": {
                "tools": {
                    "listChanged": False,  # Tool list is static for now
                },
            },
        }

        return self._success_response(request_id, result)

    def _handle_tools_list(self, request_id: Optional[str]) -> str:
        """Handle MCP tools/list request."""
        tools_list = []

        for tool_name, manifest in self._tools.items():
            tools_list.append({
                "name": tool_name,
                "description": manifest.get("description", ""),
                "inputSchema": manifest.get("inputSchema", {}),
            })

        result = {"tools": tools_list}
        return self._success_response(request_id, result)

    async def _handle_tools_call(self, request_id: Optional[str], params: Dict[str, Any]) -> str:
        """Handle MCP tools/call request."""
        tool_name = params.get("name")
        tool_params = params.get("arguments", {})

        if not tool_name:
            return self._error_response(
                request_id,
                self.INVALID_PARAMS,
                "Missing required parameter: name",
            )

        self._logger.info(f"Calling tool: {tool_name} with params: {tool_params}")

        # Route device flow tools
        if tool_name.startswith("auth."):
            if not self._device_flow_handler:
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    "Device flow handler not available",
                )

            try:
                result = await self._device_flow_handler.handle_tool_call(tool_name, tool_params)

                # Wrap result in MCP content format
                mcp_result = {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(result, indent=2),
                        }
                    ]
                }

                return self._success_response(request_id, mcp_result)

            except Exception as e:
                self._logger.error(f"Tool execution failed: {e}", exc_info=True)
                return self._error_response(
                    request_id,
                    self.INTERNAL_ERROR,
                    f"Tool execution failed: {str(e)}",
                )

        # Unknown tool prefix
        return self._error_response(
            request_id,
            self.METHOD_NOT_FOUND,
            f"Unknown tool: {tool_name}",
        )

    def _success_response(self, request_id: Optional[str], result: Any) -> str:
        """Build JSON-RPC success response."""
        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": result,
        }
        return json.dumps(response)

    def _error_response(self, request_id: Optional[str], code: int, message: str, data: Any = None) -> str:
        """Build JSON-RPC error response."""
        error = {
            "code": code,
            "message": message,
        }
        if data is not None:
            error["data"] = data

        response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": error,
        }
        return json.dumps(response)

    async def run(self) -> None:
        """Run MCP server main loop (stdio)."""
        self._logger.info("GuideAI MCP Server starting...")
        self._logger.info(f"Loaded {len(self._tools)} tools: {', '.join(self._tools.keys())}")

        try:
            # Read requests from stdin, write responses to stdout
            loop = asyncio.get_event_loop()

            while True:
                # Read one line (JSON-RPC request)
                request_line = await loop.run_in_executor(None, sys.stdin.readline)

                if not request_line:
                    self._logger.info("Stdin closed, shutting down")
                    break

                request_line = request_line.strip()
                if not request_line:
                    continue

                # Handle request
                response = await self.handle_request(request_line)

                if response:
                    # Write response to stdout
                    sys.stdout.write(response + "\n")
                    sys.stdout.flush()

        except KeyboardInterrupt:
            self._logger.info("Received interrupt, shutting down")
        except Exception as e:
            self._logger.error(f"Server error: {e}", exc_info=True)
            sys.exit(1)


async def main() -> None:
    """Main entry point for MCP server."""
    server = MCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
