"""Project REST API routes.

Projects are a single resource type that can either:
- belong to an organization (`org_id` set), or
- be personal (`owner_id` set).

This module provides `/v1/projects` list/create for personal (and optionally org-scoped) projects.

Following:
- behavior_lock_down_security_surface (Student): require auth; avoid leaking cross-user data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
import re
import uuid

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field


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
    """In-memory project store used when PostgreSQL org service isn't configured."""

    def __init__(self) -> None:
        self._projects_by_owner: Dict[str, Dict[str, StoredProject]] = {}

    def list_projects(self, *, owner_id: str, org_id: Optional[str] = None) -> List[StoredProject]:
        projects = list(self._projects_by_owner.get(owner_id, {}).values())
        if org_id is None:
            return [p for p in projects if p.org_id is None]
        return [p for p in projects if p.org_id == org_id]

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
        return project


def create_project_routes(
    *,
    store: InMemoryProjectStore,
    get_user_id: Callable[[Request], str],
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

    return router
