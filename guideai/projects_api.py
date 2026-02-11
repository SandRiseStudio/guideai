"""Project REST API routes.

Projects are a single resource type that can either:
- belong to an organization (`org_id` set), or
- be personal (`owner_id` set).

This module provides `/v1/projects` list/create for personal (and optionally org-scoped) projects
and `/v1/projects/agents` for personal agent assignments.

Following:
- behavior_lock_down_security_surface (Student): require auth; avoid leaking cross-user data.
- behavior_align_storage_layers (Student): persist to PostgreSQL for board FK integrity.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
import re
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from guideai.storage.postgres_pool import PostgresPool
    from guideai.multi_tenant.organization_service import OrganizationService

from guideai.multi_tenant.contracts import (
    Agent,
    AgentType,
    ProjectAgentAssignmentResponse,
    ProjectAgentRole,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def _slugify(value: str) -> str:
    slug = value.strip().lower()
    slug = re.sub(r"\s+", "-", slug)
    slug = _SLUG_RE.sub("", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or f"proj-{uuid.uuid4().hex[:8]}"


class ProjectDTO(BaseModel):
    id: str
    name: str
    slug: str
    description: Optional[str] = None
    visibility: str = "private"
    settings: Dict[str, object] = Field(default_factory=dict)
    org_id: Optional[str] = None
    owner_id: Optional[str] = None
    created_at: str
    updated_at: str


class ProjectListResponse(BaseModel):
    items: List[ProjectDTO]


class CreateProjectBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    slug: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    visibility: str = "private"
    org_id: Optional[str] = None


class PersonalAgentListResponse(BaseModel):
    """Response for listing project-agent assignments.

    Note: Uses ProjectAgentAssignmentResponse for proper junction table pattern.
    The 'agents' field name is kept for backward compatibility with frontend.
    """
    agents: List[ProjectAgentAssignmentResponse]
    total: int


class CreatePersonalAgentBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    project_id: str = Field(..., min_length=1)
    agent_type: AgentType = AgentType.SPECIALIST
    config: Dict[str, Any] = Field(default_factory=dict)
    capabilities: List[str] = Field(default_factory=list)


@dataclass(frozen=True)
class StoredProject:
    id: str
    name: str
    slug: str
    description: Optional[str]
    visibility: str
    settings: Dict[str, object]
    org_id: Optional[str]
    owner_id: str
    created_at: datetime
    updated_at: datetime

    def to_dto(self) -> ProjectDTO:
        return ProjectDTO(
            id=self.id,
            name=self.name,
            slug=self.slug,
            description=self.description,
            visibility=self.visibility,
            settings=self.settings,
            org_id=self.org_id,
            owner_id=self.owner_id,
            created_at=self.created_at.isoformat(),
            updated_at=self.updated_at.isoformat(),
        )


class InMemoryProjectStore:
    """In-memory project store with optional PostgreSQL persistence.

    When a PostgresPool is provided, projects are also persisted to PostgreSQL
    to satisfy foreign key constraints from other tables (e.g., boards).
    On startup, projects are loaded from PostgreSQL to restore state.
    """

    def __init__(self, pool: Optional["PostgresPool"] = None) -> None:
        self._projects_by_owner: Dict[str, Dict[str, StoredProject]] = {}
        self._pool = pool
        # Load existing projects from PostgreSQL on startup
        if self._pool is not None:
            self._load_from_postgres()

    def _load_from_postgres(self) -> None:
        """Load all projects from PostgreSQL into memory on startup."""
        if self._pool is None:
            return

        loaded_count = 0

        def _execute(conn) -> None:
            nonlocal loaded_count
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT project_id, org_id, name, slug, description, visibility,
                           settings, created_by, created_at, updated_at
                    FROM projects
                    """
                )
                rows = cur.fetchall()
                for row in rows:
                    project = StoredProject(
                        id=row[0],
                        org_id=row[1],
                        name=row[2],
                        slug=row[3],
                        description=row[4],
                        visibility=row[5],
                        settings=row[6] if isinstance(row[6], dict) else {},
                        owner_id=row[7],  # created_by is owner_id
                        created_at=row[8],
                        updated_at=row[9],
                    )
                    # Add to in-memory store by owner
                    if project.owner_id not in self._projects_by_owner:
                        self._projects_by_owner[project.owner_id] = {}
                    self._projects_by_owner[project.owner_id][project.id] = project
                    loaded_count += 1

        try:
            self._pool.run_transaction(
                operation="project.load_all",
                service_prefix="project",
                actor=None,
                metadata={},
                executor=_execute,
                telemetry=None,
            )
            if loaded_count > 0:
                logger.info(f"Loaded {loaded_count} projects from PostgreSQL")
        except Exception as e:
            logger.warning(f"Failed to load projects from PostgreSQL: {e}")
            # Don't fail startup - start with empty store

    def get_project(self, *, project_id: str, owner_id: str) -> Optional[StoredProject]:
        """Get a specific project by ID for a given owner.

        If PostgresPool is available, refreshes settings from database to ensure
        any updates made via SettingsService are reflected immediately.
        """
        by_owner = self._projects_by_owner.get(owner_id, {})
        project = by_owner.get(project_id)

        if project is None:
            return None

        # Refresh settings from database to pick up any SettingsService updates
        if self._pool is not None:
            try:
                with self._pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT settings FROM projects WHERE project_id = %s",
                            (project_id,)
                        )
                        row = cur.fetchone()
                        if row and row[0]:
                            fresh_settings = row[0] if isinstance(row[0], dict) else {}
                            # Update in-memory cache with fresh settings
                            project = StoredProject(
                                id=project.id,
                                name=project.name,
                                slug=project.slug,
                                description=project.description,
                                visibility=project.visibility,
                                settings=fresh_settings,
                                org_id=project.org_id,
                                owner_id=project.owner_id,
                                created_at=project.created_at,
                                updated_at=project.updated_at,
                            )
                            # Update cache
                            self._projects_by_owner[owner_id][project_id] = project
            except Exception as e:
                logger.warning(f"Failed to refresh project settings from database: {e}")
                # Fall back to cached settings

        return project

    def list_projects(self, *, owner_id: str, org_id: Optional[str] = None) -> List[StoredProject]:
        """List projects accessible to a user.

        Returns:
        - Personal projects: where owner_id matches (org_id IS NULL)
        - Org projects: where user is a member of the org (via org_memberships)

        If org_id is provided, filters to only that org's projects.
        If org_id is None, returns personal projects PLUS all org projects the user can access.
        """
        # If we have PostgreSQL, query directly for accurate org membership data
        if self._pool is not None:
            return self._list_projects_from_postgres(owner_id=owner_id, org_id=org_id)

        # Fallback to in-memory (legacy behavior)
        projects = list(self._projects_by_owner.get(owner_id, {}).values())
        if org_id is None:
            return [p for p in projects if p.org_id is None]
        return [p for p in projects if p.org_id == org_id]

    def _list_projects_from_postgres(self, *, owner_id: str, org_id: Optional[str] = None) -> List[StoredProject]:
        """Query PostgreSQL for projects accessible to a user.

        Includes:
        1. Personal projects: owner_id = user_id AND org_id IS NULL
        2. Org projects: user is a member of the org
        """
        results: List[StoredProject] = []

        def _execute(conn) -> None:
            with conn.cursor() as cur:
                if org_id is not None:
                    # Filter to specific org - user must be a member
                    cur.execute(
                        """
                        SELECT p.project_id, p.org_id, p.name, p.slug, p.description,
                               p.visibility, p.settings, p.created_by, p.owner_id,
                               p.created_at, p.updated_at
                        FROM projects p
                        INNER JOIN org_memberships om ON om.org_id = p.org_id
                        WHERE om.user_id = %s AND p.org_id = %s AND p.archived_at IS NULL
                        """,
                        (owner_id, org_id),
                    )
                else:
                    # Return personal projects + all org projects user can access
                    cur.execute(
                        """
                        SELECT p.project_id, p.org_id, p.name, p.slug, p.description,
                               p.visibility, p.settings, p.created_by, p.owner_id,
                               p.created_at, p.updated_at
                        FROM projects p
                        LEFT JOIN org_memberships om ON om.org_id = p.org_id AND om.user_id = %s
                        WHERE p.archived_at IS NULL
                          AND (
                            -- Personal projects owned by user
                            (p.owner_id = %s AND p.org_id IS NULL)
                            OR
                            -- Org projects where user is a member
                            (p.org_id IS NOT NULL AND om.membership_id IS NOT NULL)
                          )
                        ORDER BY p.created_at DESC
                        """,
                        (owner_id, owner_id),
                    )

                for row in cur.fetchall():
                    # Handle both old schema (created_by) and new schema (owner_id)
                    project_owner = row[8] if row[8] else row[7]
                    results.append(StoredProject(
                        id=row[0],
                        org_id=row[1],
                        name=row[2],
                        slug=row[3],
                        description=row[4],
                        visibility=row[5],
                        settings=row[6] if isinstance(row[6], dict) else {},
                        owner_id=project_owner or owner_id,  # Fallback for legacy records
                        created_at=row[9],
                        updated_at=row[10],
                    ))

        try:
            self._pool.run_transaction(
                operation="project.list",
                service_prefix="project",
                actor=owner_id,
                metadata={"org_id": org_id},
                executor=_execute,
                telemetry=None,
            )
        except Exception as e:
            logger.warning(f"Failed to list projects from PostgreSQL: {e}")
            # Fallback to in-memory
            projects = list(self._projects_by_owner.get(owner_id, {}).values())
            if org_id is None:
                return [p for p in projects if p.org_id is None]
            return [p for p in projects if p.org_id == org_id]

        return results

    def _persist_to_postgres(self, project: StoredProject) -> None:
        """Persist project to PostgreSQL auth.projects table for FK integrity.

        Also creates the owner membership record so the creator has proper access.
        """
        if self._pool is None:
            return

        def _execute(conn) -> None:
            with conn.cursor() as cur:
                # Insert project
                cur.execute(
                    """
                    INSERT INTO auth.projects (project_id, org_id, name, slug, description, visibility, settings, created_by, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (project_id) DO NOTHING
                    """,
                    (
                        project.id,
                        project.org_id,
                        project.name,
                        project.slug,
                        project.description,
                        project.visibility,
                        "{}",  # settings as JSON string
                        project.owner_id,  # Now valid - user exists in auth.users (OAuth user ID)
                        project.created_at,
                        project.updated_at,
                    ),
                )

                # Add creator as owner in project_memberships
                import uuid
                membership_id = f"mem-{uuid.uuid4().hex[:12]}"
                cur.execute(
                    """
                    INSERT INTO auth.project_memberships (membership_id, project_id, user_id, role, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (project_id, user_id) DO NOTHING
                    """,
                    (
                        membership_id,
                        project.id,
                        project.owner_id,
                        "owner",
                        project.created_at,
                        project.created_at,
                    ),
                )

        try:
            self._pool.run_transaction(
                operation="project.persist",
                service_prefix="project",
                actor=None,
                metadata={"project_id": project.id},
                executor=_execute,
                telemetry=None,
            )
        except Exception as e:
            logger.warning(f"Failed to persist project to PostgreSQL: {e}")
            # Don't fail - in-memory store is primary, PostgreSQL is supplementary

    def create_project(
        self,
        *,
        owner_id: str,
        name: str,
        slug: Optional[str],
        description: Optional[str],
        visibility: str,
        org_id: Optional[str],
    ) -> StoredProject:
        now = _utc_now()
        project_id = f"proj-{uuid.uuid4().hex[:12]}"
        resolved_slug = _slugify(slug or name)

        by_owner = self._projects_by_owner.setdefault(owner_id, {})
        if any(p.slug == resolved_slug and p.org_id == org_id for p in by_owner.values()):
            raise ValueError(f"Project slug '{resolved_slug}' is already taken")

        project = StoredProject(
            id=project_id,
            name=name,
            slug=resolved_slug,
            description=description,
            visibility=visibility,
            settings={},
            org_id=org_id,
            owner_id=owner_id,
            created_at=now,
            updated_at=now,
        )
        by_owner[project.id] = project

        # Persist to PostgreSQL for FK integrity (boards, runs, etc.)
        self._persist_to_postgres(project)

        return project


