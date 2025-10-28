from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

_DEFAULT_PERSONA_DEFS = [
    {
        "agent_id": "engineering",
        "display_name": "Engineering Agent",
        "role_alignment": "MULTI_ROLE",
        "default_behaviors": [
            "behavior_unify_execution_records",
            "behavior_wire_cli_to_orchestrator",
        ],
        "playbook_refs": ["AGENT_ENGINEERING.md"],
        "capabilities": ["runtime_orchestration", "telemetry"],
    },
    {
        "agent_id": "product",
        "display_name": "Product Agent",
        "role_alignment": "STRATEGIST",
        "default_behaviors": [
            "behavior_update_docs_after_changes",
            "behavior_instrument_metrics_pipeline",
        ],
        "playbook_refs": ["AGENT_PRODUCT.md"],
        "capabilities": ["roadmap", "metrics"],
    },
    {
        "agent_id": "finance",
        "display_name": "Finance Agent",
        "role_alignment": "TEACHER",
        "default_behaviors": [
            "behavior_validate_financial_impact",
        ],
        "playbook_refs": ["AGENT_FINANCE.md"],
        "capabilities": ["budget", "forecasting"],
    },
    {
        "agent_id": "compliance",
        "display_name": "Compliance Agent",
        "role_alignment": "TEACHER",
        "default_behaviors": [
            "behavior_handbook_compliance_prompt",
            "behavior_update_docs_after_changes",
        ],
        "playbook_refs": ["AGENT_COMPLIANCE.md"],
        "capabilities": ["audit", "checklist"],
    },
    {
        "agent_id": "security",
        "display_name": "Security Agent",
        "role_alignment": "STRATEGIST",
        "default_behaviors": [
            "behavior_lock_down_security_surface",
            "behavior_prevent_secret_leaks",
        ],
        "playbook_refs": ["AGENT_SECURITY.md"],
        "capabilities": ["auth", "threat_model"],
    },
]


@dataclass
class AgentPersona:
    agent_id: str
    display_name: str
    role_alignment: str
    default_behaviors: List[str] = field(default_factory=list)
    playbook_refs: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentSwitchEvent:
    event_id: str
    from_agent_id: str
    to_agent_id: str
    stage: str
    trigger: str
    trigger_details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    issued_by: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentAssignment:
    assignment_id: str
    run_id: str
    active_agent: AgentPersona
    stage: str
    heuristics_applied: Dict[str, Any]
    requested_by: Dict[str, Any]
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    history: List[AgentSwitchEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["active_agent"] = self.active_agent.to_dict()
        payload["history"] = [event.to_dict() for event in self.history]
        return payload


class AgentOrchestratorService:
    """In-memory coordinator for runtime agent assignments."""

    def __init__(self, personas: Optional[List[AgentPersona]] = None) -> None:
        if personas is None:
            personas = [AgentPersona(**definition) for definition in _DEFAULT_PERSONA_DEFS]
        self._personas: Dict[str, AgentPersona] = {persona.agent_id: persona for persona in personas}
        self._assignments: Dict[str, AgentAssignment] = {}
        self._assignments_by_run: Dict[str, str] = {}

    def list_personas(self) -> List[AgentPersona]:
        return list(self._personas.values())

    def assign_agent(
        self,
        *,
        run_id: Optional[str],
        requested_agent_id: Optional[str],
        stage: str,
        context: Optional[Dict[str, Any]],
        requested_by: Dict[str, Any],
    ) -> AgentAssignment:
        run_identifier = run_id or str(uuid4())
        existing_id = self._assignments_by_run.get(run_identifier)
        if existing_id:
            existing = self._assignments[existing_id]
            if requested_agent_id is None or existing.active_agent.agent_id == requested_agent_id:
                return existing
        persona = self._select_persona(requested_agent_id, context)
        heuristics = self._build_heuristics(persona.agent_id, requested_agent_id, context)
        assignment_id = str(uuid4())
        assignment = AgentAssignment(
            assignment_id=assignment_id,
            run_id=run_identifier,
            active_agent=persona,
            stage=stage,
            heuristics_applied=heuristics,
            requested_by=requested_by,
            timestamp=datetime.now(timezone.utc).isoformat(),
            metadata=context or {},
            history=[],
        )
        self._assignments[assignment_id] = assignment
        self._assignments_by_run[run_identifier] = assignment_id
        return assignment

    def switch_agent(
        self,
        *,
        assignment_id: str,
        target_agent_id: str,
        reason: Optional[str],
        allow_downgrade: bool,
        stage: Optional[str],
        issued_by: Optional[Dict[str, Any]],
    ) -> AgentAssignment:
        assignment = self._get_assignment(assignment_id)
        persona = self._select_persona(target_agent_id, assignment.metadata)
        trigger_details = {
            "reason": reason or "manual_override",
            "allow_downgrade": allow_downgrade,
        }
        event = AgentSwitchEvent(
            event_id=str(uuid4()),
            from_agent_id=assignment.active_agent.agent_id,
            to_agent_id=persona.agent_id,
            stage=stage or assignment.stage,
            trigger="MANUAL" if reason else "HEURISTIC",
            trigger_details=trigger_details,
            issued_by=issued_by or {},
        )
        assignment.history.append(event)
        assignment.active_agent = persona
        if stage:
            assignment.stage = stage
        assignment.heuristics_applied = self._build_heuristics(persona.agent_id, target_agent_id, assignment.metadata)
        assignment.timestamp = datetime.now(timezone.utc).isoformat()
        return assignment

    def get_status(
        self,
        *,
        run_id: Optional[str],
        assignment_id: Optional[str],
    ) -> Optional[AgentAssignment]:
        if assignment_id:
            return self._assignments.get(assignment_id)
        if run_id:
            found = self._assignments_by_run.get(run_id)
            return self._assignments.get(found) if found else None
        return None

    def _select_persona(
        self,
        requested_agent_id: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> AgentPersona:
        if requested_agent_id and requested_agent_id in self._personas:
            return self._personas[requested_agent_id]
        if context:
            task_type = context.get("task_type")
            if task_type == "compliance" and "compliance" in self._personas:
                return self._personas["compliance"]
            if task_type == "security" and "security" in self._personas:
                return self._personas["security"]
            if task_type == "finance" and "finance" in self._personas:
                return self._personas["finance"]
        return self._personas.get("engineering") or next(iter(self._personas.values()))

    def _build_heuristics(
        self,
        selected_agent_id: str,
        requested_agent_id: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return {
            "selected_agent_id": selected_agent_id,
            "requested_agent_id": requested_agent_id,
            "task_type": context.get("task_type") if context else None,
            "compliance_tags": context.get("compliance_tags") if context else None,
            "severity": context.get("severity") if context else None,
        }

    def _get_assignment(self, assignment_id: str) -> AgentAssignment:
        if assignment_id not in self._assignments:
            raise KeyError(f"Unknown assignment_id: {assignment_id}")
        return self._assignments[assignment_id]
