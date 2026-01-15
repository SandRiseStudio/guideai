"""Execution Wiring - Connects AgentExecutionLoop with WorkItemExecutionService.

This module provides factory functions to create and wire together the execution
components needed for agent work item execution:

- WorkItemExecutionService: Orchestrates work item execution
- AgentExecutionLoop: Drives phase-by-phase GEP execution
- AgentLLMClient: Handles LLM calls for agent reasoning
- ToolExecutor: Executes tool calls with permission enforcement

Usage during API/MCP initialization:

    from guideai.execution_wiring import wire_execution_service

    service = wire_execution_service(
        dsn=execution_dsn,
        board_service=board_service,
        run_service=run_service,
        telemetry=telemetry,
    )

See WORK_ITEM_EXECUTION_PLAN.md for full specification.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

from .run_service import RunService
from .services.board_service import BoardService
from .task_cycle_service import TaskCycleService
from .telemetry import TelemetryClient
from .work_item_execution_contracts import ExecutionPolicy

logger = logging.getLogger(__name__)


def _create_credential_resolver_from_store(
    credential_store: Any,
) -> Callable[[str, Optional[str], Optional[str]], Optional[str]]:
    """Create a credential resolver function that uses the CredentialStore.

    This returns a function that can resolve API keys for providers using
    the CredentialStore's credential resolution logic (project -> org -> platform).

    Args:
        credential_store: CredentialStore instance from WorkItemExecutionService

    Returns:
        Credential resolver function (provider, project_id, org_id) -> api_key
    """
    def resolver(
        provider: str,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve API key for a provider using CredentialStore."""
        # Map provider name to a model_id from that provider to use resolution
        provider_to_model = {
            "anthropic": "claude-sonnet-4-5",
            "openai": "gpt-4o",
            "openrouter": "claude-sonnet-4-5",  # Use any model for OpenRouter
        }

        model_id = provider_to_model.get(provider)
        if not model_id:
            return None

        result = credential_store.get_credential_for_model(model_id, project_id, org_id)
        if result:
            api_key, source, is_byok = result
            logger.debug(f"Resolved credential for {provider}: source={source}, byok={is_byok}")
            return api_key
        return None

    return resolver


# Type alias for credential resolvers - supports both simple (provider) and
# context-aware (provider, project_id, org_id) signatures
CredentialResolver = Callable[..., Optional[str]]


def wire_execution_service(
    *,
    dsn: Optional[str] = None,
    board_service: Optional[BoardService] = None,
    run_service: Optional[RunService] = None,
    task_cycle_service: Optional[TaskCycleService] = None,
    telemetry: Optional[TelemetryClient] = None,
    credential_resolver: Optional[CredentialResolver] = None,
    tool_registry: Optional[Dict[str, Any]] = None,
) -> Any:
    """Create and wire a fully-configured WorkItemExecutionService.

    This function creates all the execution components and wires them together:

    1. Creates WorkItemExecutionService
    2. Creates AgentExecutionLoop
    3. Creates AgentLLMClient
    4. Wires: WorkItemExecutionService.set_execution_loop(loop)
    5. Wires: AgentExecutionLoop.set_llm_client(client)

    Note: ToolExecutor is created per-execution with the specific ExecutionPolicy,
    so it's not pre-wired here but set during each execution run.

    Args:
        dsn: PostgreSQL connection string for execution state
        board_service: Service for board/work item operations (shared instance)
        run_service: Service for run tracking (shared instance)
        task_cycle_service: Service for GEP phase management
        telemetry: Telemetry client for event emission
        credential_resolver: Function to resolve LLM API keys
        tool_registry: Registry of tool schemas for LLM calls

    Returns:
        Fully wired WorkItemExecutionService instance
    """
    from .agent_execution_loop import AgentExecutionLoop
    from .agent_llm_client import AgentLLMClient
    from .work_item_execution_service import WorkItemExecutionService

    logger.info("Wiring execution service components...")

    # Create the task cycle service if not provided
    if task_cycle_service is None:
        from .storage.postgres_pool import PostgresPool
        pool = PostgresPool(dsn) if dsn else None
        task_cycle_service = TaskCycleService(pool=pool)

    # Create the run service if not provided
    if run_service is None:
        run_service = RunService()

    # Create the main service
    service = WorkItemExecutionService(
        dsn=dsn,
        board_service=board_service,
        run_service=run_service,
        task_cycle_service=task_cycle_service,
        telemetry=telemetry,
    )
    logger.info("Created WorkItemExecutionService")

    # Create credential resolver from service's credential store if not provided
    if credential_resolver is None and service._credential_store is not None:
        credential_resolver = _create_credential_resolver_from_store(service._credential_store)
        logger.info("Created credential resolver from WorkItemExecutionService's CredentialStore")

    # Create the LLM client
    llm_client = AgentLLMClient(
        credential_resolver=credential_resolver,
        tool_registry=tool_registry,
        telemetry=telemetry,
    )
    logger.info("Created AgentLLMClient")

    # Create the execution loop
    execution_loop = AgentExecutionLoop(
        run_service=run_service,
        task_cycle_service=task_cycle_service,
        llm_client=llm_client,
        telemetry=telemetry,
    )
    logger.info("Created AgentExecutionLoop")

    # Wire them together
    service.set_execution_loop(execution_loop)
    logger.info("Wired AgentExecutionLoop into WorkItemExecutionService")

    logger.info("Execution service wiring complete")
    return service


def wire_execution_loop(
    *,
    run_service: Optional[RunService] = None,
    task_cycle_service: Optional[TaskCycleService] = None,
    telemetry: Optional[TelemetryClient] = None,
    credential_resolver: Optional[CredentialResolver] = None,
    tool_registry: Optional[Dict[str, Any]] = None,
) -> Any:
    """Create and wire a standalone AgentExecutionLoop with LLM client.

    Use this when you need just the execution loop without the full service,
    for example when the WorkItemExecutionService is already created.

    Args:
        run_service: Service for run tracking
        task_cycle_service: Service for GEP phase management
        telemetry: Telemetry client
        credential_resolver: Function to resolve LLM API keys
        tool_registry: Registry of tool schemas

    Returns:
        AgentExecutionLoop with LLM client wired
    """
    from .agent_execution_loop import AgentExecutionLoop
    from .agent_llm_client import AgentLLMClient

    # Create LLM client
    llm_client = AgentLLMClient(
        credential_resolver=credential_resolver,
        tool_registry=tool_registry,
        telemetry=telemetry,
    )

    # Create execution loop with LLM client
    execution_loop = AgentExecutionLoop(
        run_service=run_service or RunService(),
        task_cycle_service=task_cycle_service or TaskCycleService(),
        llm_client=llm_client,
        telemetry=telemetry,
    )

    return execution_loop


def create_tool_executor_for_run(
    policy: ExecutionPolicy,
    *,
    mcp_client: Optional[Any] = None,
    project_root: Optional[str] = None,
    telemetry: Optional[TelemetryClient] = None,
) -> Any:
    """Create a ToolExecutor for a specific execution run.

    ToolExecutor is created per-run because it needs the ExecutionPolicy
    which varies by work item, agent, and project settings.

    Args:
        policy: Execution policy for this run (permissions, write scope, etc.)
        mcp_client: MCP client for remote tool execution
        project_root: Project root directory for path resolution
        telemetry: Telemetry client

    Returns:
        ToolExecutor configured for the run
    """
    from .tool_executor import ToolExecutor

    return ToolExecutor(
        policy=policy,
        mcp_client=mcp_client,
        project_root=project_root,
        telemetry=telemetry,
    )