def create_project_routes(
    *,
    store: InMemoryProjectStore,
    get_user_id: Callable[[Request], str],
    org_service: Optional["OrganizationService"] = None,
    tags: Optional[List[str]] = None,
) -> APIRouter:
    router = APIRouter(prefix="/v1/projects", tags=tags or ["projects"])

    @router.get("", response_model=ProjectListResponse)
    def list_projects(request: Request, org_id: Optional[str] = Query(default=None)) -> ProjectListResponse:
        user_id = get_user_id(request)
        projects = store.list_projects(owner_id=user_id, org_id=org_id)
        return ProjectListResponse(items=[p.to_dto() for p in projects])

    @router.post("", response_model=ProjectDTO, status_code=status.HTTP_201_CREATED)
    def create_project(request: Request, body: CreateProjectBody) -> ProjectDTO:
        user_id = get_user_id(request)

        if body.org_id is not None and not body.org_id.strip():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="org_id cannot be empty")

        try:
            project = store.create_project(
                owner_id=user_id,
                name=body.name,
                slug=body.slug,
                description=body.description,
                visibility=body.visibility,
                org_id=body.org_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        return project.to_dto()

    # -------------------------------------------------------------------------
    # /agents routes MUST be defined BEFORE /{project_id} to avoid route conflict
    # (FastAPI matches routes in order; /{project_id} would match "agents" as a project_id)
    # -------------------------------------------------------------------------
    if org_service is not None:
        def _require_personal_project(user_id: str, project_id: str) -> StoredProject:
            project = store.get_project(project_id=project_id, owner_id=user_id)
            if project is None or project.org_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Project {project_id} not found",
                )
            return project

        @router.get("/agents", response_model=PersonalAgentListResponse)
        def list_personal_agents(
            request: Request,
            project_id: Optional[str] = Query(default=None),
        ) -> PersonalAgentListResponse:
            """List agent assignments for personal projects.

            Uses the junction table pattern (execution.project_agent_assignments)
            to return agents assigned to projects owned by the requesting user.
            """
            user_id = get_user_id(request)
            if project_id:
                _require_personal_project(user_id, project_id)
            assignments = org_service.list_user_project_agent_assignments(
                owner_id=user_id,
                project_id=project_id,
            )
            return PersonalAgentListResponse(agents=assignments, total=len(assignments))

        @router.post("/agents", response_model=ProjectAgentAssignmentResponse, status_code=status.HTTP_201_CREATED)
        def create_personal_agent(request: Request, body: CreatePersonalAgentBody) -> ProjectAgentAssignmentResponse:
            """Assign a registry agent to a personal project.

            Extracts the registry_agent_id from body.config and creates a
            project-agent assignment in the junction table.

            For backward compatibility, accepts the legacy body format with
            registry_agent_id inside config.
            """
            user_id = get_user_id(request)
            _require_personal_project(user_id, body.project_id)

            # Extract registry agent ID from config (frontend sends it there)
            registry_agent_id = body.config.get("registry_agent_id")
            if not registry_agent_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="config.registry_agent_id is required",
                )

            try:
                assignment = org_service.assign_registry_agent_to_project(
                    project_id=body.project_id,
                    agent_id=registry_agent_id,
                    assigned_by=user_id,
                    config_overrides=body.config,
                    role=ProjectAgentRole.PRIMARY,
                )

                # Fetch with agent details for response
                assignments = org_service.list_project_agent_assignments(body.project_id)
                return next((a for a in assignments if a.id == assignment.id), assignment)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(exc),
                ) from exc

        @router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
        def delete_personal_agent(request: Request, agent_id: str) -> None:
            """Remove an agent assignment.

            The agent_id here is actually the assignment ID (paa-*).
            For backward compatibility, we try both removing by assignment ID
            and by looking up assignments to find a matching agent.
            """
            user_id = get_user_id(request)

            # First try to remove by assignment ID directly
            removed = org_service.remove_project_agent_assignment(
                assignment_id=agent_id,
                removed_by=user_id,
            )
            if not removed:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent assignment {agent_id} not found",
                )
    else:
        # Fallback routes when org_service is not available - return empty results
        @router.get("/agents", response_model=PersonalAgentListResponse)
        def list_personal_agents_fallback(
            request: Request,
            project_id: Optional[str] = Query(default=None),
        ) -> PersonalAgentListResponse:
            _ = get_user_id(request)  # Still require auth
            return PersonalAgentListResponse(agents=[], total=0)

        @router.post("/agents", response_model=ProjectAgentAssignmentResponse, status_code=status.HTTP_201_CREATED)
        def create_personal_agent_fallback(request: Request, body: CreatePersonalAgentBody) -> ProjectAgentAssignmentResponse:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Personal agent creation requires multi-tenant service to be configured",
            )

        @router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
        def delete_personal_agent_fallback(request: Request, agent_id: str) -> None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Personal agent deletion requires multi-tenant service to be configured",
            )

    # -------------------------------------------------------------------------
    # /{project_id} routes MUST come AFTER /agents routes
    # -------------------------------------------------------------------------
    @router.get("/{project_id}", response_model=ProjectDTO)
    def get_project(request: Request, project_id: str) -> ProjectDTO:
        user_id = get_user_id(request)
        project = store.get_project(project_id=project_id, owner_id=user_id)
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project {project_id} not found")
        return project.to_dto()

    return router
