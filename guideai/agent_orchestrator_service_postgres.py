"""PostgreSQL-backed AgentOrchestratorService implementation.

Provides durable storage for agent assignments, persona definitions, and switching history.
Replaces in-memory dict storage with PostgreSQL for multi-tenant production deployments.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4, UUID

from guideai.storage.postgres_pool import PostgresPool
from guideai.agent_orchestrator_service import (
    AgentPersona,
    AgentSwitchEvent,
    AgentAssignment,
    _DEFAULT_PERSONA_DEFS,
)


class PostgresAgentOrchestratorService:
    """PostgreSQL-backed agent orchestrator with durable state."""

    def __init__(self, dsn: str) -> None:
        """Initialize with PostgreSQL connection.

        Args:
            dsn: PostgreSQL connection string (e.g., postgresql://user:pass@host:port/dbname)
        """
        self._pool = PostgresPool(dsn, service_name="agent_orchestrator")
        self._ensure_default_personas()

    def _ensure_default_personas(self) -> None:
        """Seed default personas if not already present."""
        def _execute(conn: Any) -> None:
            with conn.cursor() as cur:
                for persona_def in _DEFAULT_PERSONA_DEFS:
                    cur.execute(
                        """
                        INSERT INTO agent_personas (
                            agent_id, display_name, role_alignment,
                            default_behaviors, playbook_refs, capabilities
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (agent_id) DO NOTHING
                        """,
                        (
                            persona_def["agent_id"],
                            persona_def["display_name"],
                            persona_def["role_alignment"],
                            json.dumps(persona_def["default_behaviors"]),
                            json.dumps(persona_def["playbook_refs"]),
                            json.dumps(persona_def["capabilities"]),
                    ),
                )

        self._pool.run_transaction(
            "seed_default_personas",
            executor=_execute,
            service_prefix="agent_orchestrator",
        )

    def list_personas(self) -> List[AgentPersona]:
        """List all available agent personas."""
        def _query(conn: Any) -> List[AgentPersona]:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT agent_id, display_name, role_alignment,
                           default_behaviors, playbook_refs, capabilities
                    FROM agent_personas
                    ORDER BY agent_id
                    """
                )
                rows = cur.fetchall()
                return [
                    AgentPersona(
                        agent_id=row[0],
                        display_name=row[1],
                        role_alignment=row[2],
                        default_behaviors=row[3] if row[3] else [],
                        playbook_refs=row[4] if row[4] else [],
                        capabilities=row[5] if row[5] else [],
                    )
                    for row in rows
                ]

        return self._pool.run_transaction(
            "list_personas",
            executor=_query,
            service_prefix="agent_orchestrator",
        )

    def assign_agent(
        self,
        *,
        run_id: Optional[str],
        requested_agent_id: Optional[str],
        stage: str,
        context: Optional[Dict[str, Any]],
        requested_by: Dict[str, Any],
    ) -> AgentAssignment:
        """Assign an agent to a run with context-aware selection.

        Args:
            run_id: Run identifier (None for global assignment)
            requested_agent_id: Specific agent requested (None for heuristic selection)
            stage: Current stage (e.g., 'planning', 'execution', 'review')
            context: Context metadata for heuristics
            requested_by: Actor dict with id/role/surface

        Returns:
            AgentAssignment with assigned persona and heuristics
        """
        def _execute(conn: Any) -> AgentAssignment:
            with conn.cursor() as cur:
                # Check for existing assignment
                if run_id:
                    cur.execute(
                        """
                        SELECT assignment_id, active_agent_id, stage,
                               heuristics_applied, requested_by_id, requested_by_role,
                               requested_by_surface, created_at, metadata
                        FROM agent_assignments
                        WHERE run_id = %s
                        """,
                        (run_id,),
                    )
                    existing = cur.fetchone()
                    if existing and (requested_agent_id is None or existing[1] == requested_agent_id):
                        # Return existing assignment
                        assignment_id = existing[0]
                        persona = self._fetch_persona(cur, existing[1])
                        history = self._fetch_history(cur, assignment_id)
                        return AgentAssignment(
                            assignment_id=str(assignment_id),
                            run_id=run_id,
                            active_agent=persona,
                            stage=existing[2],
                            heuristics_applied=existing[3] if existing[3] else {},
                            requested_by={
                                "id": existing[4],
                                "role": existing[5],
                                "surface": existing[6],
                            },
                            timestamp=existing[7].isoformat(),
                            metadata=existing[8] if existing[8] else {},
                            history=history,
                        )

                # Select persona
                persona = self._select_persona(cur, requested_agent_id, context)
                heuristics = self._build_heuristics(persona.agent_id, requested_agent_id, context)

                # Create new assignment
                assignment_id = uuid4()
                timestamp = datetime.now(timezone.utc)
                cur.execute(
                    """
                    INSERT INTO agent_assignments (
                        assignment_id, run_id, active_agent_id, stage,
                        heuristics_applied, requested_by_id, requested_by_role,
                        requested_by_surface, created_at, updated_at, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        assignment_id,
                        run_id,
                        persona.agent_id,
                        stage,
                        json.dumps(heuristics),
                    requested_by.get("id") or requested_by.get("actor_id") or "unknown",
                    requested_by.get("role") or requested_by.get("actor_role") or "STUDENT",
                    requested_by.get("surface") or requested_by.get("actor_surface") or "cli",
                        timestamp,
                        timestamp,
                        json.dumps(context or {}),
                    ),
                )

                return AgentAssignment(
                        assignment_id=str(assignment_id),
                        run_id=run_id or "",
                        active_agent=persona,
                        stage=stage,
                        heuristics_applied=heuristics,
                        requested_by=requested_by,
                        timestamp=timestamp.isoformat(),
                        metadata=context or {},
                        history=[],
                    )

        return self._pool.run_transaction(
            "assign_agent",
            executor=_execute,
            service_prefix="agent_orchestrator",
        )

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
        """Switch the assigned agent for a run.

        Args:
            assignment_id: Assignment to modify
            target_agent_id: New agent to assign
            reason: Human-readable reason for switch
            allow_downgrade: Whether to allow switching to less senior agent
            stage: Optional new stage
            issued_by: Actor dict with id/role/surface

        Returns:
            Updated AgentAssignment with switch event added to history
        """
        def _execute(conn: Any) -> AgentAssignment:
            with conn.cursor() as cur:
                # Fetch current assignment
                cur.execute(
                    """
                    SELECT run_id, active_agent_id, stage, heuristics_applied,
                           requested_by_id, requested_by_role, requested_by_surface,
                           created_at, metadata
                    FROM agent_assignments
                    WHERE assignment_id = %s
                    """,
                    (UUID(assignment_id),),
                )
                row = cur.fetchone()
                if not row:
                    raise KeyError(f"Unknown assignment_id: {assignment_id}")

                run_id, from_agent_id, current_stage, heuristics_json, req_id, req_role, req_surface, created_at, metadata_json = row
                from_persona = self._fetch_persona(cur, from_agent_id)
                to_persona = self._fetch_persona(cur, target_agent_id)

                # Create switch event
                event_id = uuid4()
                new_stage = stage or current_stage
                trigger_details = {
                    "reason": reason or "manual_override",
                    "allow_downgrade": allow_downgrade,
                }
                timestamp = datetime.now(timezone.utc)

                cur.execute(
                    """
                    INSERT INTO agent_switch_events (
                        event_id, assignment_id, from_agent_id, to_agent_id,
                        stage, trigger, trigger_details, issued_by_id,
                        issued_by_role, issued_by_surface, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        event_id,
                        UUID(assignment_id),
                        from_agent_id,
                        target_agent_id,
                        new_stage,
                        "MANUAL" if reason else "HEURISTIC",
                        json.dumps(trigger_details),
                        (issued_by.get("id") or issued_by.get("actor_id") or "unknown") if issued_by else "unknown",
                        (issued_by.get("role") or issued_by.get("actor_role") or "STUDENT") if issued_by else "STUDENT",
                        (issued_by.get("surface") or issued_by.get("actor_surface") or "cli") if issued_by else "cli",
                        timestamp,
                    ),
                )

                # Update assignment
                new_heuristics = self._build_heuristics(target_agent_id, target_agent_id, metadata_json if metadata_json else {})
                cur.execute(
                    """
                    UPDATE agent_assignments
                    SET active_agent_id = %s, stage = %s,
                        heuristics_applied = %s, updated_at = %s
                    WHERE assignment_id = %s
                    """,
                    (
                        target_agent_id,
                        new_stage,
                        json.dumps(new_heuristics),
                        timestamp,
                        UUID(assignment_id),
                    ),
                )

                # Fetch full history
                history = self._fetch_history(cur, UUID(assignment_id))

                return AgentAssignment(
                    assignment_id=assignment_id,
                    run_id=run_id or "",
                    active_agent=to_persona,
                    stage=new_stage,
                    heuristics_applied=new_heuristics,
                    requested_by={
                        "id": req_id,
                        "role": req_role,
                        "surface": req_surface,
                    },
                    timestamp=timestamp.isoformat(),
                    metadata=metadata_json if metadata_json else {},
                    history=history,
                )

        return self._pool.run_transaction(
            "switch_agent",
            executor=_execute,
            service_prefix="agent_orchestrator",
        )

    def get_status(
        self,
        *,
        run_id: Optional[str],
        assignment_id: Optional[str],
    ) -> Optional[AgentAssignment]:
        """Get current assignment status by run_id or assignment_id.

        Args:
            run_id: Run identifier
            assignment_id: Assignment UUID

        Returns:
            AgentAssignment if found, None otherwise
        """
        def _execute(conn: Any) -> Optional[AgentAssignment]:
            with conn.cursor() as cur:
                if assignment_id:
                    query = """
                        SELECT assignment_id, run_id, active_agent_id, stage,
                               heuristics_applied, requested_by_id, requested_by_role,
                               requested_by_surface, created_at, metadata
                        FROM agent_assignments
                        WHERE assignment_id = %s
                    """
                    cur.execute(query, (UUID(assignment_id),))
                elif run_id:
                    query = """
                        SELECT assignment_id, run_id, active_agent_id, stage,
                               heuristics_applied, requested_by_id, requested_by_role,
                               requested_by_surface, created_at, metadata
                        FROM agent_assignments
                        WHERE run_id = %s
                    """
                    cur.execute(query, (run_id,))
                else:
                    return None

                row = cur.fetchone()
                if not row:
                    return None

                persona = self._fetch_persona(cur, row[2])
                history = self._fetch_history(cur, row[0])

                return AgentAssignment(
                    assignment_id=str(row[0]),
                    run_id=row[1] or "",
                    active_agent=persona,
                    stage=row[3],
                    heuristics_applied=row[4] if row[4] else {},
                    requested_by={
                        "id": row[5],
                        "role": row[6],
                        "surface": row[7],
                    },
                    timestamp=row[8].isoformat(),
                    metadata=row[9] if row[9] else {},
                    history=history,
                )

        return self._pool.run_transaction(
            "get_status",
            executor=_execute,
            service_prefix="agent_orchestrator",
        )

    def _fetch_persona(self, cur: Any, agent_id: str) -> AgentPersona:
        """Fetch persona by agent_id."""
        cur.execute(
            """
            SELECT agent_id, display_name, role_alignment,
                   default_behaviors, playbook_refs, capabilities
            FROM agent_personas
            WHERE agent_id = %s
            """,
            (agent_id,),
        )
        row = cur.fetchone()
        if not row:
            raise KeyError(f"Unknown agent_id: {agent_id}")

        return AgentPersona(
            agent_id=row[0],
            display_name=row[1],
            role_alignment=row[2],
            default_behaviors=row[3] if row[3] else [],
            playbook_refs=row[4] if row[4] else [],
            capabilities=row[5] if row[5] else [],
        )

    def _fetch_history(self, cur: Any, assignment_id: UUID) -> List[AgentSwitchEvent]:
        """Fetch switch history for an assignment."""
        cur.execute(
            """
            SELECT event_id, from_agent_id, to_agent_id, stage, trigger,
                   trigger_details, issued_by_id, issued_by_role,
                   issued_by_surface, created_at
            FROM agent_switch_events
            WHERE assignment_id = %s
            ORDER BY created_at ASC
            """,
            (assignment_id,),
        )
        rows = cur.fetchall()
        return [
            AgentSwitchEvent(
                event_id=str(row[0]),
                from_agent_id=row[1],
                to_agent_id=row[2],
                stage=row[3],
                trigger=row[4],
                trigger_details=row[5] if row[5] else {},
                timestamp=row[9].isoformat(),
                issued_by={
                    "actor_id": row[6],
                    "actor_role": row[7],
                } if row[6] else {},
            )
            for row in rows
        ]

    def _select_persona(
        self,
        cur: Any,
        requested_agent_id: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> AgentPersona:
        """Select persona based on request or heuristics."""
        # Direct request takes priority
        if requested_agent_id:
            try:
                return self._fetch_persona(cur, requested_agent_id)
            except KeyError:
                pass  # Fall through to heuristics

        # Apply heuristics from context
        if context:
            task_type = context.get("task_type")
            if task_type:
                cur.execute(
                    """
                    SELECT agent_id, display_name, role_alignment,
                           default_behaviors, playbook_refs, capabilities
                    FROM agent_personas
                    WHERE agent_id = %s
                    """,
                    (task_type,),
                )
                row = cur.fetchone()
                if row:
                    return AgentPersona(
                        agent_id=row[0],
                        display_name=row[1],
                        role_alignment=row[2],
                        default_behaviors=row[3] if row[3] else [],
                        playbook_refs=row[4] if row[4] else [],
                        capabilities=row[5] if row[5] else [],
                    )

        # Default to engineering
        try:
            return self._fetch_persona(cur, "engineering")
        except KeyError:
            # Fall back to first available persona
            cur.execute(
                """
                SELECT agent_id, display_name, role_alignment,
                       default_behaviors, playbook_refs, capabilities
                FROM agent_personas
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("No agent personas available")

            return AgentPersona(
                agent_id=row[0],
                display_name=row[1],
                role_alignment=row[2],
                default_behaviors=row[3] if row[3] else [],
                playbook_refs=row[4] if row[4] else [],
                capabilities=row[5] if row[5] else [],
            )

    def _build_heuristics(
        self,
        selected_agent_id: str,
        requested_agent_id: Optional[str],
        context: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build heuristics metadata for assignment."""
        return {
            "selected_agent_id": selected_agent_id,
            "requested_agent_id": requested_agent_id,
            "task_type": context.get("task_type") if context else None,
            "compliance_tags": context.get("compliance_tags") if context else None,
            "severity": context.get("severity") if context else None,
        }
