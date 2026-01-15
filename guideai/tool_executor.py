"""Tool Executor - Executes tool calls with permission enforcement.

Handles execution of MCP tools called by agents during work item execution.
Enforces write scope, internet access, and other permission policies.

See WORK_ITEM_EXECUTION_PLAN.md for full specification.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Union

from .telemetry import TelemetryClient
from .work_item_execution_contracts import (
    ExecutionPolicy,
    InternetAccessPolicy,
    PendingFileChange,
    PRExecutionContext,
    ToolCall,
    ToolResult,
    WriteScope,
)


logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _short_id(prefix: str) -> str:
    """Generate a short prefixed ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class ToolCategory(str, Enum):
    """Categories of tools for permission grouping."""
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    NETWORK = "network"
    FILESYSTEM = "filesystem"
    GIT = "git"
    BROWSER = "browser"
    SEARCH = "search"


@dataclass
class ToolDefinition:
    """Definition of an available tool."""
    name: str
    description: str
    input_schema: Dict[str, Any]
    category: ToolCategory
    requires_internet: bool = False
    is_write_operation: bool = False
    allowed_patterns: List[str] = field(default_factory=list)  # For filesystem tools
    handler: Optional[Callable[..., Any]] = None

    def to_schema_dict(self) -> Dict[str, Any]:
        """Convert to schema dict for LLM tool calling."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolPermissionError(Exception):
    """Raised when a tool call violates permissions."""

    def __init__(
        self,
        tool_name: str,
        reason: str,
        policy: Optional[str] = None,
    ) -> None:
        self.tool_name = tool_name
        self.reason = reason
        self.policy = policy
        super().__init__(f"Permission denied for {tool_name}: {reason}")


class ToolExecutionError(Exception):
    """Raised when a tool execution fails."""

    def __init__(
        self,
        tool_name: str,
        error: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.tool_name = tool_name
        self.error = error
        self.details = details or {}
        super().__init__(f"Tool {tool_name} failed: {error}")


class ToolRegistry:
    """Registry of available tools and their definitions."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        """Register default MCP tools."""
        # File reading tools
        self.register(ToolDefinition(
            name="read_file",
            description="Read contents of a file at the given path",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read"},
                    "start_line": {"type": "integer", "description": "Starting line number (1-indexed)"},
                    "end_line": {"type": "integer", "description": "Ending line number (1-indexed)"},
                },
                "required": ["path"],
            },
            category=ToolCategory.READ,
            is_write_operation=False,
        ))

        # File writing tools
        self.register(ToolDefinition(
            name="write_file",
            description="Write content to a file at the given path",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
            category=ToolCategory.WRITE,
            is_write_operation=True,
        ))

        self.register(ToolDefinition(
            name="edit_file",
            description="Edit a file by replacing content",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to edit"},
                    "old_content": {"type": "string", "description": "Content to replace"},
                    "new_content": {"type": "string", "description": "Replacement content"},
                },
                "required": ["path", "old_content", "new_content"],
            },
            category=ToolCategory.WRITE,
            is_write_operation=True,
        ))

        # Search tools
        self.register(ToolDefinition(
            name="grep_search",
            description="Search for pattern in files",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Pattern to search for"},
                    "path": {"type": "string", "description": "Path to search in"},
                    "include": {"type": "string", "description": "File pattern to include"},
                },
                "required": ["pattern"],
            },
            category=ToolCategory.SEARCH,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="file_search",
            description="Search for files by name pattern",
            input_schema={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "File name pattern"},
                    "path": {"type": "string", "description": "Path to search in"},
                },
                "required": ["pattern"],
            },
            category=ToolCategory.SEARCH,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="semantic_search",
            description="Semantic search for code or documentation",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
            category=ToolCategory.SEARCH,
            is_write_operation=False,
        ))

        # Directory tools
        self.register(ToolDefinition(
            name="list_dir",
            description="List contents of a directory",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to directory"},
                },
                "required": ["path"],
            },
            category=ToolCategory.READ,
            is_write_operation=False,
        ))

        # Terminal tools
        self.register(ToolDefinition(
            name="run_in_terminal",
            description="Run a command in the terminal",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Command to run"},
                    "cwd": {"type": "string", "description": "Working directory"},
                },
                "required": ["command"],
            },
            category=ToolCategory.EXECUTE,
            is_write_operation=True,
        ))

        # Git tools
        self.register(ToolDefinition(
            name="git_status",
            description="Get git status",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repository path"},
                },
            },
            category=ToolCategory.GIT,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="git_diff",
            description="Get git diff",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Repository path"},
                    "staged": {"type": "boolean", "description": "Show staged changes"},
                },
            },
            category=ToolCategory.GIT,
            is_write_operation=False,
        ))

        self.register(ToolDefinition(
            name="git_commit",
            description="Create a git commit",
            input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Commit message"},
                    "path": {"type": "string", "description": "Repository path"},
                },
                "required": ["message"],
            },
            category=ToolCategory.GIT,
            is_write_operation=True,
        ))

        # Web tools
        self.register(ToolDefinition(
            name="fetch_url",
            description="Fetch content from a URL",
            input_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"},
                },
                "required": ["url"],
            },
            category=ToolCategory.NETWORK,
            requires_internet=True,
            is_write_operation=False,
        ))

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool definition."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[ToolDefinition]:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def list_all(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def list_by_category(self, category: ToolCategory) -> List[str]:
        """List tool names by category."""
        return [
            name for name, tool in self._tools.items()
            if tool.category == category
        ]

    def get_schemas(self, names: Optional[List[str]] = None) -> Dict[str, Any]:
        """Get schemas for specified tools (or all if none specified)."""
        tools_to_include = names or list(self._tools.keys())
        return {
            name: self._tools[name].to_schema_dict()
            for name in tools_to_include
            if name in self._tools
        }


class PermissionChecker:
    """Checks tool permissions against execution policy."""

    def __init__(
        self,
        policy: ExecutionPolicy,
        registry: ToolRegistry,
    ) -> None:
        self._policy = policy
        self._registry = registry

    def check_permission(self, tool: ToolCall) -> None:
        """Check if a tool call is permitted.

        Raises ToolPermissionError if not permitted.
        """
        tool_def = self._registry.get(tool.tool_name)
        if not tool_def:
            logger.warning(f"Tool '{tool.tool_name}' not found in registry. Available tools: {self._registry.list_all()}")
            raise ToolPermissionError(
                tool_name=tool.tool_name,
                reason="Unknown tool",
            )

        # Check internet access
        if tool_def.requires_internet:
            if self._policy.internet_access == InternetAccessPolicy.DISABLED:
                raise ToolPermissionError(
                    tool_name=tool.tool_name,
                    reason="Internet access denied",
                    policy=f"internet_access={self._policy.internet_access.value}",
                )

        # Check write scope
        if tool_def.is_write_operation:
            if self._policy.write_scope == WriteScope.READ_ONLY:
                raise ToolPermissionError(
                    tool_name=tool.tool_name,
                    reason="Write operations not permitted",
                    policy=f"write_scope={self._policy.write_scope.value}",
                )

            # Check if path is within allowed scope
            if "path" in tool.tool_args:
                self._check_write_path(tool.tool_name, tool.tool_args["path"])

    def _check_write_path(self, tool_name: str, path: str) -> None:
        """Check if a write path is within allowed scope."""
        import os

        # Get allowed directories from policy
        allowed_dirs = self._policy.allowed_write_directories or []

        # For LOCAL_ONLY, LOCAL_AND_PR, check if path is within allowed directories
        if self._policy.write_scope in (WriteScope.LOCAL_ONLY, WriteScope.LOCAL_AND_PR):
            if not allowed_dirs:
                return  # No restrictions if no dirs specified

            abs_path = os.path.abspath(path)
            for allowed_dir in allowed_dirs:
                if abs_path.startswith(os.path.abspath(allowed_dir)):
                    return

            raise ToolPermissionError(
                tool_name=tool_name,
                reason=f"Path {path} outside allowed directories",
                policy=f"write_scope={self._policy.write_scope.value}, allowed={allowed_dirs}",
            )

        # PR_ONLY mode - writes will be captured for PR, not written locally
        elif self._policy.write_scope == WriteScope.PR_ONLY:
            # Allow the write - it will be intercepted and added to PR
            return

    def filter_available_tools(
        self,
        requested: Optional[List[str]] = None,
    ) -> List[str]:
        """Filter tools based on policy permissions.

        Returns list of tool names that are available given the policy.
        """
        all_tools = requested or self._registry.list_all()
        available = []

        for tool_name in all_tools:
            tool_def = self._registry.get(tool_name)
            if not tool_def:
                continue

            # Skip tools requiring internet if not allowed
            if tool_def.requires_internet:
                if self._policy.internet_access == InternetAccessPolicy.DISABLED:
                    continue

            # Skip write tools if not allowed
            if tool_def.is_write_operation:
                if self._policy.write_scope == WriteScope.READ_ONLY:
                    continue

            available.append(tool_name)

        return available


class ToolExecutor:
    """Executes tool calls with permission enforcement.

    Handles:
    - Permission checking against execution policy
    - Actual tool execution (via MCP or local handlers)
    - PR mode file change interception
    - Result formatting and error handling
    - Execution logging and metrics
    """

    def __init__(
        self,
        policy: ExecutionPolicy,
        *,
        registry: Optional[ToolRegistry] = None,
        mcp_client: Optional[Any] = None,
        telemetry: Optional[TelemetryClient] = None,
        project_root: Optional[str] = None,
        pr_context: Optional[PRExecutionContext] = None,
        current_phase: Optional[str] = None,
    ) -> None:
        """Initialize ToolExecutor.

        Args:
            policy: Execution policy for permission checks
            registry: Tool registry (defaults to standard registry)
            mcp_client: MCP client for remote tool execution
            telemetry: Telemetry client for metrics
            project_root: Project root directory for path resolution
            pr_context: PR execution context for file change accumulation
            current_phase: Current GEP phase (for PR change tracking)
        """
        self._policy = policy
        self._registry = registry or ToolRegistry()
        self._mcp_client = mcp_client
        self._telemetry = telemetry or TelemetryClient.noop()
        self._project_root = project_root
        self._pr_context = pr_context
        self._current_phase = current_phase or "unknown"

        self._permission_checker = PermissionChecker(policy, self._registry)

        # Execution history
        self._execution_history: List[ToolResult] = []

    def set_pr_context(self, pr_context: Optional[PRExecutionContext]) -> None:
        """Set the PR execution context for file change accumulation."""
        self._pr_context = pr_context

    def set_current_phase(self, phase: str) -> None:
        """Set the current GEP phase for change tracking."""
        self._current_phase = phase

    def _is_pr_mode(self) -> bool:
        """Check if we're in PR mode (should intercept file writes)."""
        return (
            self._pr_context is not None and
            self._policy.write_scope in (WriteScope.PR_ONLY, WriteScope.LOCAL_AND_PR)
        )

    def _should_write_locally(self) -> bool:
        """Check if we should also write files locally."""
        return self._policy.write_scope in (WriteScope.LOCAL_ONLY, WriteScope.LOCAL_AND_PR)

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call.

        Args:
            tool_call: The tool call to execute

        Returns:
            ToolResult with output or error
        """
        import time
        start_time = time.time()

        try:
            # Check permissions
            self._permission_checker.check_permission(tool_call)

            # Execute tool
            output = await self._execute_tool(tool_call)

            elapsed_ms = int((time.time() - start_time) * 1000)

            result = ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                output=output,
                success=True,
            )

            # Log telemetry
            self._telemetry.emit_event(
                event_type="tool.executed",
                payload={
                    "tool_name": tool_call.tool_name,
                    "success": True,
                    "elapsed_ms": elapsed_ms,
                },
            )

        except ToolPermissionError as e:
            result = ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                output="",
                success=False,
                error=str(e),
            )

            logger.warning(f"Permission denied: {e}")
            self._telemetry.emit_event(
                event_type="tool.permission_denied",
                payload={
                    "tool_name": tool_call.tool_name,
                    "reason": e.reason,
                    "policy": e.policy,
                },
            )

        except ToolExecutionError as e:
            result = ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                output="",
                success=False,
                error=str(e),
            )

            logger.error(f"Tool execution failed: {e}")
            self._telemetry.emit_event(
                event_type="tool.execution_failed",
                payload={
                    "tool_name": tool_call.tool_name,
                    "error": e.error,
                },
            )

        except Exception as e:
            result = ToolResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                output="",
                success=False,
                error=f"Unexpected error: {e}",
            )

            logger.exception(f"Unexpected tool error: {e}")
            self._telemetry.emit_event(
                event_type="tool.unexpected_error",
                payload={
                    "tool_name": tool_call.tool_name,
                    "error": str(e),
                },
            )

        self._execution_history.append(result)
        return result

    async def execute_batch(
        self,
        tool_calls: List[ToolCall],
        parallel: bool = False,
    ) -> List[ToolResult]:
        """Execute multiple tool calls.

        Args:
            tool_calls: List of tool calls to execute
            parallel: If True, execute in parallel (where safe)

        Returns:
            List of ToolResults
        """
        if parallel:
            # Execute in parallel (be careful with dependencies)
            tasks = [self.execute(tc) for tc in tool_calls]
            return await asyncio.gather(*tasks)
        else:
            # Execute sequentially
            results = []
            for tc in tool_calls:
                result = await self.execute(tc)
                results.append(result)
            return results

    async def _execute_tool(self, tool_call: ToolCall) -> str:
        """Execute a tool and return its output.

        This method dispatches to the appropriate handler:
        - MCP client for remote tools
        - Local handlers for built-in tools
        """
        tool_def = self._registry.get(tool_call.tool_name)
        if not tool_def:
            raise ToolExecutionError(
                tool_name=tool_call.tool_name,
                error="Unknown tool",
            )

        # Check for custom handler
        if tool_def.handler:
            try:
                result = await tool_def.handler(**tool_call.tool_args)
                return json.dumps(result) if not isinstance(result, str) else result
            except Exception as e:
                raise ToolExecutionError(
                    tool_name=tool_call.tool_name,
                    error=str(e),
                )

        # Use MCP client if available
        if self._mcp_client:
            try:
                result = await self._mcp_client.call_tool(
                    tool_call.tool_name,
                    tool_call.tool_args,
                )
                return result
            except Exception as e:
                raise ToolExecutionError(
                    tool_name=tool_call.tool_name,
                    error=f"MCP call failed: {e}",
                )

        # Fall back to local implementation
        return await self._execute_locally(tool_call)

    async def _execute_locally(self, tool_call: ToolCall) -> str:
        """Execute a tool locally (fallback when no MCP client)."""
        import os

        tool_name = tool_call.tool_name
        inputs = tool_call.tool_args

        # Implement basic tools locally
        if tool_name == "read_file":
            path = inputs.get("path", "")
            if self._project_root:
                path = os.path.join(self._project_root, path)

            try:
                with open(path, "r") as f:
                    content = f.read()

                # Handle line ranges
                start_line = inputs.get("start_line")
                end_line = inputs.get("end_line")
                if start_line or end_line:
                    lines = content.split("\n")
                    start = (start_line or 1) - 1
                    end = end_line or len(lines)
                    content = "\n".join(lines[start:end])

                return content
            except FileNotFoundError:
                raise ToolExecutionError(tool_name, f"File not found: {path}")
            except Exception as e:
                raise ToolExecutionError(tool_name, str(e))

        elif tool_name == "write_file":
            path = inputs.get("path", "")
            content = inputs.get("content", "")
            relative_path = path  # Keep original for PR context
            if self._project_root:
                path = os.path.join(self._project_root, path)

            result_parts = []

            # Intercept for PR mode - accumulate changes to PR context
            if self._is_pr_mode() and self._pr_context is not None:
                from datetime import datetime, timezone
                from guideai.work_item_execution_contracts import PendingFileChange

                # Add to PR context for later commit
                file_change = PendingFileChange(
                    path=relative_path,
                    content=content,
                    action="create",  # write_file always creates/overwrites
                    phase=self._current_phase,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                self._pr_context.pending_changes.append(file_change)
                result_parts.append(f"Staged {len(content)} characters for PR commit: {relative_path}")

            # Write locally if policy allows
            if self._should_write_locally():
                try:
                    # Create directory if needed
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    with open(path, "w") as f:
                        f.write(content)
                    result_parts.append(f"Wrote {len(content)} characters to {path}")
                except Exception as e:
                    raise ToolExecutionError(tool_name, str(e))

            if not result_parts:
                # This shouldn't happen - either PR mode or local write should be active
                raise ToolExecutionError(tool_name, "Write operation blocked by policy")

            return " | ".join(result_parts)

        elif tool_name == "list_dir":
            path = inputs.get("path", ".")
            if self._project_root:
                path = os.path.join(self._project_root, path)

            try:
                entries = os.listdir(path)
                return json.dumps(entries)
            except Exception as e:
                raise ToolExecutionError(tool_name, str(e))

        elif tool_name == "run_in_terminal":
            command = inputs.get("command", "")
            cwd = inputs.get("cwd", self._project_root)

            try:
                import subprocess
                result = subprocess.run(
                    command,
                    shell=True,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                output = result.stdout
                if result.returncode != 0:
                    output += f"\nError (exit {result.returncode}): {result.stderr}"
                return output
            except subprocess.TimeoutExpired:
                raise ToolExecutionError(tool_name, "Command timed out after 60s")
            except Exception as e:
                raise ToolExecutionError(tool_name, str(e))

        else:
            raise ToolExecutionError(
                tool_name=tool_name,
                error="No local implementation available",
            )

    def get_available_tools(self) -> List[str]:
        """Get list of tools available given the current policy."""
        return self._permission_checker.filter_available_tools()

    def get_tool_schemas(
        self,
        tools: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get schemas for available tools."""
        available = tools or self.get_available_tools()
        return self._registry.get_schemas(available)

    def get_execution_history(self) -> List[ToolResult]:
        """Get history of tool executions."""
        return list(self._execution_history)

    def update_policy(self, policy: ExecutionPolicy) -> None:
        """Update the execution policy."""
        self._policy = policy
        self._permission_checker = PermissionChecker(policy, self._registry)


# Factory function
def create_tool_executor(
    policy: ExecutionPolicy,
    *,
    mcp_client: Optional[Any] = None,
    project_root: Optional[str] = None,
) -> ToolExecutor:
    """Create a ToolExecutor with standard configuration."""
    return ToolExecutor(
        policy=policy,
        mcp_client=mcp_client,
        project_root=project_root,
    )
