"""Agent Execution Loop - Phase-by-phase GEP execution engine.

The AgentExecutionLoop drives execution through the 8 GEP phases:
PLANNING → CLARIFYING → ARCHITECTING → EXECUTING → TESTING → FIXING → VERIFYING → COMPLETING

For each phase, it:
1. Reads current phase from TaskCycle
2. Composes prompt with phase-specific instructions + tools schema
3. Calls AgentLLMClient for LLM response
4. Executes tool calls (with permission checks)
5. Appends RunStep entries to RunService
6. Advances TaskCycle to next phase when gate satisfied

See WORK_ITEM_EXECUTION_PLAN.md for full specification.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .action_contracts import Actor
from .agent_registry_contracts import Agent, AgentVersion
from .multi_tenant.board_contracts import WorkItem
from .run_contracts import Run, RunStatus, RunStep
from .run_service import RunService
from .task_cycle_contracts import (
    CyclePhase,
    CycleResponse,
    GateType,
    PHASE_GATES,
    TransitionPhaseRequest,
    TriggerType,
    VALID_TRANSITIONS,
)
from .task_cycle_service import TaskCycleService
from .telemetry import TelemetryClient
from .work_item_execution_contracts import (
    AgentResponse,
    ClarificationQuestion,
    ExecutionPolicy,
    ExecutionState,
    ExecutionStep,
    ExecutionStepType,
    GatePolicyType,
    InternetAccessPolicy,
    PendingFileChange,
    PRCommitStrategy,
    PRExecutionContext,
    ToolCall,
    ToolResult,
    WriteScope,
    generate_pr_branch_name,
)


logger = logging.getLogger(__name__)


def _now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _short_id(prefix: str) -> str:
    """Generate a short prefixed ID."""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass
class PhaseContext:
    """Context for executing a single GEP phase."""
    phase: CyclePhase
    work_item: WorkItem
    agent: Agent
    agent_version: Optional[AgentVersion]
    playbook: Dict[str, Any]
    available_tools: List[str]
    messages: List[Dict[str, Any]] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PhaseResult:
    """Result of executing a single GEP phase."""
    success: bool
    phase: CyclePhase
    outputs: Dict[str, Any]
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_results: List[ToolResult] = field(default_factory=list)
    clarification_questions: List[ClarificationQuestion] = field(default_factory=list)
    error: Optional[str] = None
    should_advance: bool = True
    next_phase: Optional[CyclePhase] = None


class AgentExecutionLoop:
    """Drives agent execution through GEP phases.

    This class manages the execution loop for a work item, iterating through
    GEP phases until completion or failure. It handles:

    - Phase-specific prompt composition
    - LLM calls via AgentLLMClient
    - Tool execution with permission enforcement
    - Phase gate satisfaction and transitions
    - Run step logging
    - PR creation and file change accumulation (for PR mode)
    """

    # Maximum iterations per phase to prevent infinite loops
    MAX_PHASE_ITERATIONS = 50

    # Maximum total iterations across all phases
    MAX_TOTAL_ITERATIONS = 200

    def __init__(
        self,
        *,
        run_service: Optional[RunService] = None,
        task_cycle_service: Optional[TaskCycleService] = None,
        llm_client: Optional[Any] = None,  # AgentLLMClient
        tool_executor: Optional[Any] = None,  # ToolExecutor
        telemetry: Optional[TelemetryClient] = None,
        github_service: Optional[Any] = None,  # GitHubService
    ) -> None:
        """Initialize AgentExecutionLoop.

        Args:
            run_service: Service for run tracking
            task_cycle_service: Service for GEP phase management
            llm_client: Client for LLM calls
            tool_executor: Executor for tool calls
            telemetry: Telemetry client
            github_service: Service for GitHub operations (PR creation, commits)
        """
        self._run_service = run_service or RunService()
        self._task_cycle_service = task_cycle_service or TaskCycleService()
        self._llm_client = llm_client
        self._tool_executor = tool_executor
        self._telemetry = telemetry or TelemetryClient.noop()
        self._github_service = github_service

        # PR execution context (set during run() if in PR mode)
        self._pr_context: Optional[PRExecutionContext] = None

        # Phase handlers
        self._phase_handlers: Dict[CyclePhase, Callable] = {
            CyclePhase.PLANNING: self._execute_planning_phase,
            CyclePhase.CLARIFYING: self._execute_clarifying_phase,
            CyclePhase.ARCHITECTING: self._execute_architecting_phase,
            CyclePhase.EXECUTING: self._execute_executing_phase,
            CyclePhase.TESTING: self._execute_testing_phase,
            CyclePhase.FIXING: self._execute_fixing_phase,
            CyclePhase.VERIFYING: self._execute_verifying_phase,
            CyclePhase.COMPLETING: self._execute_completing_phase,
        }

    def set_llm_client(self, client: Any) -> None:
        """Set the LLM client (avoids circular import)."""
        self._llm_client = client

    def set_tool_executor(self, executor: Any) -> None:
        """Set the tool executor (avoids circular import)."""
        self._tool_executor = executor

    def set_github_service(self, service: Any) -> None:
        """Set the GitHub service (avoids circular import)."""
        self._github_service = service

    def set_pr_context(self, context: PRExecutionContext) -> None:
        """Set the PR execution context for PR mode."""
        self._pr_context = context

    @property
    def pr_context(self) -> Optional[PRExecutionContext]:
        """Get the current PR execution context."""
        return self._pr_context

    async def run(
        self,
        *,
        run_id: str,
        cycle_id: str,
        work_item: WorkItem,
        agent: Agent,
        agent_version: Optional[AgentVersion],
        exec_policy: ExecutionPolicy,
        model_id: str,
        user_id: str,
        org_id: Optional[str],
        project_id: Optional[str],
    ) -> Dict[str, Any]:
        """Run the execution loop until completion.

        This is the main entry point for the execution loop. It drives the agent
        through all GEP phases until reaching COMPLETING or encountering an error.

        Args:
            run_id: Run ID for tracking
            cycle_id: TaskCycle ID for phase management
            work_item: Work item being executed
            agent: Agent performing execution
            agent_version: Active agent version with playbook
            exec_policy: Execution policy (permissions, models, gates)
            model_id: Selected model for LLM calls
            user_id: User who initiated execution
            org_id: Organization ID
            project_id: Project ID

        Returns:
            Dict with execution results including outputs, errors, etc.
        """
        logger.info(f"Starting execution loop for run {run_id}, work item {work_item.item_id}")

        # Update run status to running
        self._run_service.update_progress(
            run_id,
            status=RunStatus.RUNNING,
            metadata={"phase": CyclePhase.PLANNING.value},
        )

        # Load playbook from agent version
        playbook = self._load_playbook(agent_version)

        # Track execution state
        total_iterations = 0
        phase_outputs: Dict[CyclePhase, Dict[str, Any]] = {}
        all_tool_calls: List[ToolCall] = []

        try:
            while total_iterations < self.MAX_TOTAL_ITERATIONS:
                # Get current phase from TaskCycle
                cycle = self._task_cycle_service.get_cycle(cycle_id)
                if not cycle:
                    raise RuntimeError(f"TaskCycle {cycle_id} not found")

                current_phase = cycle.current_phase

                # Check for terminal states
                if current_phase == CyclePhase.COMPLETING:
                    # Execute completing phase for final outputs
                    result = await self._execute_phase(
                        phase=current_phase,
                        run_id=run_id,
                        cycle_id=cycle_id,
                        work_item=work_item,
                        agent=agent,
                        agent_version=agent_version,
                        exec_policy=exec_policy,
                        model_id=model_id,
                        playbook=playbook,
                        previous_outputs=phase_outputs,
                        project_id=project_id,
                        org_id=org_id,
                    )
                    phase_outputs[current_phase] = result.outputs

                    # Mark run as completed
                    self._run_service.update_progress(
                        run_id,
                        status=RunStatus.COMPLETED,
                        outputs=self._merge_outputs(phase_outputs),
                        metadata={"phase": CyclePhase.COMPLETING.value},
                    )

                    logger.info(f"Execution completed for run {run_id}")
                    return {
                        "status": "completed",
                        "phase_outputs": phase_outputs,
                        "tool_calls": all_tool_calls,
                    }

                # Execute current phase
                result = await self._execute_phase(
                    phase=current_phase,
                    run_id=run_id,
                    cycle_id=cycle_id,
                    work_item=work_item,
                    agent=agent,
                    agent_version=agent_version,
                    exec_policy=exec_policy,
                    model_id=model_id,
                    playbook=playbook,
                    previous_outputs=phase_outputs,
                    project_id=project_id,
                    org_id=org_id,
                )

                # Track outputs and tool calls
                phase_outputs[current_phase] = result.outputs
                all_tool_calls.extend(result.tool_calls)

                # Handle phase failure
                if not result.success:
                    logger.error(f"Phase {current_phase.value} failed: {result.error}")

                    # Check if this is a clarification request
                    if result.clarification_questions:
                        # Transition to CLARIFYING phase
                        self._task_cycle_service.transition_phase(
                            cycle_id=cycle_id,
                            to_phase=CyclePhase.CLARIFYING,
                            user_id=user_id,
                            gate_satisfied=True,  # Automatic gate for clarification
                        )
                        continue

                    # Actual failure - update run status
                    self._run_service.update_progress(
                        run_id,
                        status=RunStatus.FAILED,
                        error=result.error,
                        metadata={
                            "phase": current_phase.value,
                            "step_type": ExecutionStepType.ERROR.value,
                        },
                    )
                    return {
                        "status": "failed",
                        "error": result.error,
                        "phase": current_phase.value,
                        "phase_outputs": phase_outputs,
                    }

                # Check if phase should advance
                if not result.should_advance:
                    total_iterations += 1
                    continue

                # Determine next phase
                next_phase = result.next_phase or self._get_next_phase(current_phase, result)

                if not next_phase:
                    logger.error(f"No valid next phase from {current_phase.value}")
                    break

                # Check gate policy for transition
                gate_satisfied = self._check_gate_satisfaction(
                    current_phase=current_phase,
                    next_phase=next_phase,
                    exec_policy=exec_policy,
                    result=result,
                )

                if not gate_satisfied:
                    # Gate requires approval - pause execution
                    logger.info(
                        f"Gate not satisfied for {current_phase.value} -> {next_phase.value}, "
                        "waiting for approval"
                    )

                    self._run_service.update_progress(
                        run_id,
                        status=RunStatus.PENDING,  # Waiting for approval
                        current_step=f"Waiting for {self._get_gate_type(current_phase).value} approval",
                        metadata={
                            "phase": current_phase.value,
                            "step_type": ExecutionStepType.GATE_WAITING.value,
                        },
                    )

                    return {
                        "status": "paused",
                        "phase": current_phase.value,
                        "waiting_for": self._get_gate_type(current_phase).value,
                        "phase_outputs": phase_outputs,
                    }

                # Transition to next phase
                self._task_cycle_service.transition_phase(
                    TransitionPhaseRequest(
                        cycle_id=cycle_id,
                        target_phase=next_phase,
                        triggered_by=user_id,
                        trigger_type=TriggerType.AUTO,
                        notes=f"Gate satisfied for {current_phase.value}",
                        approval_granted=True,
                    )
                )

                # Update run progress
                progress = self._calculate_progress(next_phase)
                self._run_service.update_progress(
                    run_id,
                    progress=progress,
                    current_step=f"Phase: {next_phase.value}",
                    metadata={
                        "phase": next_phase.value,
                        "step_type": ExecutionStepType.PHASE_START.value,
                    },
                )

                total_iterations += 1

            # Max iterations reached
            logger.error(f"Max iterations reached for run {run_id}")
            self._run_service.update_progress(
                run_id,
                status=RunStatus.FAILED,
                error="Maximum iterations exceeded",
                metadata={
                    "phase": current_phase.value if "current_phase" in locals() else "unknown",
                    "step_type": ExecutionStepType.ERROR.value,
                },
            )

            return {
                "status": "failed",
                "error": "Maximum iterations exceeded",
                "phase_outputs": phase_outputs,
            }

        except Exception as e:
            logger.exception(f"Execution loop error for run {run_id}: {e}")
            self._run_service.update_progress(
                run_id,
                status=RunStatus.FAILED,
                error=str(e),
                metadata={
                    "phase": "unknown",
                    "step_type": ExecutionStepType.ERROR.value,
                },
            )
            raise

    async def _execute_phase(
        self,
        *,
        phase: CyclePhase,
        run_id: str,
        cycle_id: str,
        work_item: WorkItem,
        agent: Agent,
        agent_version: Optional[AgentVersion],
        exec_policy: ExecutionPolicy,
        model_id: str,
        playbook: Dict[str, Any],
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> PhaseResult:
        """Execute a single GEP phase.

        This method handles the execution of one phase, including:
        - Building phase context
        - Calling phase-specific handler
        - Logging run steps
        - Handling tool calls

        Args:
            phase: The GEP phase to execute
            run_id: Run ID for tracking
            cycle_id: TaskCycle ID
            work_item: Work item being executed
            agent: Executing agent
            agent_version: Agent version with playbook
            exec_policy: Execution policy
            model_id: Model ID for LLM calls
            playbook: Loaded playbook configuration
            previous_outputs: Outputs from previous phases
            project_id: Project context for BYOK credential resolution
            org_id: Org context for BYOK credential resolution

        Returns:
            PhaseResult with success status, outputs, and next phase
        """
        logger.info(f"Executing phase {phase.value} for run {run_id}")

        # Record phase start
        step = ExecutionStep(
            step_id=_short_id("step"),
            step_type=ExecutionStepType.PHASE_TRANSITION,
            phase=phase.value,
            timestamp=_now_iso(),
            content={"entering_phase": True},
        )
        self._add_run_step(run_id, step)

        # Build phase context
        context = PhaseContext(
            phase=phase,
            work_item=work_item,
            agent=agent,
            agent_version=agent_version,
            playbook=playbook,
            available_tools=self._get_available_tools(phase, exec_policy),
            outputs=dict(previous_outputs.get(phase, {})),
        )

        try:
            # Get phase handler
            handler = self._phase_handlers.get(phase)
            if not handler:
                raise RuntimeError(f"No handler for phase {phase.value}")

            # Execute phase
            result = await handler(
                context=context,
                run_id=run_id,
                cycle_id=cycle_id,
                exec_policy=exec_policy,
                model_id=model_id,
                previous_outputs=previous_outputs,
                project_id=project_id,
                org_id=org_id,
            )

            # Record phase completion
            step.completed_at = _now_iso()
            step.outputs = result.outputs

            return result

        except Exception as e:
            logger.exception(f"Phase {phase.value} error: {e}")
            return PhaseResult(
                success=False,
                phase=phase,
                outputs={},
                error=str(e),
                should_advance=False,
            )

    # =========================================================================
    # Phase Handlers
    # =========================================================================

    async def _execute_planning_phase(
        self,
        context: PhaseContext,
        run_id: str,
        cycle_id: str,
        exec_policy: ExecutionPolicy,
        model_id: str,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> PhaseResult:
        """Execute the PLANNING phase.

        In this phase, the agent:
        1. Analyzes the work item requirements
        2. Creates an execution plan
        3. Identifies needed clarifications

        Gate: planning_approved (requires approval unless auto-approved)
        """
        if not self._llm_client:
            logger.warning(f"No LLM client configured for run {run_id} - skipping LLM call in PLANNING phase")
            return PhaseResult(
                success=True,
                phase=CyclePhase.PLANNING,
                outputs={"plan": "No LLM client configured, using default plan"},
                should_advance=True,
                next_phase=CyclePhase.ARCHITECTING,
            )

        logger.info(f"PLANNING phase: LLM client configured, building prompt for run {run_id}")

        # Build planning prompt
        prompt = self._build_planning_prompt(context)
        logger.info(f"PLANNING phase: Built prompt with {len(prompt)} messages, calling LLM model {model_id}")

        # Call LLM with project/org context for BYOK credential resolution
        try:
            response = await self._llm_client.call(
                model_id=model_id,
                messages=prompt,
                tools=context.available_tools,
                project_id=project_id,
                org_id=org_id,
            )
            logger.info(f"PLANNING phase: LLM call completed for run {run_id}")
        except Exception as e:
            logger.error(f"PLANNING phase: LLM call failed for run {run_id}: {e}")
            raise

        # Parse response
        if response.needs_clarification:
            return PhaseResult(
                success=False,
                phase=CyclePhase.PLANNING,
                outputs={},
                clarification_questions=response.clarification_questions,
                should_advance=False,
            )

        # Execute any tool calls
        tool_results = await self._execute_tool_calls(
            response.tool_calls,
            run_id,
            exec_policy,
        )

        # Extract plan from response
        plan = self._extract_plan(response, tool_results)

        return PhaseResult(
            success=True,
            phase=CyclePhase.PLANNING,
            outputs={"plan": plan},
            tool_calls=response.tool_calls,
            tool_results=tool_results,
            should_advance=True,
            next_phase=CyclePhase.ARCHITECTING,
        )

    async def _execute_clarifying_phase(
        self,
        context: PhaseContext,
        run_id: str,
        cycle_id: str,
        exec_policy: ExecutionPolicy,
        model_id: str,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> PhaseResult:
        """Execute the CLARIFYING phase.

        In this phase, the agent waits for human clarification before proceeding.
        The execution pauses until clarification is provided.

        Gate: clarification_provided (auto-satisfied when clarification received)
        """
        # Check if clarification has been provided (via comments/updates)
        clarification = self._check_for_clarification(context.work_item, run_id)

        if not clarification:
            # Still waiting for clarification
            return PhaseResult(
                success=True,
                phase=CyclePhase.CLARIFYING,
                outputs={"waiting_for": "clarification"},
                should_advance=False,
            )

        # Clarification received - proceed to next phase
        # Determine which phase to return to based on what triggered clarification
        return_phase = self._get_return_phase_after_clarification(context, previous_outputs)

        return PhaseResult(
            success=True,
            phase=CyclePhase.CLARIFYING,
            outputs={"clarification": clarification},
            should_advance=True,
            next_phase=return_phase,
        )

    async def _execute_architecting_phase(
        self,
        context: PhaseContext,
        run_id: str,
        cycle_id: str,
        exec_policy: ExecutionPolicy,
        model_id: str,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> PhaseResult:
        """Execute the ARCHITECTING phase.

        In this phase, the agent:
        1. Designs the solution architecture
        2. Identifies files to create/modify
        3. Plans the implementation approach

        Gate: architecture_approved (requires approval unless auto-approved)
        """
        if not self._llm_client:
            return PhaseResult(
                success=True,
                phase=CyclePhase.ARCHITECTING,
                outputs={"architecture": "No LLM client configured, using default architecture"},
                should_advance=True,
                next_phase=CyclePhase.EXECUTING,
            )

        # Get plan from previous phase
        plan = previous_outputs.get(CyclePhase.PLANNING, {}).get("plan", "")

        # Build architecting prompt
        prompt = self._build_architecting_prompt(context, plan)

        # Call LLM with project/org context for BYOK credential resolution
        response = await self._llm_client.call(
            model_id=model_id,
            messages=prompt,
            tools=context.available_tools,
            project_id=project_id,
            org_id=org_id,
        )

        # Handle clarifications
        if response.needs_clarification:
            return PhaseResult(
                success=False,
                phase=CyclePhase.ARCHITECTING,
                outputs={},
                clarifications=response.clarifications,
                should_advance=False,
            )

        # Execute any tool calls (e.g., reading files to understand codebase)
        tool_results = await self._execute_tool_calls(
            response.tool_calls,
            run_id,
            exec_policy,
        )

        # Extract architecture from response
        architecture = self._extract_architecture(response, tool_results)

        return PhaseResult(
            success=True,
            phase=CyclePhase.ARCHITECTING,
            outputs={"architecture": architecture},
            tool_calls=response.tool_calls,
            tool_results=tool_results,
            should_advance=True,
            next_phase=CyclePhase.EXECUTING,
        )

    async def _execute_executing_phase(
        self,
        context: PhaseContext,
        run_id: str,
        cycle_id: str,
        exec_policy: ExecutionPolicy,
        model_id: str,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> PhaseResult:
        """Execute the EXECUTING phase.

        In this phase, the agent:
        1. Implements the planned changes
        2. Creates/modifies files
        3. Runs necessary commands

        Gate: None (autonomous execution)
        """
        if not self._llm_client:
            return PhaseResult(
                success=True,
                phase=CyclePhase.EXECUTING,
                outputs={"changes": "No LLM client configured, no changes made"},
                should_advance=True,
                next_phase=CyclePhase.TESTING,
            )

        # Get architecture from previous phase
        architecture = previous_outputs.get(CyclePhase.ARCHITECTING, {}).get("architecture", "")

        # Build executing prompt
        prompt = self._build_executing_prompt(context, architecture)

        # Iterative execution loop within this phase
        max_iterations = 10
        iteration = 0
        all_changes: List[Dict[str, Any]] = []
        all_tool_calls: List[ToolCall] = []

        while iteration < max_iterations:
            # Call LLM with project/org context for BYOK credential resolution
            response = await self._llm_client.call(
                model_id=model_id,
                messages=prompt,
                tools=context.available_tools,
                project_id=project_id,
                org_id=org_id,
            )

            # Handle clarifications
            if response.needs_clarification:
                return PhaseResult(
                    success=False,
                    phase=CyclePhase.EXECUTING,
                    outputs={"partial_changes": all_changes},
                    clarifications=response.clarifications,
                    tool_calls=all_tool_calls,
                    should_advance=False,
                )

            # Execute tool calls
            tool_results = await self._execute_tool_calls(
                response.tool_calls,
                run_id,
                exec_policy,
            )

            all_tool_calls.extend(response.tool_calls)

            # Track changes
            for result in tool_results:
                if result.success and result.tool_name in ("file_write", "file_edit"):
                    all_changes.append({
                        "file": result.outputs.get("file"),
                        "action": result.tool_name,
                    })

            # Check if agent signals completion
            if response.phase_complete or not response.tool_calls:
                break

            # Add tool results to prompt for next iteration
            prompt = self._add_tool_results_to_prompt(prompt, response, tool_results)
            iteration += 1

        return PhaseResult(
            success=True,
            phase=CyclePhase.EXECUTING,
            outputs={"changes": all_changes, "files_changed": len(all_changes)},
            tool_calls=all_tool_calls,
            should_advance=True,
            next_phase=CyclePhase.TESTING,
        )

    async def _execute_testing_phase(
        self,
        context: PhaseContext,
        run_id: str,
        cycle_id: str,
        exec_policy: ExecutionPolicy,
        model_id: str,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> PhaseResult:
        """Execute the TESTING phase.

        In this phase, the agent:
        1. Runs tests for changed code
        2. Validates functionality
        3. Identifies any failures

        Gate: None (autonomous execution) - transitions to FIXING if tests fail
        """
        if not self._llm_client:
            return PhaseResult(
                success=True,
                phase=CyclePhase.TESTING,
                outputs={"tests_passed": True},
                should_advance=True,
                next_phase=CyclePhase.VERIFYING,
            )

        # Get changes from previous phase
        changes = previous_outputs.get(CyclePhase.EXECUTING, {}).get("changes", [])

        # Build testing prompt
        prompt = self._build_testing_prompt(context, changes)

        # Call LLM with project/org context for BYOK credential resolution
        response = await self._llm_client.call(
            model_id=model_id,
            messages=prompt,
            tools=context.available_tools,
            project_id=project_id,
            org_id=org_id,
        )

        # Execute tool calls (run tests)
        tool_results = await self._execute_tool_calls(
            response.tool_calls,
            run_id,
            exec_policy,
        )

        # Check test results
        tests_passed = self._check_test_results(tool_results)

        if tests_passed:
            return PhaseResult(
                success=True,
                phase=CyclePhase.TESTING,
                outputs={"tests_passed": True, "test_results": [r.to_dict() for r in tool_results]},
                tool_calls=response.tool_calls,
                tool_results=tool_results,
                should_advance=True,
                next_phase=CyclePhase.VERIFYING,
            )
        else:
            # Tests failed - go to FIXING phase
            return PhaseResult(
                success=True,
                phase=CyclePhase.TESTING,
                outputs={"tests_passed": False, "test_results": [r.to_dict() for r in tool_results]},
                tool_calls=response.tool_calls,
                tool_results=tool_results,
                should_advance=True,
                next_phase=CyclePhase.FIXING,
            )

    async def _execute_fixing_phase(
        self,
        context: PhaseContext,
        run_id: str,
        cycle_id: str,
        exec_policy: ExecutionPolicy,
        model_id: str,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> PhaseResult:
        """Execute the FIXING phase.

        In this phase, the agent:
        1. Analyzes test failures
        2. Fixes identified issues
        3. Returns to TESTING phase

        Gate: None (autonomous execution)
        """
        if not self._llm_client:
            return PhaseResult(
                success=True,
                phase=CyclePhase.FIXING,
                outputs={"fixes_applied": 0},
                should_advance=True,
                next_phase=CyclePhase.TESTING,
            )

        # Get test results from previous phase
        test_results = previous_outputs.get(CyclePhase.TESTING, {}).get("test_results", [])

        # Build fixing prompt
        prompt = self._build_fixing_prompt(context, test_results)

        # Call LLM with project/org context for BYOK credential resolution
        response = await self._llm_client.call(
            model_id=model_id,
            messages=prompt,
            tools=context.available_tools,
            project_id=project_id,
            org_id=org_id,
        )

        # Execute tool calls (apply fixes)
        tool_results = await self._execute_tool_calls(
            response.tool_calls,
            run_id,
            exec_policy,
        )

        fixes_applied = sum(1 for r in tool_results if r.success)

        return PhaseResult(
            success=True,
            phase=CyclePhase.FIXING,
            outputs={"fixes_applied": fixes_applied},
            tool_calls=response.tool_calls,
            tool_results=tool_results,
            should_advance=True,
            next_phase=CyclePhase.TESTING,  # Return to testing after fixing
        )

    async def _execute_verifying_phase(
        self,
        context: PhaseContext,
        run_id: str,
        cycle_id: str,
        exec_policy: ExecutionPolicy,
        model_id: str,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> PhaseResult:
        """Execute the VERIFYING phase.

        In this phase, the agent:
        1. Performs final verification
        2. Runs linting, type checking
        3. Prepares PR/commit

        Gate: verification_approved (requires approval unless auto-approved)
        """
        if not self._llm_client:
            return PhaseResult(
                success=True,
                phase=CyclePhase.VERIFYING,
                outputs={"verified": True},
                should_advance=True,
                next_phase=CyclePhase.COMPLETING,
            )

        # Build verification prompt
        prompt = self._build_verifying_prompt(context, previous_outputs)

        # Call LLM with project/org context for BYOK credential resolution
        response = await self._llm_client.call(
            model_id=model_id,
            messages=prompt,
            tools=context.available_tools,
            project_id=project_id,
            org_id=org_id,
        )

        # Execute tool calls (lint, type check, etc.)
        tool_results = await self._execute_tool_calls(
            response.tool_calls,
            run_id,
            exec_policy,
        )

        # Check verification results
        all_passed = all(r.success for r in tool_results) if tool_results else True

        return PhaseResult(
            success=True,
            phase=CyclePhase.VERIFYING,
            outputs={"verified": all_passed, "verification_results": [r.to_dict() for r in tool_results]},
            tool_calls=response.tool_calls,
            tool_results=tool_results,
            should_advance=all_passed,
            next_phase=CyclePhase.COMPLETING if all_passed else CyclePhase.FIXING,
        )

    async def _execute_completing_phase(
        self,
        context: PhaseContext,
        run_id: str,
        cycle_id: str,
        exec_policy: ExecutionPolicy,
        model_id: str,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> PhaseResult:
        """Execute the COMPLETING phase.

        In this phase, the agent:
        1. Creates final summary
        2. Generates PR if configured (commits pending changes and creates PR)
        3. Updates work item status

        Gate: None (terminal phase)
        """
        # Generate completion summary
        summary = self._generate_completion_summary(context, previous_outputs)

        outputs = {
            "summary": summary,
            "completed_at": _now_iso(),
        }

        # Create PR if in PR mode and have pending changes
        if exec_policy.write_scope in (WriteScope.PR_ONLY, WriteScope.LOCAL_AND_PR):
            pr_result = await self._create_pull_request_if_needed(
                context=context,
                run_id=run_id,
                summary=summary,
                previous_outputs=previous_outputs,
                project_id=project_id,
                org_id=org_id,
            )
            if pr_result:
                outputs["pr_url"] = pr_result.get("pr_url")
                outputs["pr_number"] = pr_result.get("pr_number")
                outputs["branch_name"] = pr_result.get("branch_name")
                outputs["files_changed"] = pr_result.get("files_changed", 0)
                outputs["commit_sha"] = pr_result.get("commit_sha")

        return PhaseResult(
            success=True,
            phase=CyclePhase.COMPLETING,
            outputs=outputs,
            should_advance=False,  # Terminal phase
        )

    # =========================================================================
    # PR Creation Methods
    # =========================================================================

    async def _create_pull_request_if_needed(
        self,
        context: PhaseContext,
        run_id: str,
        summary: str,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a pull request if in PR mode and have pending changes.

        This method:
        1. Checks if there are pending file changes
        2. Commits all pending changes to the PR branch
        3. Creates a pull request with execution summary as body
        4. Records the PR creation as an execution step

        Args:
            context: Phase context with work item info
            run_id: Run ID for logging
            summary: Execution summary for PR body
            previous_outputs: Outputs from previous phases
            project_id: Project ID for credential resolution
            org_id: Org ID for credential resolution

        Returns:
            Dict with PR details (pr_url, pr_number, etc.) or None if no PR needed
        """
        if not self._pr_context:
            logger.debug(f"No PR context for run {run_id}, skipping PR creation")
            return None

        if not self._pr_context.has_pending_changes():
            logger.info(f"No pending changes for run {run_id}, skipping PR creation")
            return None

        if not self._github_service:
            logger.warning(f"No GitHub service configured for run {run_id}, cannot create PR")
            return None

        try:
            # Import here to avoid circular dependency
            from .services.github_service import FileChange

            # Convert pending changes to FileChange objects
            file_changes: List[FileChange] = []
            for change in self._pr_context.pending_changes:
                file_changes.append(FileChange(
                    path=change.path,
                    content=change.content if change.action != "delete" else None,
                    encoding=change.encoding,
                    action=change.action,
                ))

            # Build PR title and body
            work_item_title = context.work_item.title
            pr_title = f"[GuideAI] {work_item_title}"
            pr_body = self._build_pr_body(
                context=context,
                summary=summary,
                previous_outputs=previous_outputs,
            )

            # Create the PR
            logger.info(
                f"Creating PR for run {run_id}: {len(file_changes)} file(s) "
                f"on branch {self._pr_context.branch_name}"
            )

            pr_result = self._github_service.create_pull_request(
                repo=self._pr_context.repo,
                title=pr_title,
                head_branch=self._pr_context.branch_name,
                files=file_changes,
                project_id=project_id or self._pr_context.project_id,
                org_id=org_id or self._pr_context.org_id,
                body=pr_body,
                base_branch=self._pr_context.base_branch,
                commit_message=f"feat: {work_item_title}",
                draft=self._pr_context.draft_pr,
                labels=self._pr_context.labels or ["guideai", "automated"],
            )

            if pr_result.success:
                # Update PR context
                self._pr_context.pr_number = pr_result.pr_number
                self._pr_context.pr_url = pr_result.pr_url
                self._pr_context.last_commit_sha = pr_result.commit_sha
                self._pr_context.commit_count += 1
                self._pr_context.branch_created = True

                # Clear pending changes since they're committed
                committed_changes = self._pr_context.clear_pending_changes()

                # Record PR creation step
                step = ExecutionStep(
                    step_id=_short_id("step"),
                    step_type=ExecutionStepType.PR_CREATED,
                    phase=CyclePhase.COMPLETING.value,
                    timestamp=_now_iso(),
                    content={
                        "pr_url": pr_result.pr_url,
                        "pr_number": pr_result.pr_number,
                        "branch": self._pr_context.branch_name,
                        "files_changed": pr_result.files_changed,
                        "commit_sha": pr_result.commit_sha,
                    },
                )
                self._add_run_step(run_id, step)

                logger.info(
                    f"PR created for run {run_id}: {pr_result.pr_url} "
                    f"({pr_result.files_changed} files)"
                )

                return {
                    "pr_url": pr_result.pr_url,
                    "pr_number": pr_result.pr_number,
                    "branch_name": self._pr_context.branch_name,
                    "files_changed": pr_result.files_changed,
                    "commit_sha": pr_result.commit_sha,
                }
            else:
                logger.error(f"Failed to create PR for run {run_id}: {pr_result.error}")
                # Record error step
                step = ExecutionStep(
                    step_id=_short_id("step"),
                    step_type=ExecutionStepType.ERROR,
                    phase=CyclePhase.COMPLETING.value,
                    timestamp=_now_iso(),
                    content={
                        "error": f"PR creation failed: {pr_result.error}",
                        "branch": self._pr_context.branch_name,
                    },
                )
                self._add_run_step(run_id, step)
                return None

        except Exception as e:
            logger.exception(f"Error creating PR for run {run_id}: {e}")
            return None

    async def _commit_pending_changes_for_phase(
        self,
        phase: CyclePhase,
        run_id: str,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Commit pending changes at the end of a phase (for per-phase commit strategy).

        Only commits if:
        1. PR context exists with per-phase strategy
        2. There are pending changes
        3. GitHub service is available

        Args:
            phase: The phase that just completed
            run_id: Run ID for logging
            project_id: Project ID for credential resolution
            org_id: Org ID for credential resolution

        Returns:
            Dict with commit details or None
        """
        if not self._pr_context:
            return None

        if self._pr_context.commit_strategy != PRCommitStrategy.PER_PHASE:
            return None

        if not self._pr_context.has_pending_changes():
            return None

        if not self._github_service:
            logger.warning(f"No GitHub service for per-phase commit in run {run_id}")
            return None

        try:
            from .services.github_service import FileChange

            # Convert pending changes
            file_changes = [
                FileChange(
                    path=c.path,
                    content=c.content if c.action != "delete" else None,
                    encoding=c.encoding,
                    action=c.action,
                )
                for c in self._pr_context.pending_changes
            ]

            # Commit to branch
            commit_message = f"Phase {phase.value}: {len(file_changes)} file(s) changed"

            result = self._github_service.commit_to_branch(
                repo=self._pr_context.repo,
                branch=self._pr_context.branch_name,
                message=commit_message,
                files=file_changes,
                project_id=project_id or self._pr_context.project_id,
                org_id=org_id or self._pr_context.org_id,
                create_branch=not self._pr_context.branch_created,
                base_branch=self._pr_context.base_branch,
            )

            if result.success:
                self._pr_context.branch_created = True
                self._pr_context.last_commit_sha = result.commit_sha
                self._pr_context.commit_count += 1
                self._pr_context.clear_pending_changes()

                logger.info(
                    f"Phase commit for run {run_id}: {result.commit_sha} "
                    f"({result.files_changed} files)"
                )

                return {
                    "commit_sha": result.commit_sha,
                    "files_changed": result.files_changed,
                    "branch": self._pr_context.branch_name,
                }
            else:
                logger.error(f"Phase commit failed for run {run_id}: {result.error}")
                return None

        except Exception as e:
            logger.exception(f"Error in phase commit for run {run_id}: {e}")
            return None

    def _build_pr_body(
        self,
        context: PhaseContext,
        summary: str,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
    ) -> str:
        """Build the PR description body.

        Includes:
        - Work item link and title
        - Execution summary
        - Files changed by phase
        - Agent and model info
        """
        work_item = context.work_item
        agent = context.agent

        # Get files changed from EXECUTING phase
        executing_outputs = previous_outputs.get(CyclePhase.EXECUTING, {})
        changes = executing_outputs.get("changes", [])
        files_changed = executing_outputs.get("files_changed", len(changes))

        body_lines = [
            f"## Work Item: {work_item.title}",
            "",
            f"**Work Item ID**: `{work_item.item_id}`",
            f"**Agent**: {agent.name}",
            f"**Run ID**: `{self._pr_context.run_id if self._pr_context else 'unknown'}`",
            "",
            "---",
            "",
            "## Summary",
            "",
            summary,
            "",
            "---",
            "",
            f"## Changes ({files_changed} files)",
            "",
        ]

        # List changed files
        if changes:
            for change in changes[:20]:  # Limit to 20 files in PR body
                file_path = change.get("file", "unknown")
                action = change.get("action", "modified")
                emoji = {"file_write": "✏️", "file_edit": "📝", "delete": "🗑️"}.get(action, "📄")
                body_lines.append(f"- {emoji} `{file_path}`")

            if len(changes) > 20:
                body_lines.append(f"- ... and {len(changes) - 20} more files")
        else:
            body_lines.append("_No files changed_")

        body_lines.extend([
            "",
            "---",
            "",
            "_This PR was automatically created by GuideAI._",
        ])

        return "\n".join(body_lines)

    def add_file_change(
        self,
        path: str,
        content: str,
        action: str,
        phase: str,
        original_content: Optional[str] = None,
        encoding: str = "utf-8",
    ) -> bool:
        """Add a file change to the PR context.

        This method is called by the ToolExecutor when a file write/edit
        is performed in PR mode. The change is accumulated for later commit.

        Args:
            path: File path relative to repo root
            content: New file content
            action: "create", "update", or "delete"
            phase: GEP phase where change occurred
            original_content: Original content for diff generation
            encoding: Content encoding ("utf-8" or "base64")

        Returns:
            True if change was added, False if no PR context
        """
        if not self._pr_context:
            return False

        self._pr_context.add_file_change(
            path=path,
            content=content,
            action=action,
            phase=phase,
            original_content=original_content,
            encoding=encoding,
        )
        return True

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _load_playbook(self, agent_version: Optional[AgentVersion]) -> Dict[str, Any]:
        """Load playbook from agent version."""
        if not agent_version:
            return {}

        playbook = agent_version.metadata.get("playbook", {})
        if isinstance(playbook, str):
            try:
                playbook = json.loads(playbook)
            except json.JSONDecodeError:
                playbook = {}

        return playbook

    def _get_available_tools(
        self,
        phase: CyclePhase,
        exec_policy: ExecutionPolicy,
    ) -> List[str]:
        """Get available tools for a phase based on policy."""
        # Define phase-specific tool sets
        # NOTE: Tool names must match ToolRegistry in tool_executor.py
        phase_tools = {
            CyclePhase.PLANNING: [
                "read_file", "list_dir", "grep_search", "semantic_search",
            ],
            CyclePhase.CLARIFYING: [
                "read_file", "work_item_comment",
            ],
            CyclePhase.ARCHITECTING: [
                "read_file", "list_dir", "grep_search", "semantic_search",
            ],
            CyclePhase.EXECUTING: [
                "read_file", "write_file", "edit_file", "run_in_terminal",
                "list_dir", "grep_search",
            ],
            CyclePhase.TESTING: [
                "read_file", "run_in_terminal",
            ],
            CyclePhase.FIXING: [
                "read_file", "write_file", "edit_file", "run_in_terminal",
            ],
            CyclePhase.VERIFYING: [
                "read_file", "run_in_terminal",
            ],
            CyclePhase.COMPLETING: [
                "read_file", "work_item_update",
            ],
        }

        tools = phase_tools.get(phase, [])

        # Filter based on write scope
        if exec_policy.write_scope == WriteScope.READ_ONLY:
            tools = [t for t in tools if not t.startswith("write_file") and not t.startswith("edit_file")]

        # Add internet tools if enabled
        if exec_policy.internet_access == InternetAccessPolicy.ENABLED:
            tools.extend(["fetch_url", "search_web"])

        return tools

    async def _execute_tool_calls(
        self,
        tool_calls: List[ToolCall],
        run_id: str,
        exec_policy: ExecutionPolicy,
    ) -> List[ToolResult]:
        """Execute a list of tool calls."""
        if not tool_calls or not self._tool_executor:
            return []

        results = []
        for call in tool_calls:
            # Record tool call step
            step = ExecutionStep(
                step_id=_short_id("step"),
                step_type=ExecutionStepType.TOOL_CALL,
                phase="tool_execution",
                timestamp=_now_iso(),
                content={"inputs": call.tool_args},
                tool_name=call.tool_name,
            )

            try:
                # Check permissions
                if not self._check_tool_permission(call.tool_name, exec_policy):
                    result = ToolResult(
                        call_id=call.call_id,
                        tool_name=call.tool_name,
                        success=False,
                        error="Tool not permitted by execution policy",
                        output={},
                    )
                else:
                    # Execute tool
                    result = await self._tool_executor.execute(call)

            except Exception as e:
                result = ToolResult(
                    call_id=call.call_id,
                    tool_name=call.tool_name,
                    success=False,
                    error=str(e),
                    output={},
                )

            # Record completion - ExecutionStep doesn't have these fields, skip
            # step.completed_at = _now_iso()
            # step.outputs = result.output
            self._add_run_step(run_id, step)

            results.append(result)

        return results

    def _check_tool_permission(self, tool_name: str, exec_policy: ExecutionPolicy) -> bool:
        """Check if a tool is permitted by the execution policy."""
        # Write tools check (updated to match ToolRegistry names)
        write_tools = {"write_file", "edit_file", "run_in_terminal"}
        if tool_name in write_tools and exec_policy.write_scope == WriteScope.READ_ONLY:
            return False

        # Internet tools check
        internet_tools = {"fetch_url"}
        if tool_name in internet_tools and exec_policy.internet_access == InternetAccessPolicy.DISABLED:
            return False

        return True

    def _add_run_step(self, run_id: str, step: ExecutionStep) -> None:
        """Add a step to the run."""
        try:
            step_type = getattr(step, "step_type", None) or getattr(step, "type", None)
            step_type_value = step_type.value if hasattr(step_type, "value") else str(step_type or "step")
            phase = getattr(step, "phase", None)
            tool_name = getattr(step, "tool_name", None)
            input_tokens = int(getattr(step, "input_tokens", 0) or 0)
            output_tokens = int(getattr(step, "output_tokens", 0) or 0)
            duration_ms = int(getattr(step, "duration_ms", 0) or 0)
            model_id = getattr(step, "model_id", None)
            content = getattr(step, "content", None) or getattr(step, "outputs", None) or {}
            preview = json.dumps(content, ensure_ascii=True)[:240] if content else None

            metadata: Dict[str, Any] = {
                "phase": phase,
                "step_type": step_type_value,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": duration_ms,
            }
            if preview:
                metadata["content_preview"] = preview
            if model_id:
                metadata["model_id"] = model_id
            if tool_name:
                metadata["tool_calls"] = [{"tool_name": tool_name}]

            extra_metadata = getattr(step, "metadata", None)
            if isinstance(extra_metadata, dict):
                for key, value in extra_metadata.items():
                    metadata.setdefault(key, value)

            self._run_service.add_step(
                run_id=run_id,
                action=tool_name or step_type_value,
                outcome=content if isinstance(content, dict) else {},
                metadata=metadata,
                status=RunStatus.COMPLETED,
            )
        except Exception as e:
            logger.exception(f"Error adding run step: {e}")

    def _check_gate_satisfaction(
        self,
        current_phase: CyclePhase,
        next_phase: CyclePhase,
        exec_policy: ExecutionPolicy,
        result: PhaseResult,
    ) -> bool:
        """Check if gate is satisfied for phase transition."""
        gate_type = PHASE_GATES.get(current_phase)
        if not gate_type:
            return True  # No gate required

        # Check policy for this gate type
        gate_policies = exec_policy.phase_gates or {}
        policy = gate_policies.get(gate_type.value, GatePolicyType.NONE)

        if policy == GatePolicyType.NONE:
            return True  # Auto-approved without notification
        elif policy == GatePolicyType.STRICT:
            return False  # Wait for human approval
        elif policy == GatePolicyType.SOFT:
            return True  # Proceed but notify

        return True

    def _get_gate_type(self, phase: CyclePhase) -> GateType:
        """Get the gate type for a phase."""
        return PHASE_GATES.get(phase, GateType.CLARIFICATION_PROVIDED)

    def _get_next_phase(self, current_phase: CyclePhase, result: PhaseResult) -> Optional[CyclePhase]:
        """Determine the next phase based on current phase and result."""
        # Check valid transitions
        valid_next = VALID_TRANSITIONS.get(current_phase, [])

        if not valid_next:
            return None

        # Use suggested next phase if valid
        if result.next_phase and result.next_phase in valid_next:
            return result.next_phase

        # Default to first valid transition
        return valid_next[0] if valid_next else None

    def _calculate_progress(self, phase: CyclePhase) -> int:
        """Calculate progress percentage based on current phase."""
        phase_progress = {
            CyclePhase.PLANNING: 10,
            CyclePhase.CLARIFYING: 15,
            CyclePhase.ARCHITECTING: 25,
            CyclePhase.EXECUTING: 50,
            CyclePhase.TESTING: 70,
            CyclePhase.FIXING: 75,
            CyclePhase.VERIFYING: 90,
            CyclePhase.COMPLETING: 100,
        }
        return phase_progress.get(phase, 0)

    def _merge_outputs(
        self,
        phase_outputs: Dict[CyclePhase, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Merge outputs from all phases into a single dict."""
        merged: Dict[str, Any] = {}

        for phase, outputs in phase_outputs.items():
            for key, value in outputs.items():
                merged[f"{phase.value}_{key}"] = value

        # Add summary outputs
        if CyclePhase.EXECUTING in phase_outputs:
            merged["files_changed"] = phase_outputs[CyclePhase.EXECUTING].get("files_changed", 0)
        if CyclePhase.COMPLETING in phase_outputs:
            merged["summary"] = phase_outputs[CyclePhase.COMPLETING].get("summary", "")

        return merged

    # =========================================================================
    # Prompt Builders
    # =========================================================================

    def _build_planning_prompt(self, context: PhaseContext) -> List[Dict[str, Any]]:
        """Build the prompt for the PLANNING phase."""
        system = f"""You are {context.agent.name}, an AI agent executing a work item.

Current Phase: PLANNING
Your task is to analyze the work item and create an execution plan.

Work Item:
- Title: {context.work_item.title}
- Description: {context.work_item.description or 'No description'}
- Labels: {', '.join(context.work_item.labels) if context.work_item.labels else 'None'}

Playbook Instructions:
{json.dumps(context.playbook.get('planning_instructions', {}), indent=2)}

Available Tools: {', '.join(context.available_tools)}

Your response should include:
1. Understanding of the requirements
2. Key steps to complete the work item
3. Any clarifications needed before proceeding
4. Estimated complexity and approach

If you need clarification, use the clarification tool. Otherwise, proceed with creating a plan.
"""

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "Please analyze this work item and create an execution plan."},
        ]

    def _build_architecting_prompt(
        self,
        context: PhaseContext,
        plan: str,
    ) -> List[Dict[str, Any]]:
        """Build the prompt for the ARCHITECTING phase."""
        system = f"""You are {context.agent.name}, an AI agent executing a work item.

Current Phase: ARCHITECTING
Your task is to design the solution architecture based on the plan.

Work Item:
- Title: {context.work_item.title}
- Description: {context.work_item.description or 'No description'}

Previous Plan:
{plan}

Playbook Instructions:
{json.dumps(context.playbook.get('architecture_instructions', {}), indent=2)}

Available Tools: {', '.join(context.available_tools)}

Your response should include:
1. Files to create or modify
2. Key components and their interactions
3. Implementation approach for each change
4. Any dependencies or prerequisites
"""

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "Please design the solution architecture for this work item."},
        ]

    def _build_executing_prompt(
        self,
        context: PhaseContext,
        architecture: str,
    ) -> List[Dict[str, Any]]:
        """Build the prompt for the EXECUTING phase."""
        system = f"""You are {context.agent.name}, an AI agent executing a work item.

Current Phase: EXECUTING
Your task is to implement the changes according to the architecture.

Work Item:
- Title: {context.work_item.title}

Architecture:
{architecture}

Playbook Instructions:
{json.dumps(context.playbook.get('execution_instructions', {}), indent=2)}

Available Tools: {', '.join(context.available_tools)}

Implement the changes step by step. Use the available tools to:
1. Read existing files for context
2. Create new files as needed
3. Modify existing files
4. Run commands as required

Signal completion when all changes are made.
"""

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "Please implement the planned changes."},
        ]

    def _build_testing_prompt(
        self,
        context: PhaseContext,
        changes: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Build the prompt for the TESTING phase."""
        system = f"""You are {context.agent.name}, an AI agent executing a work item.

Current Phase: TESTING
Your task is to test the changes made in the execution phase.

Changes Made:
{json.dumps(changes, indent=2)}

Playbook Instructions:
{json.dumps(context.playbook.get('testing_instructions', {}), indent=2)}

Available Tools: {', '.join(context.available_tools)}

Run appropriate tests to validate:
1. New code works correctly
2. Existing tests still pass
3. No regressions introduced
"""

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "Please run tests to validate the changes."},
        ]

    def _build_fixing_prompt(
        self,
        context: PhaseContext,
        test_results: List[ToolResult],
    ) -> List[Dict[str, Any]]:
        """Build the prompt for the FIXING phase."""
        failures = [r for r in test_results if not r.success]

        system = f"""You are {context.agent.name}, an AI agent executing a work item.

Current Phase: FIXING
Your task is to fix the test failures.

Test Failures:
{json.dumps([{"tool": f.tool_name, "error": f.error} for f in failures], indent=2)}

Available Tools: {', '.join(context.available_tools)}

Analyze the failures and apply fixes to make the tests pass.
"""

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "Please fix the test failures."},
        ]

    def _build_verifying_prompt(
        self,
        context: PhaseContext,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Build the prompt for the VERIFYING phase."""
        system = f"""You are {context.agent.name}, an AI agent executing a work item.

Current Phase: VERIFYING
Your task is to perform final verification of the changes.

Available Tools: {', '.join(context.available_tools)}

Run verification checks:
1. Linting
2. Type checking
3. Final review of changes
4. Prepare commit/PR if all checks pass
"""

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "Please verify the changes are ready for completion."},
        ]

    def _add_tool_results_to_prompt(
        self,
        prompt: List[Dict[str, Any]],
        response: AgentResponse,
        tool_results: List[ToolResult],
    ) -> List[Dict[str, Any]]:
        """Add tool results to prompt for next iteration."""
        new_prompt = prompt.copy()

        # Add assistant response
        new_prompt.append({
            "role": "assistant",
            "content": response.text_output,
        })

        # Add tool results
        for result in tool_results:
            new_prompt.append({
                "role": "tool",
                "content": json.dumps({
                    "tool": result.tool_name,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                }),
            })

        return new_prompt

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def _check_for_clarification(
        self,
        work_item: WorkItem,
        run_id: str,
    ) -> Optional[str]:
        """Check if clarification has been provided via work item comments."""
        # TODO: Check work item comments for clarification responses
        # For now, return None (no clarification yet)
        return None

    def _get_return_phase_after_clarification(
        self,
        context: PhaseContext,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
    ) -> CyclePhase:
        """Determine which phase to return to after clarification."""
        # Check which phase triggered the clarification
        if CyclePhase.ARCHITECTING in previous_outputs:
            return CyclePhase.EXECUTING
        elif CyclePhase.PLANNING in previous_outputs:
            return CyclePhase.ARCHITECTING
        else:
            return CyclePhase.PLANNING

    def _extract_plan(
        self,
        response: AgentResponse,
        tool_results: List[ToolResult],
    ) -> Dict[str, Any]:
        """Extract plan from LLM response."""
        # TODO: Parse response content for structured plan
        return {
            "raw_plan": response.text_output,
            "steps": [],  # TODO: Extract steps
        }

    def _extract_architecture(
        self,
        response: AgentResponse,
        tool_results: List[ToolResult],
    ) -> Dict[str, Any]:
        """Extract architecture from LLM response."""
        # TODO: Parse response content for structured architecture
        return {
            "raw_architecture": response.text_output,
            "files_to_modify": [],  # TODO: Extract file list
            "files_to_create": [],
        }

    def _check_test_results(self, tool_results: List[ToolResult]) -> bool:
        """Check if all tests passed."""
        if not tool_results:
            return True  # No tests run, assume pass

        return all(r.success for r in tool_results)

    def _generate_completion_summary(
        self,
        context: PhaseContext,
        previous_outputs: Dict[CyclePhase, Dict[str, Any]],
    ) -> str:
        """Generate a completion summary for posting as a comment."""
        lines = [
            f"## ✅ Work Item Completed",
            f"",
            f"**Work Item:** {context.work_item.title}",
            f"**Agent:** {context.agent.name}",
            f"",
        ]

        # Add changes summary
        if CyclePhase.EXECUTING in previous_outputs:
            changes = previous_outputs[CyclePhase.EXECUTING].get("changes", [])
            if changes:
                lines.append(f"### Changes Made")
                lines.append(f"- Files modified: {len(changes)}")
                for change in changes[:10]:  # Limit to 10
                    lines.append(f"  - {change.get('file', 'unknown')}")
                if len(changes) > 10:
                    lines.append(f"  - ... and {len(changes) - 10} more")

        # Add test summary
        if CyclePhase.TESTING in previous_outputs:
            tests_passed = previous_outputs[CyclePhase.TESTING].get("tests_passed", True)
            lines.append(f"")
            lines.append(f"### Tests")
            lines.append(f"- Status: {'✅ Passed' if tests_passed else '❌ Failed'}")

        return "\n".join(lines)
