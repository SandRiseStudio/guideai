"""PostgreSQL-backed organization service for multi-tenancy.

This service handles all CRUD operations for organizations, memberships,
projects, and agents with proper tenant isolation via RLS.

Usage:
    from guideai.multi_tenant import OrganizationService

    org_service = OrganizationService(dsn="postgresql://...")

    # Create org (owner context set automatically)
    org = org_service.create_organization(
        request=CreateOrgRequest(name="Acme Corp", slug="acme"),
        owner_id="user-123"
    )

    # List user's orgs
    orgs = org_service.list_user_organizations(user_id="user-123")
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Optional, List, Dict, Any

from .contracts import (
    Organization,
    CreateOrgRequest,
    UpdateOrgRequest,
    OrgMembership,
    CreateMembershipRequest,
    UpdateMembershipRequest,
    Project,
    CreateProjectRequest,
    UpdateProjectRequest,
    ProjectMembership,
    CreateProjectMembershipRequest,
    Agent,
    CreateAgentRequest,
    UpdateAgentRequest,
    Subscription,
    UsageRecord,
    RecordUsageRequest,
    OrgWithMembers,
    OrgWithRole,
    ProjectWithMembers,
    UserOrganizations,
    OrgContext,
    OrgPlan,
    OrgStatus,
    MemberRole,
    ProjectRole,
    SubscriptionStatus,
    ProjectVisibility,
    AgentType,
    AgentStatus,
    # New imports for optional orgs
    ProjectCollaborator,
    AddCollaboratorRequest,
    UpdateCollaboratorRequest,
    BillingContext,
    ResolveBillingRequest,
    CreateUserSubscriptionRequest,
    UserWithSubscription,
    # Agent status tracking
    AgentStatusTransitionTrigger,
    AgentStatusChangeRequest,
    AgentStatusEvent,
    AgentStatusHistory,
    is_valid_status_transition,
)
from .board_contracts import CreateBoardRequest

if TYPE_CHECKING:
    from guideai.storage.postgres_pool import PostgresPool
    from guideai.services.board_service import BoardService, Actor as BoardActor


def _jsonb(value: Any) -> Optional[str]:
    """Serialize a value to JSON string for PostgreSQL JSONB columns."""
    if value is None:
        return None
    return json.dumps(value)


logger = logging.getLogger(__name__)


class OrganizationService:
    """PostgreSQL-backed service for organization management.

    All operations respect Row-Level Security (RLS) policies defined
    in migration 023. This is a synchronous service using psycopg2
    through PostgresPool.

    Attributes:
        pool: PostgresPool instance for database operations.
        board_service: Optional BoardService for auto-creating default boards.
    """

    def __init__(
        self,
        pool: Optional["PostgresPool"] = None,
        dsn: Optional[str] = None,
        board_service: Optional["BoardService"] = None,
    ):
        """Initialize with either a pool or DSN string.

        Args:
            pool: PostgresPool instance for database operations.
            dsn: PostgreSQL connection string (creates pool automatically).
            board_service: Optional BoardService for creating default boards.

        Raises:
            ValueError: If neither pool nor dsn is provided.
        """
        if pool is not None:
            self.pool = pool
        elif dsn is not None:
            from guideai.storage.postgres_pool import PostgresPool
            self.pool = PostgresPool(dsn=dsn)
        else:
            raise ValueError("Either pool or dsn must be provided")

        self._board_service = board_service

    # =========================================================================
    # Organization CRUD
    # =========================================================================

    def create_organization(
        self,
        request: CreateOrgRequest,
        owner_id: str,
    ) -> Organization:
        """Create a new organization with the requesting user as owner.

        Args:
            request: Organization creation request.
            owner_id: User ID who will be the org owner.

        Returns:
            The created organization.

        Raises:
            ValueError: If slug is already taken.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Check slug uniqueness
            cursor.execute(
                "SELECT id FROM organizations WHERE slug = %s",
                (request.slug,)
            )
            if cursor.fetchone():
                raise ValueError(f"Organization slug '{request.slug}' is already taken")

            # Create organization
            org = Organization(
                name=request.name,
                slug=request.slug,
                display_name=request.display_name,
                plan=request.plan,
                settings=request.settings,
            )

            # Insert organization
            cursor.execute(
                """
                INSERT INTO organizations (id, name, slug, display_name, plan, settings, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    org.id,
                    org.name,
                    org.slug,
                    org.display_name,
                    org.plan.value,
                    _jsonb(org.settings),
                    _jsonb(org.metadata),
                ),
            )

            # Add owner membership
            membership = OrgMembership(
                org_id=org.id,
                user_id=owner_id,
                role=MemberRole.OWNER,
            )
            cursor.execute(
                """
                INSERT INTO org_memberships (membership_id, org_id, user_id, role)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    membership.id,
                    membership.org_id,
                    membership.user_id,
                    membership.role.value,
                ),
            )

            # Create default subscription
            subscription = Subscription(
                org_id=org.id,
                plan=org.plan,
                status=SubscriptionStatus.ACTIVE,
            )
            cursor.execute(
                """
                INSERT INTO subscriptions (subscription_id, org_id, plan, status)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    subscription.id,
                    subscription.org_id,
                    subscription.plan.value,
                    subscription.status.value,
                ),
            )

            conn.commit()

        logger.info(f"Created organization {org.id} with owner {owner_id}")
        return org

    def get_organization(self, org_id: str) -> Optional[Organization]:
        """Get an organization by ID.

        Args:
            org_id: Organization ID.

        Returns:
            The organization if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, name, slug, display_name, plan, status,
                       stripe_customer_id, settings, metadata,
                       created_at, updated_at
                FROM organizations
                WHERE id = %s AND status != 'deleted'
                """,
                (org_id,)
            )
            row = cursor.fetchone()

        if not row:
            return None

        return Organization(
            id=row[0],
            name=row[1],
            slug=row[2],
            display_name=row[3],
            plan=OrgPlan(row[4]),
            status=OrgStatus(row[5]),
            stripe_customer_id=row[6],
            settings=row[7] or {},
            metadata=row[8] or {},
            created_at=row[9],
            updated_at=row[10],
        )

    def get_organization_by_slug(self, slug: str) -> Optional[Organization]:
        """Get an organization by slug.

        Args:
            slug: Organization slug.

        Returns:
            The organization if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, name, slug, display_name, plan, status,
                       stripe_customer_id, settings, metadata,
                       created_at, updated_at
                FROM organizations
                WHERE slug = %s AND status != 'deleted'
                """,
                (slug,)
            )
            row = cursor.fetchone()

        if not row:
            return None

        return Organization(
            id=row[0],
            name=row[1],
            slug=row[2],
            display_name=row[3],
            plan=OrgPlan(row[4]),
            status=OrgStatus(row[5]),
            stripe_customer_id=row[6],
            settings=row[7] or {},
            metadata=row[8] or {},
            created_at=row[9],
            updated_at=row[10],
        )

    def update_organization(
        self,
        org_id: str,
        request: UpdateOrgRequest,
    ) -> Optional[Organization]:
        """Update an organization.

        Args:
            org_id: Organization ID.
            request: Update request with fields to modify.

        Returns:
            The updated organization if found, None otherwise.
        """
        # Build dynamic update query
        updates = []
        params = []

        if request.name is not None:
            updates.append("name = %s")
            params.append(request.name)

        if request.display_name is not None:
            updates.append("display_name = %s")
            params.append(request.display_name)

        if request.plan is not None:
            updates.append("plan = %s")
            params.append(request.plan.value)

        if request.status is not None:
            updates.append("status = %s")
            params.append(request.status.value)

        if request.settings is not None:
            updates.append("settings = %s")
            params.append(_jsonb(request.settings))

        if request.metadata is not None:
            updates.append("metadata = %s")
            params.append(_jsonb(request.metadata))

        if not updates:
            # No changes requested
            return self.get_organization(org_id)

        updates.append("updated_at = %s")
        params.append(datetime.utcnow())
        params.append(org_id)

        query = f"""
            UPDATE organizations
            SET {', '.join(updates)}
            WHERE id = %s AND status != 'deleted'
        """

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            conn.commit()

        return self.get_organization(org_id)

    def delete_organization(self, org_id: str) -> bool:
        """Soft-delete an organization by setting status to deleted.

        Args:
            org_id: Organization ID.

        Returns:
            True if organization was deleted, False if not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE organizations
                SET status = 'deleted', updated_at = %s
                WHERE id = %s AND status != 'deleted'
                """,
                (datetime.utcnow(), org_id),
            )
            deleted = cursor.rowcount > 0
            conn.commit()

        if deleted:
            logger.info(f"Soft-deleted organization {org_id}")

        return deleted

    # =========================================================================
    # User Organization Access
    # =========================================================================

    def list_user_organizations(
        self,
        user_id: str,
        include_deleted: bool = False,
    ) -> List[OrgWithRole]:
        """List all organizations a user belongs to.

        Args:
            user_id: User ID.
            include_deleted: Whether to include deleted organizations.

        Returns:
            List of organizations with user's role in each.
        """
        status_filter = "" if include_deleted else "AND o.status != 'deleted'"

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT o.id, o.name, o.slug, o.display_name, o.plan, o.status,
                       o.stripe_customer_id, o.settings, o.metadata,
                       o.created_at, o.updated_at,
                       m.role as user_role,
                       (SELECT COUNT(*) FROM org_memberships WHERE org_id = o.id) as member_count
                FROM organizations o
                JOIN org_memberships m ON o.id = m.org_id
                WHERE m.user_id = %s {status_filter}
                ORDER BY o.name
                """,
                (user_id,)
            )
            rows = cursor.fetchall()

        orgs = []
        for row in rows:
            org = OrgWithRole(
                id=row[0],
                name=row[1],
                slug=row[2],
                display_name=row[3],
                plan=OrgPlan(row[4]),
                status=OrgStatus(row[5]),
                stripe_customer_id=row[6],
                settings=row[7] or {},
                metadata=row[8] or {},
                created_at=row[9],
                updated_at=row[10],
                role=MemberRole(row[11]),
                member_count=row[12],
            )
            orgs.append(org)

        return orgs

    def get_user_org_context(
        self,
        user_id: str,
        org_id: str,
    ) -> Optional[OrgContext]:
        """Get user's context within an organization.

        Args:
            user_id: User ID.
            org_id: Organization ID.

        Returns:
            OrgContext if user is a member, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT o.id as org_id, o.plan, o.settings,
                       m.user_id, m.role
                FROM organizations o
                JOIN org_memberships m ON o.id = m.org_id
                WHERE o.id = %s AND m.user_id = %s AND o.status = 'active'
                """,
                (org_id, user_id),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return OrgContext(
            org_id=row[0],
            user_id=row[3],
            role=MemberRole(row[4]),
            plan=OrgPlan(row[1]),
            settings=row[2] or {},
        )

    # =========================================================================
    # Membership Management
    # =========================================================================

    def add_member(
        self,
        org_id: str,
        request: CreateMembershipRequest,
        invited_by: Optional[str] = None,
    ) -> OrgMembership:
        """Add a member to an organization.

        Args:
            org_id: Organization ID.
            request: Membership creation request.
            invited_by: User ID of the inviter.

        Returns:
            The created membership.

        Raises:
            ValueError: If user is already a member.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Check for existing membership
            cursor.execute(
                "SELECT membership_id FROM org_memberships WHERE org_id = %s AND user_id = %s",
                (org_id, request.user_id),
            )
            if cursor.fetchone():
                raise ValueError(f"User {request.user_id} is already a member of org {org_id}")

            membership = OrgMembership(
                org_id=org_id,
                user_id=request.user_id,
                role=request.role,
                invited_by=invited_by,
                invited_at=datetime.utcnow() if invited_by else None,
            )

            cursor.execute(
                """
                INSERT INTO org_memberships (membership_id, org_id, user_id, role, invited_by, invited_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    membership.id,
                    membership.org_id,
                    membership.user_id,
                    membership.role.value,
                    membership.invited_by,
                    membership.invited_at,
                ),
            )
            conn.commit()

        logger.info(f"Added member {request.user_id} to org {org_id} as {request.role}")
        return membership

    def update_member_role(
        self,
        org_id: str,
        user_id: str,
        request: UpdateMembershipRequest,
    ) -> Optional[OrgMembership]:
        """Update a member's role.

        Args:
            org_id: Organization ID.
            user_id: User ID.
            request: Update request.

        Returns:
            Updated membership if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE org_memberships
                SET role = %s, updated_at = %s
                WHERE org_id = %s AND user_id = %s
                """,
                (request.role.value, datetime.utcnow(), org_id, user_id),
            )

            if cursor.rowcount == 0:
                return None

            cursor.execute(
                """
                SELECT membership_id, org_id, user_id, role, invited_by, invited_at, created_at, updated_at
                FROM org_memberships
                WHERE org_id = %s AND user_id = %s
                """,
                (org_id, user_id),
            )
            row = cursor.fetchone()
            conn.commit()

        if row is None:
            return None

        return OrgMembership(
            id=row[0],
            org_id=row[1],
            user_id=row[2],
            role=MemberRole(row[3]),
            invited_by=row[4],
            invited_at=row[5],
            created_at=row[6],
            updated_at=row[7],
        )

    def remove_member(self, org_id: str, user_id: str) -> bool:
        """Remove a member from an organization.

        Args:
            org_id: Organization ID.
            user_id: User ID.

        Returns:
            True if member was removed, False if not found.

        Raises:
            ValueError: If trying to remove the last owner.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Check if this is the last owner
            cursor.execute(
                """
                SELECT COUNT(*) FROM org_memberships
                WHERE org_id = %s AND role = 'owner'
                """,
                (org_id,),
            )
            owner_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT role = 'owner' FROM org_memberships
                WHERE org_id = %s AND user_id = %s
                """,
                (org_id, user_id),
            )
            row = cursor.fetchone()
            is_owner = row[0] if row else False

            if is_owner and owner_count <= 1:
                raise ValueError("Cannot remove the last owner of an organization")

            cursor.execute(
                "DELETE FROM org_memberships WHERE org_id = %s AND user_id = %s",
                (org_id, user_id),
            )
            removed = cursor.rowcount > 0
            conn.commit()

        if removed:
            logger.info(f"Removed member {user_id} from org {org_id}")

        return removed

    def list_members(self, org_id: str) -> List[OrgMembership]:
        """List all members of an organization.

        Args:
            org_id: Organization ID.

        Returns:
            List of memberships.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT membership_id, org_id, user_id, role, invited_by, invited_at, created_at, updated_at
                FROM org_memberships
                WHERE org_id = %s
                ORDER BY created_at
                """,
                (org_id,),
            )
            rows = cursor.fetchall()

        return [
            OrgMembership(
                id=row[0],
                org_id=row[1],
                user_id=row[2],
                role=MemberRole(row[3]),
                invited_by=row[4],
                invited_at=row[5],
                created_at=row[6],
                updated_at=row[7],
            )
            for row in rows
        ]

    # =========================================================================
    # Project Management
    # =========================================================================

    def create_project(
        self,
        org_id: str,
        name: str,
        owner_id: str,
        slug: Optional[str] = None,
        description: Optional[str] = None,
        visibility: ProjectVisibility = ProjectVisibility.PRIVATE,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Project:
        """Create a new project within an organization.

        Args:
            org_id: Organization ID.
            name: Project name.
            owner_id: User ID who will be the project owner.
            slug: Optional slug (auto-generated from name if not provided).
            description: Optional description.
            visibility: Project visibility (default: private).
            settings: Optional settings dict.

        Returns:
            The created project.

        Raises:
            ValueError: If slug is already taken within the org.
        """
        # Generate slug from name if not provided
        if slug is None:
            slug = name.lower().replace(" ", "-")

        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Check slug uniqueness within org
            cursor.execute(
                "SELECT project_id FROM projects WHERE org_id = %s AND slug = %s",
                (org_id, slug),
            )
            if cursor.fetchone():
                raise ValueError(f"Project slug '{slug}' is already taken in this organization")

            project = Project(
                org_id=org_id,
                name=name,
                slug=slug,
                description=description,
                visibility=visibility,
                settings=settings or {},
            )

            # Insert project
            cursor.execute(
                """
                INSERT INTO projects (project_id, org_id, name, slug, description, visibility, settings)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    project.id,
                    project.org_id,
                    project.name,
                    project.slug,
                    project.description,
                    project.visibility.value,
                    _jsonb(project.settings),
                ),
            )

            # Add owner membership
            cursor.execute(
                """
                INSERT INTO project_memberships (membership_id, project_id, user_id, role)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    f"pmem-{project.id[-12:]}",
                    project.id,
                    owner_id,
                    ProjectRole.OWNER.value,
                ),
            )
            conn.commit()

        # Auto-create default board if BoardService is available
        if self._board_service is not None:
            try:
                from guideai.services.board_service import Actor as BoardActor
                board_request = CreateBoardRequest(
                    project_id=project.id,
                    name="Default Board",
                    description=f"Default board for {name}",
                    is_default=True,
                    create_default_columns=True,
                )
                actor = BoardActor(id=owner_id, role="user", surface="api")
                self._board_service.create_board(board_request, actor, org_id=org_id)
                logger.info(f"Created default board for project {project.id}")
            except Exception as e:
                # Log but don't fail project creation if board creation fails
                logger.warning(f"Failed to create default board for project {project.id}: {e}")

        logger.info(f"Created project {project.id} in org {org_id}")
        return project

    def list_projects(self, org_id: str) -> List[Project]:
        """List all projects in an organization.

        Args:
            org_id: Organization ID.

        Returns:
            List of projects.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT project_id, org_id, name, slug, description, visibility, settings, created_at, updated_at
                FROM projects
                WHERE org_id = %s
                ORDER BY name
                """,
                (org_id,),
            )
            rows = cursor.fetchall()

        return [
            Project(
                id=row[0],
                org_id=row[1],
                name=row[2],
                slug=row[3],
                description=row[4],
                visibility=ProjectVisibility(row[5]),
                settings=row[6] or {},
                created_at=row[7],
                updated_at=row[8],
            )
            for row in rows
        ]

    def get_project(self, project_id: str, org_id: Optional[str] = None) -> Optional[Project]:
        """Get a project by ID.

        Args:
            project_id: Project ID.
            org_id: Optional org ID for cross-org validation (security check).

        Returns:
            The project if found and not archived, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            if org_id:
                cursor.execute(
                    """
                    SELECT project_id, org_id, name, slug, description, visibility,
                           settings, archived_at, created_at, updated_at
                    FROM projects
                    WHERE project_id = %s AND org_id = %s AND archived_at IS NULL
                    """,
                    (project_id, org_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT project_id, org_id, name, slug, description, visibility,
                           settings, archived_at, created_at, updated_at
                    FROM projects
                    WHERE project_id = %s AND archived_at IS NULL
                    """,
                    (project_id,),
                )
            row = cursor.fetchone()

        if not row:
            return None

        return Project(
            id=row[0],
            org_id=row[1],
            name=row[2],
            slug=row[3],
            description=row[4],
            visibility=ProjectVisibility(row[5]),
            settings=row[6] or {},
            created_at=row[8],
            updated_at=row[9],
        )

    def get_project_by_slug(self, org_id: str, slug: str) -> Optional[Project]:
        """Get a project by organization ID and slug.

        Args:
            org_id: Organization ID.
            slug: Project slug (unique within org).

        Returns:
            The project if found and not archived, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT project_id, org_id, name, slug, description, visibility,
                       settings, archived_at, created_at, updated_at
                FROM projects
                WHERE org_id = %s AND slug = %s AND archived_at IS NULL
                """,
                (org_id, slug),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return Project(
            id=row[0],
            org_id=row[1],
            name=row[2],
            slug=row[3],
            description=row[4],
            visibility=ProjectVisibility(row[5]),
            settings=row[6] or {},
            created_at=row[8],
            updated_at=row[9],
        )

    def update_project(
        self,
        project_id: str,
        request: UpdateProjectRequest,
        org_id: Optional[str] = None,
    ) -> Optional[Project]:
        """Update a project.

        Args:
            project_id: Project ID.
            request: Update request with fields to modify.
            org_id: Optional org ID for cross-org validation (security check).

        Returns:
            The updated project if found, None otherwise.
        """
        # Build dynamic update query
        updates = []
        params = []

        if request.name is not None:
            updates.append("name = %s")
            params.append(request.name)

        if request.description is not None:
            updates.append("description = %s")
            params.append(request.description)

        if request.visibility is not None:
            updates.append("visibility = %s")
            params.append(request.visibility.value)

        if request.settings is not None:
            updates.append("settings = %s")
            params.append(_jsonb(request.settings))

        if not updates:
            # No changes requested
            return self.get_project(project_id, org_id)

        updates.append("updated_at = %s")
        params.append(datetime.utcnow())
        params.append(project_id)

        # Add org_id filter if provided for security
        org_filter = "AND org_id = %s" if org_id else ""
        if org_id:
            params.append(org_id)

        query = f"""
            UPDATE projects
            SET {', '.join(updates)}
            WHERE project_id = %s AND archived_at IS NULL {org_filter}
        """

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            conn.commit()

        return self.get_project(project_id, org_id)

    def delete_project(self, project_id: str, org_id: Optional[str] = None) -> bool:
        """Soft-delete a project by setting archived_at timestamp.

        When a project is archived, agents assigned to it are unassigned
        (project_id set to NULL) rather than deleted.

        Args:
            project_id: Project ID.
            org_id: Optional org ID for cross-org validation (security check).

        Returns:
            True if project was archived, False if not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Build query with optional org filter
            org_filter = "AND org_id = %s" if org_id else ""
            params = [datetime.utcnow(), project_id]
            if org_id:
                params.append(org_id)

            cursor.execute(
                f"""
                UPDATE projects
                SET archived_at = %s, updated_at = %s
                WHERE project_id = %s AND archived_at IS NULL {org_filter}
                """.replace("updated_at = %s", "updated_at = archived_at"),
                tuple(params),
            )
            # Fix: actually use two timestamps
            cursor.execute(
                f"""
                UPDATE projects
                SET archived_at = %s, updated_at = %s
                WHERE project_id = %s AND archived_at IS NULL {org_filter}
                """,
                tuple([datetime.utcnow(), datetime.utcnow(), project_id] + ([org_id] if org_id else [])),
            )
            deleted = cursor.rowcount > 0

            if deleted:
                # Unassign agents from this project (cascade behavior)
                cursor.execute(
                    """
                    UPDATE agents
                    SET project_id = NULL, updated_at = %s
                    WHERE project_id = %s
                    """,
                    (datetime.utcnow(), project_id),
                )

            conn.commit()

        if deleted:
            logger.info(f"Soft-deleted project {project_id}")

        return deleted

    def restore_project(self, project_id: str, org_id: Optional[str] = None) -> Optional[Project]:
        """Restore a soft-deleted project.

        Args:
            project_id: Project ID.
            org_id: Optional org ID for cross-org validation (security check).

        Returns:
            The restored project if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            org_filter = "AND org_id = %s" if org_id else ""
            params = [datetime.utcnow(), project_id]
            if org_id:
                params.append(org_id)

            cursor.execute(
                f"""
                UPDATE projects
                SET archived_at = NULL, updated_at = %s
                WHERE project_id = %s AND archived_at IS NOT NULL {org_filter}
                """,
                tuple(params),
            )
            restored = cursor.rowcount > 0
            conn.commit()

        if restored:
            logger.info(f"Restored project {project_id}")
            return self.get_project(project_id, org_id)

        return None

    # =========================================================================
    # Project Membership Management
    # =========================================================================

    def add_project_member(
        self,
        project_id: str,
        user_id: str,
        role: ProjectRole = ProjectRole.CONTRIBUTOR,
    ) -> ProjectMembership:
        """Add a member to a project.

        Args:
            project_id: Project ID.
            user_id: User ID to add.
            role: Role to assign (default: contributor).

        Returns:
            The created membership.

        Raises:
            ValueError: If user is already a project member.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Check for existing membership
            cursor.execute(
                "SELECT membership_id FROM project_memberships WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )
            if cursor.fetchone():
                raise ValueError(f"User {user_id} is already a member of project {project_id}")

            membership = ProjectMembership(
                project_id=project_id,
                user_id=user_id,
                role=role,
            )

            cursor.execute(
                """
                INSERT INTO project_memberships (membership_id, project_id, user_id, role)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    membership.id,
                    membership.project_id,
                    membership.user_id,
                    membership.role.value,
                ),
            )
            conn.commit()

        logger.info(f"Added member {user_id} to project {project_id} as {role}")
        return membership

    def remove_project_member(self, project_id: str, user_id: str) -> bool:
        """Remove a member from a project.

        Args:
            project_id: Project ID.
            user_id: User ID to remove.

        Returns:
            True if member was removed, False if not found.

        Raises:
            ValueError: If trying to remove the last owner.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Check if this is the last owner
            cursor.execute(
                """
                SELECT COUNT(*) FROM project_memberships
                WHERE project_id = %s AND role = 'owner'
                """,
                (project_id,),
            )
            owner_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT role = 'owner' FROM project_memberships
                WHERE project_id = %s AND user_id = %s
                """,
                (project_id, user_id),
            )
            row = cursor.fetchone()
            is_owner = row[0] if row else False

            if is_owner and owner_count <= 1:
                raise ValueError("Cannot remove the last owner of a project")

            cursor.execute(
                "DELETE FROM project_memberships WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )
            removed = cursor.rowcount > 0
            conn.commit()

        if removed:
            logger.info(f"Removed member {user_id} from project {project_id}")

        return removed

    def list_project_members(self, project_id: str) -> List[ProjectMembership]:
        """List all members of a project.

        Args:
            project_id: Project ID.

        Returns:
            List of project memberships.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT membership_id, project_id, user_id, role, created_at, updated_at
                FROM project_memberships
                WHERE project_id = %s
                ORDER BY created_at
                """,
                (project_id,),
            )
            rows = cursor.fetchall()

        return [
            ProjectMembership(
                id=row[0],
                project_id=row[1],
                user_id=row[2],
                role=ProjectRole(row[3]),
                created_at=row[4],
                updated_at=row[5] if len(row) > 5 else row[4],
            )
            for row in rows
        ]

    def update_project_member_role(
        self,
        project_id: str,
        user_id: str,
        new_role: ProjectRole,
    ) -> Optional[ProjectMembership]:
        """Update a project member's role.

        Args:
            project_id: Project ID.
            user_id: User ID.
            new_role: New role to assign.

        Returns:
            Updated membership if found, None otherwise.

        Raises:
            ValueError: If demoting the last owner.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Check if this is the last owner being demoted
            if new_role != ProjectRole.OWNER:
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM project_memberships
                    WHERE project_id = %s AND role = 'owner'
                    """,
                    (project_id,),
                )
                owner_count = cursor.fetchone()[0]

                cursor.execute(
                    """
                    SELECT role = 'owner' FROM project_memberships
                    WHERE project_id = %s AND user_id = %s
                    """,
                    (project_id, user_id),
                )
                row = cursor.fetchone()
                is_owner = row[0] if row else False

                if is_owner and owner_count <= 1:
                    raise ValueError("Cannot demote the last owner of a project")

            cursor.execute(
                """
                UPDATE project_memberships
                SET role = %s
                WHERE project_id = %s AND user_id = %s
                """,
                (new_role.value, project_id, user_id),
            )

            if cursor.rowcount == 0:
                return None

            cursor.execute(
                """
                SELECT membership_id, project_id, user_id, role, created_at
                FROM project_memberships
                WHERE project_id = %s AND user_id = %s
                """,
                (project_id, user_id),
            )
            row = cursor.fetchone()
            conn.commit()

        if row is None:
            return None

        return ProjectMembership(
            id=row[0],
            project_id=row[1],
            user_id=row[2],
            role=ProjectRole(row[3]),
            created_at=row[4],
        )

    def create_agent(
        self,
        org_id: str,
        name: str,
        agent_type: str,
        owner_id: str,
        project_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[str]] = None,
    ) -> Agent:
        """Create a new agent within an organization.

        Args:
            org_id: Organization ID.
            name: Agent name.
            agent_type: Type of agent (general, code, data, research).
            owner_id: User ID who owns the agent.
            project_id: Optional project ID to associate with.
            config: Optional configuration dict.
            capabilities: Optional list of capability strings.

        Returns:
            The created agent.
        """
        agent = Agent(
            org_id=org_id,
            project_id=project_id,
            name=name,
            agent_type=AgentType(agent_type),
            config=config or {},
            capabilities=capabilities or [],
        )

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO agents (agent_id, org_id, project_id, name, agent_type, config, capabilities)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    agent.id,
                    agent.org_id,
                    agent.project_id,
                    agent.name,
                    agent.agent_type.value,
                    _jsonb(agent.config),
                    _jsonb(agent.capabilities),
                ),
            )
            conn.commit()

        logger.info(f"Created agent {agent.id} in org {org_id}")
        return agent

    def list_agents(
        self,
        org_id: str,
        project_id: Optional[str] = None,
    ) -> List[Agent]:
        """List agents in an organization.

        Args:
            org_id: Organization ID.
            project_id: Optional project ID to filter by.

        Returns:
            List of agents.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            if project_id:
                cursor.execute(
                    """
                    SELECT agent_id, org_id, project_id, name, agent_type, status, config, capabilities, created_at, updated_at
                    FROM agents
                    WHERE org_id = %s AND project_id = %s AND status != 'archived'
                    ORDER BY name
                    """,
                    (org_id, project_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT agent_id, org_id, project_id, name, agent_type, status, config, capabilities, created_at, updated_at
                    FROM agents
                    WHERE org_id = %s AND status != 'archived'
                    ORDER BY name
                    """,
                    (org_id,),
                )
            rows = cursor.fetchall()

        return [
            Agent(
                id=row[0],
                org_id=row[1],
                project_id=row[2],
                name=row[3],
                agent_type=AgentType(row[4]),
                status=AgentStatus(row[5]),
                config=row[6] or {},
                capabilities=row[7] or [],
                created_at=row[8],
                updated_at=row[9],
            )
            for row in rows
        ]

    def get_agent(self, agent_id: str, org_id: Optional[str] = None) -> Optional[Agent]:
        """Get an agent by ID.

        Args:
            agent_id: Agent ID.
            org_id: Optional org ID for cross-org validation (security check).

        Returns:
            The agent if found and not archived, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            if org_id:
                cursor.execute(
                    """
                    SELECT agent_id, org_id, project_id, name, agent_type, status,
                           config, capabilities, created_at, updated_at
                    FROM agents
                    WHERE agent_id = %s AND org_id = %s AND status != 'archived'
                    """,
                    (agent_id, org_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT agent_id, org_id, project_id, name, agent_type, status,
                           config, capabilities, created_at, updated_at
                    FROM agents
                    WHERE agent_id = %s AND status != 'archived'
                    """,
                    (agent_id,),
                )
            row = cursor.fetchone()

        if not row:
            return None

        return Agent(
            id=row[0],
            org_id=row[1],
            project_id=row[2],
            name=row[3],
            agent_type=AgentType(row[4]),
            status=AgentStatus(row[5]),
            config=row[6] or {},
            capabilities=row[7] or [],
            created_at=row[8],
            updated_at=row[9],
        )

    def update_agent(
        self,
        agent_id: str,
        request: UpdateAgentRequest,
        org_id: Optional[str] = None,
    ) -> Optional[Agent]:
        """Update an agent.

        Args:
            agent_id: Agent ID.
            request: Update request with fields to modify.
            org_id: Optional org ID for cross-org validation (security check).

        Returns:
            The updated agent if found, None otherwise.
        """
        # Build dynamic update query
        updates = []
        params = []

        if request.name is not None:
            updates.append("name = %s")
            params.append(request.name)

        if request.status is not None:
            updates.append("status = %s")
            params.append(request.status.value)

        if request.config is not None:
            updates.append("config = %s")
            params.append(_jsonb(request.config))

        if request.capabilities is not None:
            updates.append("capabilities = %s")
            params.append(_jsonb(request.capabilities))

        if not updates:
            # No changes requested
            return self.get_agent(agent_id, org_id)

        updates.append("updated_at = %s")
        params.append(datetime.utcnow())
        params.append(agent_id)

        # Add org_id filter if provided for security
        org_filter = "AND org_id = %s" if org_id else ""
        if org_id:
            params.append(org_id)

        query = f"""
            UPDATE agents
            SET {', '.join(updates)}
            WHERE agent_id = %s AND status != 'archived' {org_filter}
        """

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            conn.commit()

        return self.get_agent(agent_id, org_id)

    def delete_agent(self, agent_id: str, org_id: Optional[str] = None) -> bool:
        """Soft-delete an agent by setting status to 'archived'.

        Args:
            agent_id: Agent ID.
            org_id: Optional org ID for cross-org validation (security check).

        Returns:
            True if agent was archived, False if not found.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Build query with optional org filter
            org_filter = "AND org_id = %s" if org_id else ""
            params = [datetime.utcnow(), agent_id]
            if org_id:
                params.append(org_id)

            cursor.execute(
                f"""
                UPDATE agents
                SET status = 'archived', updated_at = %s
                WHERE agent_id = %s AND status != 'archived' {org_filter}
                """,
                tuple(params),
            )
            deleted = cursor.rowcount > 0
            conn.commit()

        if deleted:
            logger.info(f"Soft-deleted (archived) agent {agent_id}")

        return deleted

    def restore_agent(self, agent_id: str, org_id: Optional[str] = None) -> Optional[Agent]:
        """Restore a soft-deleted (archived) agent.

        Args:
            agent_id: Agent ID.
            org_id: Optional org ID for cross-org validation (security check).

        Returns:
            The restored agent if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            org_filter = "AND org_id = %s" if org_id else ""
            params = [datetime.utcnow(), agent_id]
            if org_id:
                params.append(org_id)

            cursor.execute(
                f"""
                UPDATE agents
                SET status = 'active', updated_at = %s
                WHERE agent_id = %s AND status = 'archived' {org_filter}
                """,
                tuple(params),
            )
            restored = cursor.rowcount > 0
            conn.commit()

        if restored:
            logger.info(f"Restored agent {agent_id}")
            return self.get_agent(agent_id, org_id)

        return None

    def assign_agent_to_project(
        self,
        agent_id: str,
        project_id: Optional[str],
        org_id: Optional[str] = None,
    ) -> Optional[Agent]:
        """Assign or unassign an agent to/from a project.

        Args:
            agent_id: Agent ID.
            project_id: Project ID to assign to, or None to unassign.
            org_id: Optional org ID for cross-org validation (security check).

        Returns:
            The updated agent if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            org_filter = "AND org_id = %s" if org_id else ""
            params = [project_id, datetime.utcnow(), agent_id]
            if org_id:
                params.append(org_id)

            cursor.execute(
                f"""
                UPDATE agents
                SET project_id = %s, updated_at = %s
                WHERE agent_id = %s AND status != 'archived' {org_filter}
                """,
                tuple(params),
            )
            updated = cursor.rowcount > 0
            conn.commit()

        if updated:
            action = f"assigned to project {project_id}" if project_id else "unassigned from project"
            logger.info(f"Agent {agent_id} {action}")
            return self.get_agent(agent_id, org_id)

        return None

    # =========================================================================
    # Agent Status Tracking
    # =========================================================================

    def update_agent_status(
        self,
        agent_id: str,
        org_id: str,
        new_status: "AgentStatus",
        triggered_by: str,
        trigger: "AgentStatusTransitionTrigger",
        reason: Optional[str] = None,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional["AgentStatusEvent"]:
        """Update an agent's status with full audit trail.

        Validates the transition is allowed, updates the agent, records
        the transition in the audit table, and emits Raze telemetry.

        Args:
            agent_id: Agent ID.
            org_id: Organization ID (for security validation).
            new_status: Target status.
            triggered_by: User ID who triggered the change.
            trigger: What triggered this change.
            reason: Optional reason for the change.
            task_id: Optional task ID (required for task-related triggers).
            metadata: Optional additional metadata.

        Returns:
            AgentStatusEvent if successful, None if agent not found.

        Raises:
            ValueError: If the transition is invalid.
        """
        from .contracts import (
            AgentStatusTransitionTrigger,
            AgentStatusEvent,
            is_valid_status_transition,
        )

        # Get current agent status
        agent = self.get_agent(agent_id, org_id)
        if not agent:
            return None

        old_status = agent.status

        # Validate transition
        if not is_valid_status_transition(old_status, new_status):
            raise ValueError(
                f"Invalid status transition: {old_status.value} → {new_status.value}"
            )

        now = datetime.utcnow()
        event_metadata = metadata or {}

        # Create status event
        event = AgentStatusEvent(
            agent_id=agent_id,
            org_id=org_id,
            from_status=old_status,
            to_status=new_status,
            reason=reason,
            trigger=trigger,
            triggered_by=triggered_by,
            task_id=task_id,
            metadata=event_metadata,
            created_at=now,
            notification_channel=f"agent:{agent_id}:status",
        )

        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Update agent status
            cursor.execute(
                """
                UPDATE agents
                SET status = %s, updated_at = %s, last_status_change = %s
                WHERE agent_id = %s AND org_id = %s AND status != 'archived'
                """,
                (new_status.value, now, now, agent_id, org_id),
            )

            if cursor.rowcount == 0:
                return None

            # Record transition in audit table
            cursor.execute(
                """
                INSERT INTO agent_status_transitions
                    (agent_id, from_status, to_status, triggered_by, trigger_type, task_id, reason, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    agent_id,
                    old_status.value,
                    new_status.value,
                    triggered_by,
                    trigger.value,
                    task_id,
                    reason,
                    _jsonb(event_metadata),
                ),
            )

            conn.commit()

        # Emit Raze telemetry (if available)
        self._emit_status_change_telemetry(event)

        logger.info(
            f"Agent {agent_id} status changed: {old_status.value} → {new_status.value} "
            f"(trigger: {trigger.value}, by: {triggered_by})"
        )

        return event

    def _emit_status_change_telemetry(self, event: "AgentStatusEvent") -> None:
        """Emit Raze telemetry for agent status change.

        This is a separate method to allow subclasses to override or
        to facilitate testing without Raze dependencies.
        """
        try:
            from raze import RazeLogger
            raze_logger = RazeLogger(service_name="organization_service")
            raze_logger.info(
                "agent_status_changed",
                event_id=event.id,
                agent_id=event.agent_id,
                org_id=event.org_id,
                from_status=event.from_status.value,
                to_status=event.to_status.value,
                trigger=event.trigger.value,
                triggered_by=event.triggered_by,
                task_id=event.task_id,
                reason=event.reason,
                notification_channel=event.notification_channel,
            )
        except ImportError:
            # Raze not available, skip telemetry
            pass
        except Exception as e:
            # Don't fail the operation if telemetry fails
            logger.warning(f"Failed to emit Raze telemetry for agent status change: {e}")

    def pause_agent(
        self,
        agent_id: str,
        org_id: str,
        triggered_by: str,
        reason: Optional[str] = None,
    ) -> Optional["AgentStatusEvent"]:
        """Pause an agent (convenience method).

        Args:
            agent_id: Agent ID.
            org_id: Organization ID.
            triggered_by: User ID who triggered the pause.
            reason: Optional reason for pausing.

        Returns:
            AgentStatusEvent if successful, None if agent not found.
        """
        from .contracts import AgentStatusTransitionTrigger

        return self.update_agent_status(
            agent_id=agent_id,
            org_id=org_id,
            new_status=AgentStatus.PAUSED,
            triggered_by=triggered_by,
            trigger=AgentStatusTransitionTrigger.MANUAL,
            reason=reason or "Agent paused",
        )

    def activate_agent(
        self,
        agent_id: str,
        org_id: str,
        triggered_by: str,
        reason: Optional[str] = None,
    ) -> Optional["AgentStatusEvent"]:
        """Activate an agent (convenience method).

        Args:
            agent_id: Agent ID.
            org_id: Organization ID.
            triggered_by: User ID who triggered the activation.
            reason: Optional reason for activating.

        Returns:
            AgentStatusEvent if successful, None if agent not found.
        """
        from .contracts import AgentStatusTransitionTrigger

        return self.update_agent_status(
            agent_id=agent_id,
            org_id=org_id,
            new_status=AgentStatus.ACTIVE,
            triggered_by=triggered_by,
            trigger=AgentStatusTransitionTrigger.MANUAL,
            reason=reason or "Agent activated",
        )

    def disable_agent(
        self,
        agent_id: str,
        org_id: str,
        triggered_by: str,
        reason: Optional[str] = None,
    ) -> Optional["AgentStatusEvent"]:
        """Disable an agent (convenience method).

        Args:
            agent_id: Agent ID.
            org_id: Organization ID.
            triggered_by: User ID who triggered the disable.
            reason: Optional reason for disabling.

        Returns:
            AgentStatusEvent if successful, None if agent not found.
        """
        from .contracts import AgentStatusTransitionTrigger

        return self.update_agent_status(
            agent_id=agent_id,
            org_id=org_id,
            new_status=AgentStatus.DISABLED,
            triggered_by=triggered_by,
            trigger=AgentStatusTransitionTrigger.MANUAL,
            reason=reason or "Agent disabled",
        )

    def start_agent_task(
        self,
        agent_id: str,
        org_id: str,
        task_id: str,
        triggered_by: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional["AgentStatusEvent"]:
        """Mark agent as busy when starting a task (automatic transition).

        This implements the automatic IDLE/ACTIVE → BUSY transition
        when an agent starts working on a task.

        Args:
            agent_id: Agent ID.
            org_id: Organization ID.
            task_id: ID of the task being started.
            triggered_by: User ID who triggered the task.
            metadata: Optional task metadata.

        Returns:
            AgentStatusEvent if transition occurred, None if agent not found
            or already busy.
        """
        from .contracts import AgentStatusTransitionTrigger

        agent = self.get_agent(agent_id, org_id)
        if not agent:
            return None

        # Only transition if agent is in a valid starting state
        if agent.status not in (AgentStatus.ACTIVE, AgentStatus.IDLE):
            logger.debug(
                f"Agent {agent_id} cannot start task: current status is {agent.status.value}"
            )
            return None

        return self.update_agent_status(
            agent_id=agent_id,
            org_id=org_id,
            new_status=AgentStatus.BUSY,
            triggered_by=triggered_by,
            trigger=AgentStatusTransitionTrigger.TASK_START,
            task_id=task_id,
            reason=f"Started task {task_id}",
            metadata=metadata,
        )

    def complete_agent_task(
        self,
        agent_id: str,
        org_id: str,
        task_id: str,
        triggered_by: str,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional["AgentStatusEvent"]:
        """Mark agent as idle when completing a task (automatic transition).

        This implements the automatic BUSY → IDLE transition
        when an agent finishes a task.

        Args:
            agent_id: Agent ID.
            org_id: Organization ID.
            task_id: ID of the completed task.
            triggered_by: User ID who triggered the completion.
            success: Whether the task completed successfully.
            metadata: Optional completion metadata.

        Returns:
            AgentStatusEvent if transition occurred, None if agent not found
            or not busy.
        """
        from .contracts import AgentStatusTransitionTrigger

        agent = self.get_agent(agent_id, org_id)
        if not agent:
            return None

        # Only transition if agent is busy
        if agent.status != AgentStatus.BUSY:
            logger.debug(
                f"Agent {agent_id} cannot complete task: current status is {agent.status.value}"
            )
            return None

        trigger = (
            AgentStatusTransitionTrigger.TASK_COMPLETE if success
            else AgentStatusTransitionTrigger.TASK_ERROR
        )

        completion_metadata = metadata or {}
        completion_metadata["success"] = success

        return self.update_agent_status(
            agent_id=agent_id,
            org_id=org_id,
            new_status=AgentStatus.IDLE,
            triggered_by=triggered_by,
            trigger=trigger,
            task_id=task_id,
            reason=f"{'Completed' if success else 'Failed'} task {task_id}",
            metadata=completion_metadata,
        )

    def get_agent_status_history(
        self,
        agent_id: str,
        org_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> Optional["AgentStatusHistory"]:
        """Get the status change history for an agent.

        Args:
            agent_id: Agent ID.
            org_id: Organization ID.
            limit: Maximum number of events to return.
            offset: Number of events to skip.

        Returns:
            AgentStatusHistory if agent found, None otherwise.
        """
        from .contracts import AgentStatusEvent, AgentStatusHistory, AgentStatusTransitionTrigger

        agent = self.get_agent(agent_id, org_id)
        if not agent:
            return None

        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Get total count
            cursor.execute(
                """
                SELECT COUNT(*) FROM agent_status_transitions
                WHERE agent_id = %s
                """,
                (agent_id,),
            )
            total = cursor.fetchone()[0]

            # Get events
            cursor.execute(
                """
                SELECT id, from_status, to_status, triggered_by, trigger_type,
                       task_id, reason, metadata, created_at
                FROM agent_status_transitions
                WHERE agent_id = %s
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (agent_id, limit, offset),
            )
            rows = cursor.fetchall()

        events = [
            AgentStatusEvent(
                id=f"ase-{row[0]}",
                agent_id=agent_id,
                org_id=org_id,
                from_status=AgentStatus(row[1]),
                to_status=AgentStatus(row[2]),
                triggered_by=row[3],
                trigger=AgentStatusTransitionTrigger(row[4]),
                task_id=row[5],
                reason=row[6],
                metadata=row[7] or {},
                created_at=row[8],
                notification_channel=f"agent:{agent_id}:status",
            )
            for row in rows
        ]

        return AgentStatusHistory(
            agent_id=agent_id,
            events=events,
            total=total,
            current_status=agent.status,
        )

    # =========================================================================
    # Usage Tracking
    # =========================================================================

    def record_usage(
        self,
        org_id: str,
        request: RecordUsageRequest,
    ) -> UsageRecord:
        """Record usage for metered billing.

        Args:
            org_id: Organization ID.
            request: Usage record request.

        Returns:
            The created usage record.
        """
        record = UsageRecord(
            org_id=org_id,
            metric_name=request.metric_name,
            quantity=request.quantity,
            metadata=request.metadata,
        )

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO usage_records (record_id, org_id, metric_name, quantity, recorded_at, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    record.id,
                    record.org_id,
                    record.metric_name,
                    record.quantity,
                    record.recorded_at,
                    _jsonb(record.metadata),
                ),
            )
            conn.commit()

        return record

    def get_usage_summary(
        self,
        org_id: str,
        metric_name: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
    ) -> int:
        """Get total usage for a metric in a time period.

        Args:
            org_id: Organization ID.
            metric_name: Name of the metric.
            start_date: Start of the period.
            end_date: End of the period (defaults to now).

        Returns:
            Total quantity used.
        """
        end_date = end_date or datetime.utcnow()

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COALESCE(SUM(quantity), 0)
                FROM usage_records
                WHERE org_id = %s AND metric_name = %s
                  AND recorded_at >= %s AND recorded_at <= %s
                """,
                (org_id, metric_name, start_date, end_date),
            )
            total = cursor.fetchone()[0]

        return total

    # =========================================================================
    # User-Owned Resources (Personal Projects/Agents without Org)
    # =========================================================================

    def create_personal_project(
        self,
        owner_id: str,
        name: str,
        slug: Optional[str] = None,
        description: Optional[str] = None,
        visibility: ProjectVisibility = ProjectVisibility.PRIVATE,
        settings: Optional[Dict[str, Any]] = None,
    ) -> Project:
        """Create a personal project owned by a user (no org required).

        Args:
            owner_id: User ID who will own the project.
            name: Project name.
            slug: Optional slug (auto-generated from name if not provided).
            description: Optional description.
            visibility: Project visibility (default: private).
            settings: Optional settings dict.

        Returns:
            The created project.

        Raises:
            ValueError: If slug is already taken by the user.
        """
        if slug is None:
            slug = name.lower().replace(" ", "-")

        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Check slug uniqueness for this user
            cursor.execute(
                "SELECT project_id FROM projects WHERE owner_id = %s AND slug = %s",
                (owner_id, slug),
            )
            if cursor.fetchone():
                raise ValueError(f"Project slug '{slug}' is already taken")

            project = Project(
                owner_id=owner_id,
                name=name,
                slug=slug,
                description=description,
                visibility=visibility,
                settings=settings or {},
            )

            cursor.execute(
                """
                INSERT INTO projects (project_id, owner_id, name, slug, description, visibility, settings, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    project.id,
                    project.owner_id,
                    project.name,
                    project.slug,
                    project.description,
                    project.visibility.value,
                    _jsonb(project.settings),
                    owner_id,
                ),
            )
            conn.commit()

        logger.info(f"Created personal project {project.id} for user {owner_id}")
        return project

    def list_personal_projects(self, owner_id: str) -> List[Project]:
        """List all personal projects owned by a user.

        Args:
            owner_id: User ID.

        Returns:
            List of projects owned by the user.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT project_id, owner_id, name, slug, description, visibility,
                       settings, created_at, updated_at
                FROM projects
                WHERE owner_id = %s AND archived_at IS NULL
                ORDER BY name
                """,
                (owner_id,),
            )
            rows = cursor.fetchall()

        return [
            Project(
                id=row[0],
                owner_id=row[1],
                name=row[2],
                slug=row[3],
                description=row[4],
                visibility=ProjectVisibility(row[5]),
                settings=row[6] or {},
                created_at=row[7],
                updated_at=row[8],
            )
            for row in rows
        ]

    def create_personal_agent(
        self,
        owner_id: str,
        name: str,
        agent_type: str = "specialist",
        project_id: Optional[str] = None,
        config: Optional[Dict[str, Any]] = None,
        capabilities: Optional[List[str]] = None,
    ) -> Agent:
        """Create a personal agent owned by a user (no org required).

        Args:
            owner_id: User ID who will own the agent.
            name: Agent name.
            agent_type: Type of agent.
            project_id: Optional project ID to associate with.
            config: Optional configuration dict.
            capabilities: Optional list of capability strings.

        Returns:
            The created agent.
        """
        agent = Agent(
            owner_id=owner_id,
            project_id=project_id,
            name=name,
            agent_type=AgentType(agent_type),
            config=config or {},
            capabilities=capabilities or [],
        )

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO agents (agent_id, owner_id, project_id, name, agent_type, config, capabilities, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    agent.id,
                    agent.owner_id,
                    agent.project_id,
                    agent.name,
                    agent.agent_type.value,
                    _jsonb(agent.config),
                    _jsonb(agent.capabilities),
                    owner_id,
                ),
            )
            conn.commit()

        logger.info(f"Created personal agent {agent.id} for user {owner_id}")
        return agent

    def list_personal_agents(
        self,
        owner_id: str,
        project_id: Optional[str] = None,
    ) -> List[Agent]:
        """List personal agents owned by a user.

        Args:
            owner_id: User ID.
            project_id: Optional project ID to filter by.

        Returns:
            List of agents owned by the user.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            if project_id:
                cursor.execute(
                    """
                    SELECT agent_id, owner_id, project_id, name, agent_type, status,
                           config, capabilities, created_at, updated_at
                    FROM agents
                    WHERE owner_id = %s AND project_id = %s AND status != 'archived'
                    ORDER BY name
                    """,
                    (owner_id, project_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT agent_id, owner_id, project_id, name, agent_type, status,
                           config, capabilities, created_at, updated_at
                    FROM agents
                    WHERE owner_id = %s AND status != 'archived'
                    ORDER BY name
                    """,
                    (owner_id,),
                )
            rows = cursor.fetchall()

        return [
            Agent(
                id=row[0],
                owner_id=row[1],
                project_id=row[2],
                name=row[3],
                agent_type=AgentType(row[4]),
                status=AgentStatus(row[5]),
                config=row[6] or {},
                capabilities=row[7] or [],
                created_at=row[8],
                updated_at=row[9],
            )
            for row in rows
        ]

    # =========================================================================
    # Project Collaborators (Share personal projects without creating an org)
    # =========================================================================

    def add_collaborator(
        self,
        project_id: str,
        user_id: str,
        invited_by: str,
        role: ProjectRole = ProjectRole.CONTRIBUTOR,
    ) -> ProjectCollaborator:
        """Add a collaborator to a personal project.

        Only the project owner can add collaborators.

        Args:
            project_id: Project ID (must be a personal project).
            user_id: User ID of the collaborator to add.
            invited_by: User ID who is inviting (must be project owner).
            role: Role to assign to the collaborator.

        Returns:
            The created collaborator invitation.

        Raises:
            ValueError: If project is not a personal project or user already a collaborator.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Verify project is personal and inviter is owner
            cursor.execute(
                "SELECT owner_id FROM projects WHERE project_id = %s AND owner_id IS NOT NULL",
                (project_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("Project is not a personal project or doesn't exist")
            if row[0] != invited_by:
                raise ValueError("Only the project owner can add collaborators")

            # Check if already a collaborator
            cursor.execute(
                "SELECT collaborator_id FROM project_collaborators WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )
            if cursor.fetchone():
                raise ValueError("User is already a collaborator on this project")

            collab = ProjectCollaborator(
                project_id=project_id,
                user_id=user_id,
                role=role,
                invited_by=invited_by,
            )

            cursor.execute(
                """
                INSERT INTO project_collaborators (collaborator_id, project_id, user_id, role, invited_by, invited_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    collab.id,
                    collab.project_id,
                    collab.user_id,
                    collab.role.value,
                    collab.invited_by,
                    collab.invited_at,
                ),
            )
            conn.commit()

        logger.info(f"Added collaborator {user_id} to project {project_id}")
        return collab

    def accept_collaboration(
        self,
        collaborator_id: str,
        user_id: str,
    ) -> bool:
        """Accept a collaboration invitation.

        Args:
            collaborator_id: Collaborator ID.
            user_id: User accepting (must match the collaborator's user_id).

        Returns:
            True if accepted, False if not found or already accepted.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE project_collaborators
                SET accepted_at = %s, updated_at = %s
                WHERE collaborator_id = %s AND user_id = %s AND accepted_at IS NULL
                """,
                (datetime.utcnow(), datetime.utcnow(), collaborator_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def list_project_collaborators(self, project_id: str) -> List[ProjectCollaborator]:
        """List all collaborators on a project.

        Args:
            project_id: Project ID.

        Returns:
            List of collaborators.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT collaborator_id, project_id, user_id, role, invited_by,
                       invited_at, accepted_at, created_at, updated_at
                FROM project_collaborators
                WHERE project_id = %s
                ORDER BY created_at
                """,
                (project_id,),
            )
            rows = cursor.fetchall()

        return [
            ProjectCollaborator(
                id=row[0],
                project_id=row[1],
                user_id=row[2],
                role=ProjectRole(row[3]),
                invited_by=row[4],
                invited_at=row[5],
                accepted_at=row[6],
                created_at=row[7],
                updated_at=row[8],
            )
            for row in rows
        ]

    def list_user_collaborations(self, user_id: str, accepted_only: bool = True) -> List[Project]:
        """List projects where user is a collaborator.

        Args:
            user_id: User ID.
            accepted_only: If True, only include accepted collaborations.

        Returns:
            List of projects the user is collaborating on.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            accepted_filter = "AND pc.accepted_at IS NOT NULL" if accepted_only else ""
            cursor.execute(
                f"""
                SELECT p.project_id, p.owner_id, p.name, p.slug, p.description,
                       p.visibility, p.settings, p.created_at, p.updated_at
                FROM projects p
                JOIN project_collaborators pc ON p.project_id = pc.project_id
                WHERE pc.user_id = %s {accepted_filter}
                ORDER BY p.name
                """,
                (user_id,),
            )
            rows = cursor.fetchall()

        return [
            Project(
                id=row[0],
                owner_id=row[1],
                name=row[2],
                slug=row[3],
                description=row[4],
                visibility=ProjectVisibility(row[5]),
                settings=row[6] or {},
                created_at=row[7],
                updated_at=row[8],
            )
            for row in rows
        ]

    def remove_collaborator(self, project_id: str, user_id: str, removed_by: str) -> bool:
        """Remove a collaborator from a project.

        Args:
            project_id: Project ID.
            user_id: User ID of the collaborator to remove.
            removed_by: User ID performing the removal (must be owner or the collaborator).

        Returns:
            True if removed, False if not found.

        Raises:
            ValueError: If removed_by is not the owner or the collaborator.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Verify remover has permission
            cursor.execute(
                "SELECT owner_id FROM projects WHERE project_id = %s",
                (project_id,),
            )
            row = cursor.fetchone()
            if row and row[0] != removed_by and user_id != removed_by:
                raise ValueError("Only the project owner or collaborator can remove collaboration")

            cursor.execute(
                "DELETE FROM project_collaborators WHERE project_id = %s AND user_id = %s",
                (project_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_collaborator_role(
        self,
        project_id: str,
        user_id: str,
        new_role: ProjectRole,
        updated_by: str,
    ) -> bool:
        """Update a collaborator's role.

        Args:
            project_id: Project ID.
            user_id: User ID of the collaborator.
            new_role: New role to assign.
            updated_by: User ID performing the update (must be project owner).

        Returns:
            True if updated, False if collaborator not found.

        Raises:
            ValueError: If updated_by is not the project owner.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Verify updater is project owner
            cursor.execute(
                "SELECT owner_id FROM projects WHERE project_id = %s",
                (project_id,),
            )
            row = cursor.fetchone()
            if not row or row[0] != updated_by:
                raise ValueError("Only the project owner can update collaborator roles")

            cursor.execute(
                """
                UPDATE project_collaborators
                SET role = %s, updated_at = %s
                WHERE project_id = %s AND user_id = %s
                """,
                (new_role.value, datetime.utcnow(), project_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    # =========================================================================
    # Billing: User-Level Subscriptions & Org Subscription Precedence
    # =========================================================================

    def create_user_subscription(
        self,
        user_id: str,
        plan: OrgPlan = OrgPlan.FREE,
    ) -> Subscription:
        """Create a user-level subscription for personal projects.

        Args:
            user_id: User ID.
            plan: Subscription plan.

        Returns:
            The created subscription.

        Raises:
            ValueError: If user already has a subscription.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Check if user already has subscription
            cursor.execute(
                "SELECT subscription_id FROM subscriptions WHERE user_id = %s",
                (user_id,),
            )
            if cursor.fetchone():
                raise ValueError("User already has a subscription")

            subscription = Subscription(
                user_id=user_id,
                plan=plan,
                status=SubscriptionStatus.ACTIVE,
            )

            cursor.execute(
                """
                INSERT INTO subscriptions (subscription_id, user_id, plan, status)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    subscription.id,
                    subscription.user_id,
                    subscription.plan.value,
                    subscription.status.value,
                ),
            )
            conn.commit()

        logger.info(f"Created user subscription {subscription.id} for user {user_id}")
        return subscription

    def get_user_subscription(self, user_id: str) -> Optional[Subscription]:
        """Get a user's personal subscription.

        Args:
            user_id: User ID.

        Returns:
            The subscription if found, None otherwise.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT subscription_id, user_id, stripe_subscription_id, stripe_customer_id,
                       plan, status, current_period_start, current_period_end, cancel_at,
                       created_at, updated_at
                FROM subscriptions
                WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cursor.fetchone()

        if not row:
            return None

        return Subscription(
            id=row[0],
            user_id=row[1],
            stripe_subscription_id=row[2],
            stripe_customer_id=row[3],
            plan=OrgPlan(row[4]),
            status=SubscriptionStatus(row[5]),
            current_period_start=row[6],
            current_period_end=row[7],
            cancel_at=row[8],
            created_at=row[9],
            updated_at=row[10],
        )

    def resolve_billing_context(
        self,
        user_id: str,
        org_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[BillingContext]:
        """Resolve which subscription to bill for a user's work.

        Billing priority:
        1. If org_id is provided and user is a member → use org subscription
        2. If project_id is provided and project is org-owned → use org subscription
        3. Otherwise → use user's personal subscription

        Args:
            user_id: User ID.
            org_id: Optional org context (takes precedence if user is member).
            project_id: Optional project context (used to determine ownership).

        Returns:
            BillingContext with resolved subscription info, or None if no subscription.
        """
        with self.pool.connection() as conn:
            cursor = conn.cursor()

            # Priority 1: Explicit org context
            if org_id:
                # Verify user is org member
                cursor.execute(
                    "SELECT role FROM org_memberships WHERE org_id = %s AND user_id = %s AND is_active = TRUE",
                    (org_id, user_id),
                )
                if cursor.fetchone():
                    # User is org member, use org subscription
                    return self._get_org_billing_context(cursor, org_id, user_id)

            # Priority 2: Check project ownership
            if project_id:
                cursor.execute(
                    "SELECT org_id, owner_id FROM projects WHERE project_id = %s",
                    (project_id,),
                )
                row = cursor.fetchone()
                if row:
                    proj_org_id, proj_owner_id = row
                    if proj_org_id:
                        # Org-owned project, use org subscription
                        return self._get_org_billing_context(cursor, proj_org_id, user_id)

            # Priority 3: User's personal subscription
            return self._get_user_billing_context(cursor, user_id)

    def _get_org_billing_context(self, cursor, org_id: str, user_id: str) -> Optional[BillingContext]:
        """Helper to get org billing context."""
        cursor.execute(
            """
            SELECT s.subscription_id, s.plan, s.status, o.monthly_token_budget,
                   COALESCE(s.tokens_used_this_period, 0) as tokens_used
            FROM subscriptions s
            JOIN organizations o ON o.id = s.org_id
            WHERE s.org_id = %s
            """,
            (org_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return BillingContext(
            subscription_id=row[0],
            subscription_type="org",
            org_id=org_id,
            user_id=user_id,
            plan=OrgPlan(row[1]),
            status=SubscriptionStatus(row[2]),
            token_budget=row[3],
            tokens_used=row[4],
            is_within_budget=row[4] < row[3],
        )

    def _get_user_billing_context(self, cursor, user_id: str) -> Optional[BillingContext]:
        """Helper to get user billing context."""
        cursor.execute(
            """
            SELECT subscription_id, plan, status
            FROM subscriptions
            WHERE user_id = %s
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        # Plan token budgets for user subscriptions
        plan_budgets = {
            OrgPlan.FREE: 10000,
            OrgPlan.STARTER: 100000,
            OrgPlan.PROFESSIONAL: 500000,
            OrgPlan.ENTERPRISE: 2000000,
        }

        plan = OrgPlan(row[1])
        budget = plan_budgets.get(plan, 10000)

        # Get usage for this user
        cursor.execute(
            """
            SELECT COALESCE(SUM(quantity), 0)
            FROM usage_records
            WHERE user_id = %s AND org_id IS NULL
              AND recorded_at >= date_trunc('month', CURRENT_TIMESTAMP)
            """,
            (user_id,),
        )
        tokens_used = cursor.fetchone()[0]

        return BillingContext(
            subscription_id=row[0],
            subscription_type="user",
            user_id=user_id,
            plan=plan,
            status=SubscriptionStatus(row[2]),
            token_budget=budget,
            tokens_used=tokens_used,
            is_within_budget=tokens_used < budget,
        )

    def record_user_usage(
        self,
        user_id: str,
        metric_name: str,
        quantity: int,
        org_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> UsageRecord:
        """Record usage for a user (personal or within org context).

        If org_id is provided, usage goes to org billing.
        Otherwise, usage goes to user's personal billing.

        Args:
            user_id: User ID.
            metric_name: Name of the metric.
            quantity: Quantity used.
            org_id: Optional org ID for org-level billing.
            metadata: Optional metadata.

        Returns:
            The created usage record.
        """
        record = UsageRecord(
            org_id=org_id,
            user_id=user_id,
            metric_name=metric_name,
            quantity=quantity,
            metadata=metadata or {},
        )

        with self.pool.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO usage_records (record_id, org_id, user_id, metric_name, quantity, recorded_at, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    record.id,
                    record.org_id,
                    record.user_id,
                    record.metric_name,
                    record.quantity,
                    record.recorded_at,
                    _jsonb(record.metadata),
                ),
            )
            conn.commit()

        return record

    def get_user_usage_summary(
        self,
        user_id: str,
        metric_name: str,
        start_date: datetime,
        end_date: Optional[datetime] = None,
        include_org_usage: bool = False,
    ) -> int:
        """Get total usage for a user.

        Args:
            user_id: User ID.
            metric_name: Name of the metric.
            start_date: Start of the period.
            end_date: End of the period (defaults to now).
            include_org_usage: If True, include usage within org contexts.

        Returns:
            Total quantity used.
        """
        end_date = end_date or datetime.utcnow()

        with self.pool.connection() as conn:
            cursor = conn.cursor()

            if include_org_usage:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(quantity), 0)
                    FROM usage_records
                    WHERE user_id = %s AND metric_name = %s
                      AND recorded_at >= %s AND recorded_at <= %s
                    """,
                    (user_id, metric_name, start_date, end_date),
                )
            else:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(quantity), 0)
                    FROM usage_records
                    WHERE user_id = %s AND org_id IS NULL AND metric_name = %s
                      AND recorded_at >= %s AND recorded_at <= %s
                    """,
                    (user_id, metric_name, start_date, end_date),
                )
            total = cursor.fetchone()[0]

        return total
