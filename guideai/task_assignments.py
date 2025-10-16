"""Task assignment registry mapping remaining deliverables to functions and agents.

This module provides a canonical view that can be consumed by CLI, REST, and MCP
surfaces while we orchestrate Milestone 1 and Milestone 2 planning. Data is kept
in-memory for parity testing purposes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class FunctionSpec:
    """Represents a functional area and its associated agent."""

    key: str
    label: str
    agent_name: str
    playbook: str
    notes: str = ""

    def to_dict(self) -> Dict[str, str]:
        payload = {
            "key": self.key,
            "function": self.label,
            "primary_agent": self.agent_name,
            "agent_playbook": self.playbook,
        }
        if self.notes:
            payload["notes"] = self.notes
        return payload


@dataclass(frozen=True)
class TaskAssignment:
    """Metadata describing a planned deliverable and ownership details."""

    task_id: str
    title: str
    milestone: str
    status: str
    description: str
    function_key: str
    dependencies: List[str] = field(default_factory=list)
    evidence_targets: List[str] = field(default_factory=list)
    supporting_functions: List[str] = field(default_factory=list)
    surfaces: List[str] = field(default_factory=lambda: ["platform", "cli", "api", "mcp"])

    def to_dict(self, function_lookup: Dict[str, FunctionSpec]) -> Dict[str, object]:
        primary = function_lookup[self.function_key]
        supporting = [function_lookup[key] for key in self.supporting_functions]
        return {
            "task_id": self.task_id,
            "title": self.title,
            "milestone": self.milestone,
            "status": self.status,
            "description": self.description,
            "function": primary.label,
            "primary_agent": primary.agent_name,
            "agent_playbook": primary.playbook,
            "surfaces": list(self.surfaces),
            "dependencies": list(self.dependencies),
            "evidence_targets": list(self.evidence_targets),
            "supporting_agents": [agent.to_dict() for agent in supporting],
        }


_FUNCTIONS: Dict[str, FunctionSpec] = {
    "engineering": FunctionSpec(
        key="engineering",
        label="Engineering",
        agent_name="Agent Engineering",
        playbook="AGENT_ENGINEERING.md",
        notes="Leads service/runtime implementation and telemetry contracts.",
    ),
    "developer_experience": FunctionSpec(
        key="developer_experience",
        label="Developer Experience",
        agent_name="Agent Developer Experience",
        playbook="AGENT_DX.md",
        notes="Owns IDE workflows, onboarding assets, and parity evidence.",
    ),
    "devops": FunctionSpec(
        key="devops",
        label="DevOps",
        agent_name="Agent DevOps",
        playbook="AGENT_DEVOPS.md",
        notes="Handles deploy pipelines, environment automation, and rollback readiness.",
    ),
    "product_management": FunctionSpec(
        key="product_management",
        label="Product Management",
        agent_name="Agent Product",
        playbook="AGENT_PRODUCT.md",
        notes="Prioritizes roadmap, discovery, and launch gating.",
    ),
    "product_analytics": FunctionSpec(
        key="product_analytics",
        label="Product (Analytics)",
        agent_name="Agent Product",
        playbook="AGENT_PRODUCT.md",
        notes="Drives analytics instrumentation and KPI dashboards.",
    ),
    "copywriting": FunctionSpec(
        key="copywriting",
        label="Copywriting",
        agent_name="Agent Copywriting",
        playbook="AGENT_COPYWRITING.md",
        notes="Crafts release notes, in-product copy, and consent messaging.",
    ),
    "compliance": FunctionSpec(
        key="compliance",
        label="Compliance",
        agent_name="Agent Compliance",
        playbook="AGENT_COMPLIANCE.md",
        notes="Ensures checklist automation, audit evidence, and policy adherence.",
    ),
}


_FUNCTION_ALIASES: Dict[str, str] = {
    "eng": "engineering",
    "engineering": "engineering",
    "developer-experience": "developer_experience",
    "developer_experience": "developer_experience",
    "dx": "developer_experience",
    "devops": "devops",
    "operations": "devops",
    "product": "product_management",
    "pm": "product_management",
    "product-management": "product_management",
    "product-analytics": "product_analytics",
    "product_analytics": "product_analytics",
    "productanalytics": "product_analytics",
    "analytics": "product_analytics",
    "copy": "copywriting",
    "copywriting": "copywriting",
    "compliance": "compliance",
}


_TASKS: List[TaskAssignment] = [
    TaskAssignment(
        task_id="milestone1.vscode_extension",
        title="VS Code Extension Preview",
        milestone="Milestone 1",
        status="PLANNED",
        description=(
            "Implement sidebar search, plan composer, execution tracker, and post-task review "
            "experiences leveraging existing SDK and telemetry contracts."
        ),
        function_key="developer_experience",
        dependencies=["sdk-authentication", "behavior-retrieval-api", "action-service-integration"],
        evidence_targets=[
            "Extension bundle",
            "Integration tests",
            "Capability matrix update",
        ],
        supporting_functions=["engineering", "copywriting", "product_management"],
    ),
    TaskAssignment(
        task_id="milestone1.checklist_automation",
        title="Checklist Automation Engine",
        milestone="Milestone 1",
        status="PLANNED",
        description=(
            "Implement automated compliance checklist enforcement and logging across Strategist/Teacher/Student templates."
        ),
        function_key="engineering",
        dependencies=["workflow-templates", "run-service", "compliance-service-stubs"],
        evidence_targets=["Automated checklist validation", "Compliance dashboard integration"],
        supporting_functions=["compliance", "devops", "product_management"],
    ),
    TaskAssignment(
        task_id="milestone1.behavior_service",
        title="BehaviorService Runtime Deployment",
        milestone="Milestone 1",
        status="PLANNED",
        description=(
            "Deploy BehaviorService with CRUD operations, approval workflow, and embedding index in production environments."
        ),
        function_key="engineering",
        dependencies=["postgres-backend", "vector-db", "embedding-model"],
        evidence_targets=["Service endpoints", "Retrieval benchmarks"],
        supporting_functions=["devops", "product_management", "compliance"],
    ),
    TaskAssignment(
        task_id="milestone1.analytics_dashboards",
        title="Initial Analytics Dashboards",
        milestone="Milestone 1",
        status="PLANNED",
        description=(
            "Deploy production analytics for behavior reuse, token savings, task completion, and compliance coverage KPIs."
        ),
        function_key="product_analytics",
        dependencies=["telemetry-pipeline", "warehouse-schema"],
        evidence_targets=[
            "Live KPI dashboards",
            "Telemetry validation",
        ],
        supporting_functions=["engineering", "developer_experience", "copywriting"],
    ),
    TaskAssignment(
        task_id="milestone1.agent_auth_runtime",
        title="AgentAuthService Runtime",
        milestone="Milestone 1",
        status="PLANNED",
        description=(
            "Deploy AgentAuthService with device flow, consent management, and policy enforcement across surfaces."
        ),
        function_key="engineering",
        dependencies=["consent-ux", "policy-engine", "mfa-enforcement"],
        evidence_targets=["Runtime deployment checklist", "Telemetry + audit coverage"],
        supporting_functions=["compliance", "product_management", "devops"],
    ),
    TaskAssignment(
        task_id="milestone1.workflow_engine",
        title="Workflow Engine Foundation",
        milestone="Milestone 1",
        status="PLANNED",
        description=(
            "Deliver Strategist/Teacher/Student workflow templates with behavior-conditioned inference integration."
        ),
        function_key="engineering",
        dependencies=["behavior-handbook", "runtime-templates"],
        evidence_targets=["Template library", "Integration tests"],
        supporting_functions=["developer_experience", "compliance"],
    ),
    TaskAssignment(
        task_id="milestone1.embedding_integration",
        title="Embedding Model Integration",
        milestone="Milestone 1",
        status="PLANNED",
        description="Integrate BGE-M3 (or alternative) embedding model with vector index for semantic behavior retrieval.",
        function_key="engineering",
        dependencies=["vector-store", "model-hosting"],
        evidence_targets=["Retriever benchmarks", "Telemetry on latency"],
        supporting_functions=["product_management", "devops"],
    ),
    TaskAssignment(
        task_id="milestone2.customer_research",
        title="External Customer Research",
        milestone="Milestone 2 Planning",
        status="PLANNED",
        description="Conduct discovery interviews/pilots and update PRD with insights.",
        function_key="product_management",
        dependencies=["customer-list", "research-plan"],
        evidence_targets=["Research synthesis", "PRD updates"],
        supporting_functions=["copywriting", "compliance"],
    ),
    TaskAssignment(
        task_id="milestone2.pricing_strategy",
        title="Pricing & Packaging Experiments",
        milestone="Milestone 2 Planning",
        status="PLANNED",
        description="Outline pricing scenarios, packaging, and GA gating criteria informed by cost telemetry.",
        function_key="product_management",
        dependencies=["cost-telemetry", "market-analysis"],
        evidence_targets=["Pricing experiment doc", "GA gating criteria"],
        supporting_functions=["engineering", "devops", "product_analytics"],
    ),
    TaskAssignment(
        task_id="milestone2.multitenant_behavior",
        title="Multi-tenant Behavior Sharing",
        milestone="Milestone 2 Planning",
        status="PLANNED",
        description="Evaluate multi-tenant behavior handbook considerations and update open questions accordingly.",
        function_key="engineering",
        dependencies=["tenant-model", "compliance-review"],
        evidence_targets=["Architecture proposal", "Compliance assessment"],
        supporting_functions=["product_management", "compliance"],
    ),
    TaskAssignment(
        task_id="milestone2.analytics_parity_dashboard",
        title="Action Replay & Parity Analytics Dashboard",
        milestone="Milestone 2 Planning",
        status="PLANNED",
        description=(
            "Create analytics dashboard tracking replay usage, parity health, PRD success metrics, and checklist adherence."
        ),
        function_key="product_analytics",
        dependencies=["action-telemetry", "parity-tests"],
        evidence_targets=["Parity metrics dashboard", "Checklist adherence view"],
        supporting_functions=["engineering", "developer_experience", "compliance"],
    ),
]


class TaskAssignmentService:
    """Provides read-only access to task assignments for the project."""

    def __init__(self, assignments: Iterable[TaskAssignment] = _TASKS) -> None:
        self._assignments = list(assignments)

    @property
    def functions(self) -> List[Dict[str, str]]:
        """Return metadata describing all supported functions."""

        return [spec.to_dict() for spec in _FUNCTIONS.values()]

    def list_assignments(self, function: Optional[str] = None) -> List[Dict[str, object]]:
        """Return task assignments, optionally filtered by function alias."""

        normalized = None
        if function:
            key = function.strip().lower().replace(" ", "-")
            normalized = _FUNCTION_ALIASES.get(key)
            if normalized is None:
                raise ValueError(
                    f"Unknown function '{function}'. Expected one of: {sorted(set(_FUNCTION_ALIASES))}."
                )

        results: List[Dict[str, object]] = []
        for assignment in self._assignments:
            if normalized and assignment.function_key != normalized:
                continue
            results.append(assignment.to_dict(_FUNCTIONS))
        return results


__all__ = [
    "FunctionSpec",
    "TaskAssignment",
    "TaskAssignmentService",
]
