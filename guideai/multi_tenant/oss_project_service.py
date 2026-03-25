"""Lightweight OSS project service for personal projects.

Provides basic project CRUD against PostgreSQL without requiring the
enterprise OrganizationService. Orgs are an enterprise feature — this
service handles personal (user-owned) projects only.

Used as a fallback when guideai-enterprise is not installed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .contracts import (
    Project,
    ProjectAgentAssignmentResponse,
    ProjectAgentRole,
    ProjectAgentStatus,
    ProjectVisibility,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OSSProjectService:
    """Minimal project service for OSS (personal projects, no org features).

    Implements the subset of OrganizationService methods used by projects_api.py.
    Backs onto the existing auth.projects / auth.project_agent_assignments tables.
    """

    def __init__(self, *, dsn: str) -> None:
        self._dsn = dsn

    def _get_conn(self):
        import psycopg2
        return psycopg2.connect(self._dsn)

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def list_projects(
        self,
        owner_id: str,
        org_id: Optional[str] = None,
    ) -> List[Project]:
        """List projects owned by a user (personal projects)."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                if org_id:
                    cur.execute(
                        """
                        SELECT project_id, org_id, owner_id, name, slug,
                               description, visibility, settings,
                               created_at, updated_at
                        FROM auth.projects
                        WHERE owner_id = %s AND org_id = %s
                        ORDER BY created_at DESC
                        """,
                        (owner_id, org_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT project_id, org_id, owner_id, name, slug,
                               description, visibility, settings,
                               created_at, updated_at
                        FROM auth.projects
                        WHERE owner_id = %s
                        ORDER BY created_at DESC
                        """,
                        (owner_id,),
                    )
                rows = cur.fetchall()
                return [self._row_to_project(r) for r in rows]
        finally:
            conn.close()

    def create_project(
        self,
        *,
        name: str,
        owner_id: str,
        org_id: Optional[str] = None,
        slug: Optional[str] = None,
        description: Optional[str] = None,
        visibility: str = "private",
    ) -> Project:
        """Create a personal project."""
        project_id = f"proj-{uuid.uuid4().hex[:12]}"
        if not slug:
            slug = name.strip().lower().replace(" ", "-")
            import re
            slug = re.sub(r"[^a-z0-9-]", "", slug) or f"proj-{uuid.uuid4().hex[:8]}"

        now = _utc_now()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth.projects
                        (project_id, org_id, owner_id, name, slug,
                         description, visibility, settings, created_by,
                         created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, '{}', %s, %s, %s)
                    RETURNING project_id
                    """,
                    (project_id, org_id, owner_id, name, slug,
                     description, visibility, owner_id, now, now),
                )
                conn.commit()
        finally:
            conn.close()

        return Project(
            id=project_id,
            org_id=org_id,
            owner_id=owner_id,
            name=name,
            slug=slug,
            description=description,
            visibility=ProjectVisibility(visibility) if visibility in ProjectVisibility.__members__.values() else ProjectVisibility.PRIVATE,
            settings={},
            created_at=now,
            updated_at=now,
        )

    def get_project(self, project_id: str) -> Optional[Project]:
        """Get a single project by ID."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT project_id, org_id, owner_id, name, slug,
                           description, visibility, settings,
                           created_at, updated_at
                    FROM auth.projects
                    WHERE project_id = %s
                    """,
                    (project_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return self._row_to_project(row)
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Project-Agent Assignments
    # ------------------------------------------------------------------

    def list_user_project_agent_assignments(
        self,
        owner_id: str,
        project_id: Optional[str] = None,
    ) -> List[ProjectAgentAssignmentResponse]:
        """List agent assignments for projects owned by a user."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                if project_id:
                    cur.execute(
                        """
                        SELECT pa.id, pa.project_id, pa.agent_id,
                               pa.assigned_by, pa.assigned_at,
                               pa.config_overrides, pa.role, pa.status,
                               a.name as agent_name, a.slug as agent_slug,
                               a.description as agent_description
                        FROM auth.project_agent_assignments pa
                        JOIN auth.projects p ON p.project_id = pa.project_id
                        LEFT JOIN execution.agents a ON a.agent_id = pa.agent_id
                        WHERE p.owner_id = %s AND pa.project_id = %s
                        ORDER BY pa.assigned_at DESC
                        """,
                        (owner_id, project_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT pa.id, pa.project_id, pa.agent_id,
                               pa.assigned_by, pa.assigned_at,
                               pa.config_overrides, pa.role, pa.status,
                               a.name as agent_name, a.slug as agent_slug,
                               a.description as agent_description
                        FROM auth.project_agent_assignments pa
                        JOIN auth.projects p ON p.project_id = pa.project_id
                        LEFT JOIN execution.agents a ON a.agent_id = pa.agent_id
                        WHERE p.owner_id = %s
                        ORDER BY pa.assigned_at DESC
                        """,
                        (owner_id,),
                    )
                rows = cur.fetchall()
                return [self._row_to_agent_assignment(r) for r in rows]
        finally:
            conn.close()

    def list_project_agent_assignments(
        self,
        project_id: str,
    ) -> List[ProjectAgentAssignmentResponse]:
        """List agent assignments for a specific project."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pa.id, pa.project_id, pa.agent_id,
                           pa.assigned_by, pa.assigned_at,
                           pa.config_overrides, pa.role, pa.status,
                           a.name as agent_name, a.slug as agent_slug,
                           a.description as agent_description
                    FROM auth.project_agent_assignments pa
                    LEFT JOIN execution.agents a ON a.agent_id = pa.agent_id
                    WHERE pa.project_id = %s
                    ORDER BY pa.assigned_at DESC
                    """,
                    (project_id,),
                )
                rows = cur.fetchall()
                return [self._row_to_agent_assignment(r) for r in rows]
        finally:
            conn.close()

    def assign_registry_agent_to_project(
        self,
        *,
        project_id: str,
        agent_id: str,
        assigned_by: str,
        config_overrides: Optional[Dict[str, Any]] = None,
        role: ProjectAgentRole = ProjectAgentRole.PRIMARY,
    ) -> ProjectAgentAssignmentResponse:
        """Assign a registry agent to a project."""
        import json

        assignment_id = f"pa-{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        config = config_overrides or {}

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO auth.project_agent_assignments
                        (id, project_id, agent_id, assigned_by, assigned_at,
                         config_overrides, role, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (assignment_id, project_id, agent_id, assigned_by, now,
                     json.dumps(config), role.value, ProjectAgentStatus.ACTIVE.value),
                )
                conn.commit()
        finally:
            conn.close()

        return ProjectAgentAssignmentResponse(
            id=assignment_id,
            project_id=project_id,
            agent_id=agent_id,
            name="",
            assigned_by=assigned_by,
            assigned_at=now,
            config=config,
            role=role,
            status=ProjectAgentStatus.ACTIVE,
        )

    def remove_project_agent_assignment(
        self,
        *,
        assignment_id: str,
        removed_by: str,
    ) -> bool:
        """Remove an agent assignment."""
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM auth.project_agent_assignments WHERE id = %s",
                    (assignment_id,),
                )
                removed = cur.rowcount > 0
                conn.commit()
                return removed
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_project(row) -> Project:
        """Convert a DB row tuple to a Project contract."""
        import json

        (project_id, org_id, owner_id, name, slug,
         description, visibility, settings,
         created_at, updated_at) = row

        if isinstance(settings, str):
            settings = json.loads(settings)
        elif settings is None:
            settings = {}

        vis = ProjectVisibility.PRIVATE
        if visibility:
            try:
                vis = ProjectVisibility(visibility)
            except ValueError:
                pass

        return Project(
            id=project_id,
            org_id=org_id,
            owner_id=owner_id or "",
            name=name or "",
            slug=slug or "",
            description=description,
            visibility=vis,
            settings=settings,
            created_at=created_at,
            updated_at=updated_at,
        )

    @staticmethod
    def _row_to_agent_assignment(row) -> ProjectAgentAssignmentResponse:
        """Convert a DB row tuple to a ProjectAgentAssignmentResponse."""
        import json

        (assign_id, project_id, agent_id,
         assigned_by, assigned_at,
         config_overrides, role, assign_status,
         agent_name, agent_slug, agent_description) = row

        if isinstance(config_overrides, str):
            config_overrides = json.loads(config_overrides)
        elif config_overrides is None:
            config_overrides = {}

        try:
            role_enum = ProjectAgentRole(role)
        except (ValueError, KeyError):
            role_enum = ProjectAgentRole.PRIMARY

        try:
            status_enum = ProjectAgentStatus(assign_status)
        except (ValueError, KeyError):
            status_enum = ProjectAgentStatus.ACTIVE

        return ProjectAgentAssignmentResponse(
            id=assign_id,
            project_id=project_id,
            agent_id=agent_id,
            name=agent_name or "",
            agent_name=agent_name,
            agent_slug=agent_slug,
            agent_description=agent_description,
            assigned_by=assigned_by,
            assigned_at=assigned_at or _utc_now(),
            config=config_overrides,
            role=role_enum,
            status=status_enum,
        )
