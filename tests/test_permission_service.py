"""Unit tests for PermissionService RBAC operations.

Tests permission checking, role-based access, and permission enforcement
for organizations and projects.

Following behavior_design_test_strategy (Student):
- Unit tests with mocks for database layer
- Tests for happy path and error cases
- Test pyramid: comprehensive unit coverage for RBAC
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock
from typing import List, Dict, Any, Optional

# Import contracts for type checking
from guideai.multi_tenant.contracts import (
    MemberRole,
    ProjectRole,
)
from guideai.multi_tenant.permissions import (
    OrgPermission,
    ProjectPermission,
    PermissionService,
    PermissionDenied,
    NotAMember,
    UserOrgContext,
    UserProjectContext,
    ORG_ROLE_PERMISSIONS,
    PROJECT_ROLE_PERMISSIONS,
    require_org_permission_decorator,
    require_project_permission_decorator,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_pool():
    """Create mock PostgreSQL connection pool with async context manager."""
    pool = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()

    # Setup cursor() to return the mock cursor
    connection.cursor.return_value.__enter__ = MagicMock(return_value=cursor)
    connection.cursor.return_value.__exit__ = MagicMock(return_value=False)

    # Setup pool.connection() context manager
    connection_ctx = MagicMock()
    connection_ctx.__enter__ = MagicMock(return_value=connection)
    connection_ctx.__exit__ = MagicMock(return_value=False)
    pool.connection.return_value = connection_ctx

    return pool, connection, cursor


@pytest.fixture
def permission_service(mock_pool):
    """Create PermissionService with mocked pool."""
    pool, connection, cursor = mock_pool

    service = PermissionService(pool=pool)

    return service, cursor


# =============================================================================
# Permission Matrix Tests
# =============================================================================

@pytest.mark.unit
class TestPermissionMatrix:
    """Test the permission matrices are correctly configured."""

    def test_owner_has_all_org_permissions(self):
        """Owner role should have all organization permissions."""
        owner_perms = ORG_ROLE_PERMISSIONS[MemberRole.OWNER]
        all_perms = set(OrgPermission)

        # Owner should have every permission
        assert owner_perms == all_perms

    def test_admin_has_most_org_permissions(self):
        """Admin role should have most permissions except destructive ones."""
        admin_perms = ORG_ROLE_PERMISSIONS[MemberRole.ADMIN]

        # Admin should NOT have
        assert OrgPermission.DELETE_ORG not in admin_perms
        assert OrgPermission.TRANSFER_OWNERSHIP not in admin_perms

        # Admin SHOULD have
        assert OrgPermission.VIEW_ORG in admin_perms
        assert OrgPermission.UPDATE_ORG in admin_perms
        assert OrgPermission.INVITE_MEMBERS in admin_perms
        assert OrgPermission.MANAGE_BILLING in admin_perms
        assert OrgPermission.VIEW_AUDIT_LOGS in admin_perms

    def test_member_has_basic_org_permissions(self):
        """Member role should have basic operational permissions."""
        member_perms = ORG_ROLE_PERMISSIONS[MemberRole.MEMBER]

        # Member should have
        assert OrgPermission.VIEW_ORG in member_perms
        assert OrgPermission.CREATE_PROJECT in member_perms
        assert OrgPermission.CREATE_AGENT in member_perms

        # Member should NOT have
        assert OrgPermission.UPDATE_ORG not in member_perms
        assert OrgPermission.MANAGE_BILLING not in member_perms
        assert OrgPermission.INVITE_MEMBERS not in member_perms
        assert OrgPermission.MANAGE_ROLES not in member_perms

    def test_viewer_has_read_only_org_permissions(self):
        """Viewer role should only have view permissions."""
        viewer_perms = ORG_ROLE_PERMISSIONS[MemberRole.VIEWER]

        # Viewer should only have view/read permissions
        assert OrgPermission.VIEW_ORG in viewer_perms
        assert OrgPermission.VIEW_MEMBERS in viewer_perms
        assert OrgPermission.VIEW_PROJECTS in viewer_perms
        assert OrgPermission.VIEW_AGENTS in viewer_perms

        # Viewer should NOT have any write permissions
        assert OrgPermission.UPDATE_ORG not in viewer_perms
        assert OrgPermission.CREATE_PROJECT not in viewer_perms
        assert OrgPermission.INVITE_MEMBERS not in viewer_perms
        assert OrgPermission.MANAGE_BILLING not in viewer_perms

    def test_project_owner_has_all_project_permissions(self):
        """Project owner should have all project permissions."""
        owner_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.OWNER]
        all_perms = set(ProjectPermission)

        assert owner_perms == all_perms

    def test_project_maintainer_permissions(self):
        """Maintainer should have most permissions except destructive ones."""
        maintainer_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.MAINTAINER]

        # Maintainer should NOT have
        assert ProjectPermission.DELETE_PROJECT not in maintainer_perms
        assert ProjectPermission.TRANSFER_PROJECT not in maintainer_perms
        assert ProjectPermission.ARCHIVE_PROJECT not in maintainer_perms

        # Maintainer SHOULD have
        assert ProjectPermission.VIEW_PROJECT in maintainer_perms
        assert ProjectPermission.UPDATE_PROJECT in maintainer_perms
        assert ProjectPermission.MANAGE_COLLABORATORS in maintainer_perms
        assert ProjectPermission.CREATE_RUNS in maintainer_perms

    def test_project_contributor_permissions(self):
        """Contributor should have operational permissions."""
        contributor_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.CONTRIBUTOR]

        # Contributor should have
        assert ProjectPermission.VIEW_PROJECT in contributor_perms
        assert ProjectPermission.CREATE_RUNS in contributor_perms
        assert ProjectPermission.CREATE_BEHAVIORS in contributor_perms

        # Contributor should NOT have
        assert ProjectPermission.UPDATE_PROJECT not in contributor_perms
        assert ProjectPermission.MANAGE_COLLABORATORS not in contributor_perms
        assert ProjectPermission.DELETE_PROJECT not in contributor_perms

    def test_project_viewer_read_only_permissions(self):
        """Project viewer should only have read permissions."""
        viewer_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.VIEWER]

        # Viewer should only have view permissions
        assert ProjectPermission.VIEW_PROJECT in viewer_perms
        assert ProjectPermission.VIEW_RUNS in viewer_perms
        assert ProjectPermission.VIEW_BEHAVIORS in viewer_perms

        # Viewer should NOT have any write permissions
        assert ProjectPermission.CREATE_RUNS not in viewer_perms
        assert ProjectPermission.UPDATE_PROJECT not in viewer_perms
        assert ProjectPermission.CREATE_BEHAVIORS not in viewer_perms


# =============================================================================
# PermissionService - Organization Permission Tests
# =============================================================================

class TestOrgPermissionChecking:
    """Test organization-level permission checking."""

    def test_get_user_org_role_returns_role(self, permission_service):
        """get_user_org_role returns correct role when user is member."""
        service, cursor = permission_service

        # Mock database return - user is ADMIN
        cursor.fetchone.return_value = ("admin",)

        role = service.get_user_org_role("user-123", "org-456")

        assert role == MemberRole.ADMIN
        cursor.execute.assert_called_once()

    def test_get_user_org_role_returns_none_for_non_member(self, permission_service):
        """get_user_org_role returns None when user is not a member."""
        service, cursor = permission_service

        # Mock database return - no membership found
        cursor.fetchone.return_value = None

        role = service.get_user_org_role("user-123", "org-456")

        assert role is None

    def test_has_org_permission_returns_true_for_admin(self, permission_service):
        """has_org_permission returns True when admin has permission."""
        service, cursor = permission_service

        # User is an admin
        cursor.fetchone.return_value = ("admin",)

        result = service.has_org_permission(
            "user-123",
            "org-456",
            OrgPermission.INVITE_MEMBERS
        )

        assert result is True

    def test_has_org_permission_returns_false_for_viewer(self, permission_service):
        """has_org_permission returns False when viewer lacks permission."""
        service, cursor = permission_service

        # User is a viewer
        cursor.fetchone.return_value = ("viewer",)

        result = service.has_org_permission(
            "user-123",
            "org-456",
            OrgPermission.INVITE_MEMBERS
        )

        assert result is False

    def test_has_org_permission_returns_false_for_non_member(self, permission_service):
        """has_org_permission returns False when user is not a member."""
        service, cursor = permission_service

        # No membership
        cursor.fetchone.return_value = None

        result = service.has_org_permission(
            "user-123",
            "org-456",
            OrgPermission.VIEW_ORG
        )

        assert result is False

    def test_require_org_permission_succeeds_for_valid_permission(self, permission_service):
        """require_org_permission does not raise when permission exists."""
        service, cursor = permission_service

        # User is owner
        cursor.fetchone.return_value = ("owner",)

        # Should not raise
        service.require_org_permission(
            "user-123",
            "org-456",
            OrgPermission.DELETE_ORG
        )

    def test_require_org_permission_raises_for_non_member(self, permission_service):
        """require_org_permission raises NotAMember when not a member."""
        service, cursor = permission_service

        # No membership
        cursor.fetchone.return_value = None

        with pytest.raises(NotAMember) as exc_info:
            service.require_org_permission(
                "user-123",
                "org-456",
                OrgPermission.VIEW_ORG
            )

        assert exc_info.value.user_id == "user-123"
        assert exc_info.value.resource_id == "org-456"

    def test_require_org_permission_raises_for_insufficient_permission(self, permission_service):
        """require_org_permission raises PermissionDenied when lacking permission."""
        service, cursor = permission_service

        # User is member (not admin)
        cursor.fetchone.return_value = ("member",)

        with pytest.raises(PermissionDenied) as exc_info:
            service.require_org_permission(
                "user-123",
                "org-456",
                OrgPermission.MANAGE_BILLING
            )

        assert exc_info.value.user_id == "user-123"
        assert exc_info.value.resource_id == "org-456"
        assert exc_info.value.permission == OrgPermission.MANAGE_BILLING

    def test_get_user_org_context_returns_full_context(self, permission_service):
        """get_user_org_context returns complete context with permissions."""
        service, cursor = permission_service

        # User is admin
        cursor.fetchone.return_value = ("admin",)

        context = service.get_user_org_context("user-123", "org-456")

        assert context is not None
        assert context.user_id == "user-123"
        assert context.org_id == "org-456"
        assert context.role == MemberRole.ADMIN
        assert OrgPermission.INVITE_MEMBERS in context.permissions
        assert OrgPermission.DELETE_ORG not in context.permissions

    def test_get_user_org_context_returns_none_for_non_member(self, permission_service):
        """get_user_org_context returns None when not a member."""
        service, cursor = permission_service

        cursor.fetchone.return_value = None

        context = service.get_user_org_context("user-123", "org-456")

        assert context is None


# =============================================================================
# PermissionService - Project Permission Tests
# =============================================================================

class TestProjectPermissionChecking:
    """Test project-level permission checking."""

    def test_get_user_project_role_from_collaborator(self, permission_service):
        """get_user_project_role returns role from project_collaborators."""
        service, cursor = permission_service

        # First call returns project collaborator role
        cursor.fetchone.return_value = ("maintainer",)

        role = service.get_user_project_role("user-123", "org-456", "proj-789")

        assert role == ProjectRole.MAINTAINER

    def test_get_user_project_role_inherits_from_org_owner(self, permission_service):
        """get_user_project_role inherits from org owner role."""
        service, cursor = permission_service

        # First call: no project collaborator
        # Second call: org membership (owner)
        cursor.fetchone.side_effect = [None, ("owner",)]

        role = service.get_user_project_role("user-123", "org-456", "proj-789")

        assert role == ProjectRole.OWNER

    def test_get_user_project_role_inherits_from_org_admin(self, permission_service):
        """get_user_project_role inherits from org admin role."""
        service, cursor = permission_service

        # First call: no project collaborator
        # Second call: org membership (admin)
        cursor.fetchone.side_effect = [None, ("admin",)]

        role = service.get_user_project_role("user-123", "org-456", "proj-789")

        assert role == ProjectRole.MAINTAINER

    def test_get_user_project_role_inherits_from_org_member(self, permission_service):
        """get_user_project_role inherits from org member role."""
        service, cursor = permission_service

        # First call: no project collaborator
        # Second call: org membership (member)
        cursor.fetchone.side_effect = [None, ("member",)]

        role = service.get_user_project_role("user-123", "org-456", "proj-789")

        assert role == ProjectRole.CONTRIBUTOR

    def test_get_user_project_role_inherits_from_org_viewer(self, permission_service):
        """get_user_project_role inherits from org viewer role."""
        service, cursor = permission_service

        # First call: no project collaborator
        # Second call: org membership (viewer)
        cursor.fetchone.side_effect = [None, ("viewer",)]

        role = service.get_user_project_role("user-123", "org-456", "proj-789")

        assert role == ProjectRole.VIEWER

    def test_has_project_permission_returns_true_for_maintainer(self, permission_service):
        """has_project_permission returns True when maintainer has permission."""
        service, cursor = permission_service

        # User is maintainer
        cursor.fetchone.return_value = ("maintainer",)

        result = service.has_project_permission(
            "user-123",
            "org-456",
            "proj-789",
            ProjectPermission.MANAGE_COLLABORATORS
        )

        assert result is True

    def test_has_project_permission_returns_false_for_viewer(self, permission_service):
        """has_project_permission returns False when viewer lacks permission."""
        service, cursor = permission_service

        # User is viewer
        cursor.fetchone.return_value = ("viewer",)

        result = service.has_project_permission(
            "user-123",
            "org-456",
            "proj-789",
            ProjectPermission.CREATE_RUNS
        )

        assert result is False

    def test_require_project_permission_succeeds(self, permission_service):
        """require_project_permission does not raise for valid permission."""
        service, cursor = permission_service

        # User is owner
        cursor.fetchone.return_value = ("owner",)

        # Should not raise
        service.require_project_permission(
            "user-123",
            "org-456",
            "proj-789",
            ProjectPermission.DELETE_PROJECT
        )

    def test_require_project_permission_raises_for_insufficient(self, permission_service):
        """require_project_permission raises when lacking permission."""
        service, cursor = permission_service

        # User is contributor
        cursor.fetchone.return_value = ("contributor",)

        with pytest.raises(PermissionDenied) as exc_info:
            service.require_project_permission(
                "user-123",
                "org-456",
                "proj-789",
                ProjectPermission.DELETE_PROJECT
            )

        assert exc_info.value.permission == ProjectPermission.DELETE_PROJECT

    def test_get_user_project_context_returns_full_context(self, permission_service):
        """get_user_project_context returns complete context."""
        service, cursor = permission_service

        # User is contributor
        cursor.fetchone.return_value = ("contributor",)

        context = service.get_user_project_context(
            "user-123",
            "org-456",
            "proj-789"
        )

        assert context is not None
        assert context.user_id == "user-123"
        assert context.org_id == "org-456"
        assert context.project_id == "proj-789"
        assert context.role == ProjectRole.CONTRIBUTOR
        assert ProjectPermission.CREATE_RUNS in context.permissions
        assert ProjectPermission.DELETE_PROJECT not in context.permissions


# =============================================================================
# Permission Filtering Tests
# =============================================================================

@pytest.mark.unit
class TestPermissionFiltering:
    """Test permission-based filtering methods."""

    def test_filter_accessible_organizations(self, permission_service):
        """filter_accessible_organizations returns orgs user can access."""
        service, cursor = permission_service

        # Mock: user is member of org-1 and org-3, but not org-2
        cursor.fetchall.return_value = [("org-1",), ("org-3",)]

        org_ids = ["org-1", "org-2", "org-3"]
        accessible = service.filter_accessible_organizations("user-123", org_ids)

        assert len(accessible) == 2
        assert "org-1" in accessible
        assert "org-3" in accessible
        assert "org-2" not in accessible

    def test_filter_accessible_projects(self, permission_service):
        """filter_accessible_projects returns projects user can access."""
        service, cursor = permission_service

        # Mock: user can access proj-a and proj-c
        cursor.fetchall.return_value = [("proj-a",), ("proj-c",)]

        project_ids = ["proj-a", "proj-b", "proj-c"]
        accessible = service.filter_accessible_projects(
            "user-123",
            "org-456",
            project_ids
        )

        assert len(accessible) == 2
        assert "proj-a" in accessible
        assert "proj-c" in accessible
        assert "proj-b" not in accessible

    def test_get_all_user_permissions_for_org(self, permission_service):
        """get_all_user_permissions_for_org returns permission set."""
        service, cursor = permission_service

        # User is admin
        cursor.fetchone.return_value = ("admin",)

        permissions = service.get_all_user_permissions_for_org("user-123", "org-456")

        assert permissions is not None
        assert OrgPermission.VIEW_ORG in permissions
        assert OrgPermission.INVITE_MEMBERS in permissions
        assert OrgPermission.DELETE_ORG not in permissions  # Admin can't delete

    def test_get_all_user_permissions_for_project(self, permission_service):
        """get_all_user_permissions_for_project returns permission set."""
        service, cursor = permission_service

        # User is contributor
        cursor.fetchone.return_value = ("contributor",)

        permissions = service.get_all_user_permissions_for_project(
            "user-123",
            "org-456",
            "proj-789"
        )

        assert permissions is not None
        assert ProjectPermission.VIEW_PROJECT in permissions
        assert ProjectPermission.CREATE_RUNS in permissions
        assert ProjectPermission.DELETE_PROJECT not in permissions


# =============================================================================
# Exception Tests
# =============================================================================

@pytest.mark.unit
class TestPermissionExceptions:
    """Test permission exception classes."""

    def test_permission_denied_message(self):
        """PermissionDenied has descriptive message."""
        exc = PermissionDenied(
            user_id="user-123",
            resource_id="org-456",
            resource_type="organization",
            permission=OrgPermission.DELETE_ORG
        )

        assert "user-123" in str(exc)
        assert "org-456" in str(exc)
        assert "DELETE_ORG" in str(exc)
        assert exc.user_id == "user-123"
        assert exc.resource_id == "org-456"

    def test_not_a_member_message(self):
        """NotAMember has descriptive message."""
        exc = NotAMember(
            user_id="user-123",
            resource_id="org-456",
            resource_type="organization"
        )

        assert "user-123" in str(exc)
        assert "org-456" in str(exc)
        assert "not a member" in str(exc).lower()


# =============================================================================
# Decorator Tests
# =============================================================================

@pytest.mark.unit
class TestPermissionDecorators:
    """Test FastAPI permission decorators."""

    def test_require_org_permission_decorator_passes(self, mock_pool):
        """Decorator allows request when permission exists."""
        pool, connection, cursor = mock_pool
        cursor.fetchone.return_value = ("owner",)

        @require_org_permission_decorator(OrgPermission.DELETE_ORG)
        def protected_endpoint(request):
            return {"status": "ok"}

        # Mock request with state containing user_id and org_id
        mock_request = MagicMock()
        mock_request.state.user_id = "user-123"
        mock_request.state.org_id = "org-456"
        mock_request.state.db_pool = pool

        # Should not raise
        result = protected_endpoint(mock_request)
        assert result["status"] == "ok"

    def test_require_project_permission_decorator_passes(self, mock_pool):
        """Project decorator allows request when permission exists."""
        pool, connection, cursor = mock_pool
        cursor.fetchone.return_value = ("owner",)

        @require_project_permission_decorator(ProjectPermission.DELETE_PROJECT)
        def protected_endpoint(request):
            return {"status": "ok"}

        # Mock request with state containing user_id, org_id, and project_id
        mock_request = MagicMock()
        mock_request.state.user_id = "user-123"
        mock_request.state.org_id = "org-456"
        mock_request.state.project_id = "proj-789"
        mock_request.state.db_pool = pool

        # Should not raise
        result = protected_endpoint(mock_request)
        assert result["status"] == "ok"


# =============================================================================
# User Context Dataclass Tests
# =============================================================================

@pytest.mark.unit
class TestUserContextDataclasses:
    """Test UserOrgContext and UserProjectContext dataclasses."""

    def test_user_org_context_has_permission(self):
        """UserOrgContext.has_permission checks correctly."""
        context = UserOrgContext(
            user_id="user-123",
            org_id="org-456",
            role=MemberRole.ADMIN,
            permissions=ORG_ROLE_PERMISSIONS[MemberRole.ADMIN]
        )

        assert context.has_permission(OrgPermission.INVITE_MEMBERS) is True
        assert context.has_permission(OrgPermission.DELETE_ORG) is False

    def test_user_project_context_has_permission(self):
        """UserProjectContext.has_permission checks correctly."""
        context = UserProjectContext(
            user_id="user-123",
            org_id="org-456",
            project_id="proj-789",
            role=ProjectRole.CONTRIBUTOR,
            permissions=PROJECT_ROLE_PERMISSIONS[ProjectRole.CONTRIBUTOR]
        )

        assert context.has_permission(ProjectPermission.CREATE_RUNS) is True
        assert context.has_permission(ProjectPermission.DELETE_PROJECT) is False
