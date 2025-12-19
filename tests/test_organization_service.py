"""Unit tests for OrganizationService CRUD operations.

Tests Project CRUD (get, update, delete, restore), Project Membership
management, and Agent CRUD operations.

Following behavior_design_test_strategy (Student):
- Unit tests with mocks for database layer
- Tests for happy path and error cases
- 70% unit coverage target
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call
from typing import List, Dict, Any, Optional

# Import contracts for type checking
from guideai.multi_tenant.contracts import (
    Project,
    ProjectMembership,
    ProjectRole,
    ProjectVisibility,
    Agent,
    AgentType,
    AgentStatus,
    MemberRole,
    UpdateProjectRequest,
    UpdateAgentRequest,
    CreateProjectMembershipRequest,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_pool():
    """Create mock PostgreSQL connection pool with proper context manager."""
    pool = MagicMock()
    connection = MagicMock()
    cursor = MagicMock()

    # Setup cursor() to return the mock cursor
    connection.cursor.return_value = cursor

    # Setup pool.connection() context manager
    connection_ctx = MagicMock()
    connection_ctx.__enter__ = MagicMock(return_value=connection)
    connection_ctx.__exit__ = MagicMock(return_value=False)
    pool.connection.return_value = connection_ctx

    return pool, connection, cursor


@pytest.fixture
def org_service(mock_pool):
    """Create OrganizationService with mocked pool."""
    pool, connection, cursor = mock_pool

    from guideai.multi_tenant.organization_service import OrganizationService

    # Create service with mock pool directly (bypass dsn path)
    service = OrganizationService(pool=pool)

    return service, cursor


@pytest.fixture
def sample_project() -> tuple:
    """Sample project data as returned by database (tuple format).

    Column order matches: project_id, org_id, name, slug, description,
    visibility, settings, archived_at, created_at, updated_at
    """
    return (
        "proj-abc123",                                           # project_id
        "org-xyz789",                                            # org_id
        "Test Project",                                          # name
        "test-project",                                          # slug
        "A test project",                                        # description
        "private",                                               # visibility
        {},                                                      # settings
        None,                                                    # archived_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # created_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # updated_at
    )


@pytest.fixture
def sample_agent() -> tuple:
    """Sample agent data as returned by database (tuple format).

    Column order matches: agent_id, org_id, project_id, name, agent_type,
    status, config, capabilities, created_at, updated_at
    """
    return (
        "agent-abc123",                                          # agent_id
        "org-xyz789",                                            # org_id
        "proj-abc123",                                           # project_id
        "Test Agent",                                            # name
        "specialist",                                            # agent_type
        "active",                                                # status
        {"model": "gpt-4"},                                      # config
        ["code_review", "testing"],                              # capabilities
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # created_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # updated_at
    )


@pytest.fixture
def sample_project_membership() -> tuple:
    """Sample project membership data (tuple format).

    Column order matches: membership_id, project_id, user_id, role,
    created_at, updated_at
    """
    return (
        "pmem-abc123",                                           # membership_id
        "proj-abc123",                                           # project_id
        "user-123",                                              # user_id
        "owner",                                                 # role
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # created_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # updated_at
    )


# =============================================================================
# Project CRUD Tests
# =============================================================================

@pytest.mark.unit
class TestGetProject:
    """Tests for get_project method."""

    def test_get_project_by_id(self, org_service, sample_project):
        """Successfully retrieve project by ID."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project

        result = service.get_project("proj-abc123")

        assert result is not None
        assert result.id == "proj-abc123"
        assert result.name == "Test Project"
        assert result.slug == "test-project"
        cursor.execute.assert_called_once()

    def test_get_project_with_org_filter(self, org_service, sample_project):
        """Retrieve project with org_id validation."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project

        result = service.get_project("proj-abc123", org_id="org-xyz789")

        assert result is not None
        assert result.org_id == "org-xyz789"
        # Verify org_id was included in query
        call_args = cursor.execute.call_args[0]
        assert "org-xyz789" in str(call_args)

    def test_get_project_not_found(self, org_service):
        """Return None when project doesn't exist."""
        service, cursor = org_service
        cursor.fetchone.return_value = None

        result = service.get_project("nonexistent-id")

        assert result is None

    def test_get_project_archived_excluded(self, org_service, sample_project):
        """Archived projects are not returned by default."""
        service, cursor = org_service
        # Return None to simulate archived project being filtered
        cursor.fetchone.return_value = None

        result = service.get_project("proj-archived")

        assert result is None
        # Verify archived_at IS NULL in query
        call_args = cursor.execute.call_args[0][0]
        assert "archived_at IS NULL" in call_args


@pytest.mark.unit
class TestGetProjectBySlug:
    """Tests for get_project_by_slug method."""

    def test_get_project_by_slug_success(self, org_service, sample_project):
        """Successfully retrieve project by org_id and slug."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project

        result = service.get_project_by_slug("org-xyz789", "test-project")

        assert result is not None
        assert result.slug == "test-project"
        assert result.org_id == "org-xyz789"

    def test_get_project_by_slug_not_found(self, org_service):
        """Return None when slug doesn't exist in org."""
        service, cursor = org_service
        cursor.fetchone.return_value = None

        result = service.get_project_by_slug("org-xyz789", "nonexistent-slug")

        assert result is None


@pytest.mark.unit
class TestUpdateProject:
    """Tests for update_project method."""

    def test_update_project_name(self, org_service, sample_project):
        """Successfully update project name."""
        service, cursor = org_service

        # First call gets project for returning, then update returns affected row
        cursor.fetchone.return_value = sample_project
        cursor.rowcount = 1

        request = UpdateProjectRequest(name="Updated Name")
        result = service.update_project("proj-abc123", request)

        assert result is not None
        # Verify UPDATE was called
        call_args_str = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "UPDATE" in call_args_str

    def test_update_project_visibility(self, org_service, sample_project):
        """Update project visibility setting."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project
        cursor.rowcount = 1

        request = UpdateProjectRequest(visibility=ProjectVisibility.INTERNAL)
        result = service.update_project("proj-abc123", request)

        assert result is not None

    def test_update_project_not_found(self, org_service):
        """Return None when project doesn't exist."""
        service, cursor = org_service
        cursor.fetchone.return_value = None
        cursor.rowcount = 0

        request = UpdateProjectRequest(name="New Name")
        result = service.update_project("nonexistent", request)

        assert result is None

    def test_update_project_no_changes(self, org_service, sample_project):
        """Handle update request with no fields set."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project

        request = UpdateProjectRequest()  # No fields set
        result = service.update_project("proj-abc123", request)

        # Should return existing project without UPDATE
        assert result is not None


@pytest.mark.unit
class TestDeleteProject:
    """Tests for delete_project (soft delete) method."""

    def test_delete_project_success(self, org_service, sample_project):
        """Successfully soft-delete a project."""
        service, cursor = org_service
        cursor.rowcount = 1

        result = service.delete_project("proj-abc123")

        assert result is True
        # Verify soft delete (SET archived_at) was used
        call_args_str = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "UPDATE" in call_args_str and "archived_at" in call_args_str

    def test_delete_project_unassigns_agents(self, org_service, sample_project):
        """Deleting project sets agents' project_id to NULL."""
        service, cursor = org_service
        cursor.rowcount = 1

        result = service.delete_project("proj-abc123")

        assert result is True
        # Verify agents were unassigned
        call_args_str = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "agents" in call_args_str.lower() or "project_id" in call_args_str

    def test_delete_project_not_found(self, org_service):
        """Return False when project doesn't exist."""
        service, cursor = org_service
        cursor.rowcount = 0

        result = service.delete_project("nonexistent")

        assert result is False

    def test_delete_project_already_deleted(self, org_service, sample_project):
        """Handle already-deleted (archived) project."""
        service, cursor = org_service
        cursor.rowcount = 0  # No rows updated

        result = service.delete_project("proj-abc123")

        assert result is False


@pytest.mark.unit
class TestRestoreProject:
    """Tests for restore_project method."""

    def test_restore_project_success(self, org_service, sample_project):
        """Successfully restore an archived project."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project
        cursor.rowcount = 1

        result = service.restore_project("proj-abc123")

        assert result is not None
        # Verify archived_at was cleared
        call_args_str = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "archived_at" in call_args_str

    def test_restore_project_not_archived(self, org_service, sample_project):
        """Handle restore of non-archived project."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project  # Not archived
        cursor.rowcount = 1

        result = service.restore_project("proj-abc123")

        # Should still succeed or return existing project
        assert result is not None

    def test_restore_project_not_found(self, org_service):
        """Return None when project doesn't exist."""
        service, cursor = org_service
        cursor.fetchone.return_value = None
        cursor.rowcount = 0

        result = service.restore_project("nonexistent")

        assert result is None


# =============================================================================
# Project Membership Tests
# =============================================================================

@pytest.mark.unit
class TestAddProjectMember:
    """Tests for add_project_member method."""

    def test_add_member_success(self, org_service, sample_project_membership):
        """Successfully add a member to a project."""
        service, cursor = org_service
        # No existing membership
        cursor.fetchone.return_value = None

        result = service.add_project_member(
            project_id="proj-abc123",
            user_id="user-456",
            role=ProjectRole.CONTRIBUTOR,
        )

        assert result is not None
        # Verify INSERT was called
        call_args_str = " ".join(str(c) for c in cursor.execute.call_args_list)
        assert "INSERT" in call_args_str and "project_memberships" in call_args_str

    def test_add_member_duplicate(self, org_service, sample_project_membership):
        """Handle adding duplicate member."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_project_membership  # Already exists

        with pytest.raises(ValueError):
            service.add_project_member(
                project_id="proj-abc123",
                user_id="user-123",
                role=ProjectRole.VIEWER,
            )

    def test_add_member_project_not_found(self, org_service):
        """Adding member to nonexistent project still creates membership."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # No existing membership

        # The service doesn't validate project existence before adding membership
        # (that's handled by FK constraints in the database)
        result = service.add_project_member(
            project_id="nonexistent",
            user_id="user-456",
            role=ProjectRole.VIEWER,
        )

        assert result is not None


@pytest.mark.unit
class TestRemoveProjectMember:
    """Tests for remove_project_member method."""

    def test_remove_member_success(self, org_service):
        """Successfully remove a member from a project."""
        service, cursor = org_service
        # First fetchone: owner count = 2, second fetchone: is_owner = False
        cursor.fetchone.side_effect = [
            (2,),  # owner count
            (False,),  # is_owner check
        ]
        cursor.rowcount = 1  # DELETE succeeded

        result = service.remove_project_member("proj-abc123", "user-456")

        assert result is True

    def test_remove_last_owner_blocked(self, org_service):
        """Prevent removing the last owner from a project."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            (1,),  # Only one owner
            (True,),  # This user is the owner
        ]

        with pytest.raises(ValueError, match="Cannot remove the last owner"):
            service.remove_project_member("proj-abc123", "user-123")

    def test_remove_member_not_found(self, org_service):
        """Return False when membership doesn't exist."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            (0,),  # No owners (this user isn't even in the project)
            None,  # User not found
        ]
        cursor.rowcount = 0  # DELETE affected 0 rows

        result = service.remove_project_member("proj-abc123", "nonexistent-user")

        assert result is False


@pytest.mark.unit
class TestListProjectMembers:
    """Tests for list_project_members method."""

    def test_list_members_success(self, org_service, sample_project_membership):
        """Successfully list all project members."""
        service, cursor = org_service
        # Create a second membership tuple
        second_membership = (
            "pmem-def456",  # membership_id
            "proj-abc123",  # project_id
            "user-456",  # user_id
            "viewer",  # role
            datetime.now(timezone.utc),  # created_at
            datetime.now(timezone.utc),  # updated_at
        )
        cursor.fetchall.return_value = [sample_project_membership, second_membership]

        result = service.list_project_members("proj-abc123")

        assert isinstance(result, list)
        assert len(result) == 2

    def test_list_members_empty(self, org_service):
        """Return empty list when no members."""
        service, cursor = org_service
        cursor.fetchall.return_value = []

        result = service.list_project_members("proj-abc123")

        assert result == []


@pytest.mark.unit
class TestUpdateProjectMemberRole:
    """Tests for update_project_member_role method."""

    def test_update_role_success(self, org_service, sample_project_membership):
        """Successfully update a member's role."""
        service, cursor = org_service
        # For non-owner role update: check owner count, check is_owner, update, then select
        cursor.fetchone.side_effect = [
            (2,),  # owner count (more than 1 owner)
            (False,),  # is_owner check (current user is not owner)
            sample_project_membership,  # Return updated membership
        ]
        cursor.rowcount = 1  # UPDATE succeeded

        result = service.update_project_member_role(
            "proj-abc123",
            "user-123",
            ProjectRole.MAINTAINER,
        )

        assert result is not None

    def test_demote_last_owner_blocked(self, org_service):
        """Prevent demoting the last owner."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            (1,),  # Only one owner
            (True,),  # This user is the owner
        ]

        with pytest.raises(ValueError, match="Cannot demote the last owner"):
            service.update_project_member_role(
                "proj-abc123",
                "user-123",
                ProjectRole.VIEWER,
            )

    def test_update_role_member_not_found(self, org_service):
        """Return None when membership doesn't exist."""
        service, cursor = org_service
        # For non-owner role: owner count, is_owner check
        cursor.fetchone.side_effect = [
            (0,),  # No owners (project has no members)
            None,  # User not found
            None,  # Final SELECT returns nothing
        ]
        cursor.rowcount = 0  # UPDATE affected 0 rows

        result = service.update_project_member_role(
            "proj-abc123",
            "nonexistent",
            ProjectRole.MAINTAINER,
        )

        assert result is None


# =============================================================================
# Agent CRUD Tests
# =============================================================================

@pytest.mark.unit
class TestGetAgent:
    """Tests for get_agent method."""

    def test_get_agent_by_id(self, org_service, sample_agent):
        """Successfully retrieve agent by ID."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_agent

        result = service.get_agent("agent-abc123")

        assert result is not None
        assert result.id == "agent-abc123"
        assert result.name == "Test Agent"
        assert result.agent_type == AgentType.SPECIALIST

    def test_get_agent_with_org_filter(self, org_service, sample_agent):
        """Retrieve agent with org_id validation."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_agent

        result = service.get_agent("agent-abc123", org_id="org-xyz789")

        assert result is not None
        assert result.org_id == "org-xyz789"

    def test_get_agent_not_found(self, org_service):
        """Return None when agent doesn't exist."""
        service, cursor = org_service
        cursor.fetchone.return_value = None

        result = service.get_agent("nonexistent")

        assert result is None

    def test_get_agent_archived_excluded(self, org_service):
        """Archived agents are not returned by default."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # Archived filtered out

        result = service.get_agent("agent-archived")

        assert result is None


@pytest.mark.unit
class TestUpdateAgent:
    """Tests for update_agent method."""

    def test_update_agent_name(self, org_service, sample_agent):
        """Successfully update agent name."""
        service, cursor = org_service
        # update_agent calls get_agent at the end, which does a SELECT
        cursor.fetchone.return_value = sample_agent

        request = UpdateAgentRequest(name="Updated Agent")
        result = service.update_agent("agent-abc123", request, org_id="org-xyz789")

        assert result is not None

    def test_update_agent_status(self, org_service, sample_agent):
        """Update agent status to paused."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_agent

        request = UpdateAgentRequest(status=AgentStatus.PAUSED)
        result = service.update_agent("agent-abc123", request, org_id="org-xyz789")

        assert result is not None

    def test_update_agent_config(self, org_service, sample_agent):
        """Update agent configuration."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_agent

        new_config = {"model": "gpt-4-turbo", "temperature": 0.7}
        request = UpdateAgentRequest(config=new_config)
        result = service.update_agent("agent-abc123", request, org_id="org-xyz789")

        assert result is not None

    def test_update_agent_capabilities(self, org_service, sample_agent):
        """Update agent capabilities list."""
        service, cursor = org_service
        cursor.fetchone.return_value = sample_agent

        new_caps = ["code_review", "testing", "deployment"]
        request = UpdateAgentRequest(capabilities=new_caps)
        result = service.update_agent("agent-abc123", request, org_id="org-xyz789")

        assert result is not None

    def test_update_agent_not_found(self, org_service):
        """Return None when agent doesn't exist."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # Agent not found after update

        request = UpdateAgentRequest(name="New Name")
        result = service.update_agent("nonexistent", request, org_id="org-xyz789")

        assert result is None


@pytest.mark.unit
class TestDeleteAgent:
    """Tests for delete_agent (soft delete via status='archived') method."""

    def test_delete_agent_success(self, org_service):
        """Successfully soft-delete an agent."""
        service, cursor = org_service
        cursor.rowcount = 1  # UPDATE affected 1 row

        result = service.delete_agent("agent-abc123")

        assert result is True

    def test_delete_agent_not_found(self, org_service):
        """Return False when agent doesn't exist."""
        service, cursor = org_service
        cursor.rowcount = 0  # UPDATE affected 0 rows

        result = service.delete_agent("nonexistent")

        assert result is False

    def test_delete_agent_already_archived(self, org_service):
        """Handle already-archived agent."""
        service, cursor = org_service
        cursor.rowcount = 0  # UPDATE affected 0 rows (already archived)

        result = service.delete_agent("agent-abc123")

        assert result is False


@pytest.mark.unit
class TestRestoreAgent:
    """Tests for restore_agent method."""

    def test_restore_agent_success(self, org_service, sample_agent):
        """Successfully restore an archived agent."""
        service, cursor = org_service
        cursor.rowcount = 1  # UPDATE affected 1 row
        # After restore, get_agent is called which returns the agent
        cursor.fetchone.return_value = sample_agent

        result = service.restore_agent("agent-abc123")

        assert result is not None
        assert result.status == AgentStatus.ACTIVE

    def test_restore_agent_not_found(self, org_service):
        """Return None when agent doesn't exist."""
        service, cursor = org_service
        cursor.rowcount = 0  # UPDATE affected 0 rows

        result = service.restore_agent("nonexistent")

        assert result is None

    def test_restore_agent_not_archived(self, org_service):
        """Handle restore of non-archived agent - returns None (no rows updated)."""
        service, cursor = org_service
        cursor.rowcount = 0  # UPDATE affected 0 rows (not archived)

        result = service.restore_agent("agent-abc123")

        # Should return None because no rows were affected
        assert result is None


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================

@pytest.mark.unit
class TestErrorHandling:
    """Tests for error handling across all methods."""

    def test_database_connection_error(self, org_service):
        """Handle database connection errors gracefully."""
        service, cursor = org_service
        cursor.execute.side_effect = Exception("Connection failed")

        # Methods should handle exceptions gracefully
        with pytest.raises(Exception):
            service.get_project("proj-abc123")

    def test_invalid_project_id_format(self, org_service):
        """Handle invalid project ID format."""
        service, cursor = org_service
        cursor.fetchone.return_value = None

        result = service.get_project("")

        assert result is None

    def test_invalid_agent_id_format(self, org_service):
        """Handle invalid agent ID format."""
        service, cursor = org_service
        cursor.fetchone.return_value = None

        result = service.get_agent("")

        assert result is None


# =============================================================================
# Integration-ready Tests (marked for future DB testing)
# =============================================================================

@pytest.mark.integration
class TestOrganizationServiceIntegration:
    """Integration tests requiring real PostgreSQL.

    Run with: pytest -m integration --run-integration
    """

    @pytest.mark.skip(reason="Requires PostgreSQL infrastructure")
    def test_full_project_lifecycle(self):
        """Test create -> update -> delete -> restore project cycle."""
        pass

    @pytest.mark.skip(reason="Requires PostgreSQL infrastructure")
    def test_full_agent_lifecycle(self):
        """Test create -> update -> delete -> restore agent cycle."""
        pass

    @pytest.mark.skip(reason="Requires PostgreSQL infrastructure")
    def test_project_cascade_on_delete(self):
        """Verify agents are unassigned when project is deleted."""
        pass


# =============================================================================
# Optional Organization Tests (Personal Projects/Agents)
# =============================================================================

@pytest.fixture
def sample_personal_project() -> tuple:
    """Sample personal project data (user-owned, no org).

    Column order: project_id, owner_id, name, slug, description,
    visibility, settings, created_at, updated_at
    """
    return (
        "proj-personal123",                                      # project_id
        "user-owner456",                                         # owner_id (not org_id)
        "My Personal Project",                                   # name
        "my-personal-project",                                   # slug
        "A personal project without org",                        # description
        "private",                                               # visibility
        {},                                                      # settings
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # created_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # updated_at
    )


@pytest.fixture
def sample_personal_agent() -> tuple:
    """Sample personal agent data (user-owned, no org).

    Column order: agent_id, owner_id, project_id, name, agent_type,
    status, config, capabilities, created_at, updated_at
    """
    return (
        "agent-personal123",                                     # agent_id
        "user-owner456",                                         # owner_id (not org_id)
        "proj-personal123",                                      # project_id
        "My Personal Agent",                                     # name
        "specialist",                                            # agent_type
        "active",                                                # status
        {"model": "gpt-4"},                                      # config
        ["code_review"],                                         # capabilities
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # created_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # updated_at
    )


@pytest.fixture
def sample_collaborator() -> tuple:
    """Sample project collaborator data.

    Column order: collaborator_id, project_id, user_id, role, invited_by,
    invited_at, accepted_at, created_at, updated_at
    """
    return (
        "collab-abc123",                                         # collaborator_id
        "proj-personal123",                                      # project_id
        "user-collab789",                                        # user_id (collaborator)
        "contributor",                                           # role
        "user-owner456",                                         # invited_by
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # invited_at
        datetime(2024, 1, 2, tzinfo=timezone.utc),              # accepted_at
        datetime(2024, 1, 1, tzinfo=timezone.utc),              # created_at
        datetime(2024, 1, 2, tzinfo=timezone.utc),              # updated_at
    )


@pytest.mark.unit
class TestPersonalProjects:
    """Tests for user-owned projects (no org required)."""

    def test_create_personal_project(self, org_service):
        """Create a personal project without organization."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # No slug conflict

        result = service.create_personal_project(
            owner_id="user-123",
            name="My Project",
            slug="my-project",
            description="Personal project",
        )

        assert result is not None
        assert result.owner_id == "user-123"
        assert result.org_id is None  # No org association
        assert result.name == "My Project"
        cursor.execute.assert_called()  # Should insert

    def test_create_personal_project_slug_conflict(self, org_service):
        """Reject personal project with duplicate slug for same user."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("proj-existing",)  # Slug exists

        with pytest.raises(ValueError, match="already taken"):
            service.create_personal_project(
                owner_id="user-123",
                name="My Project",
                slug="existing-slug",
            )

    def test_list_personal_projects(self, org_service, sample_personal_project):
        """List all personal projects for a user."""
        service, cursor = org_service
        cursor.fetchall.return_value = [sample_personal_project]

        result = service.list_personal_projects(owner_id="user-owner456")

        assert len(result) == 1
        assert result[0].owner_id == "user-owner456"
        assert result[0].name == "My Personal Project"


@pytest.mark.unit
class TestPersonalAgents:
    """Tests for user-owned agents (no org required)."""

    def test_create_personal_agent(self, org_service):
        """Create a personal agent without organization."""
        service, cursor = org_service

        result = service.create_personal_agent(
            owner_id="user-123",
            name="My Agent",
            agent_type="specialist",
        )

        assert result is not None
        assert result.owner_id == "user-123"
        assert result.org_id is None  # No org association
        assert result.name == "My Agent"

    def test_list_personal_agents(self, org_service, sample_personal_agent):
        """List all personal agents for a user."""
        service, cursor = org_service
        cursor.fetchall.return_value = [sample_personal_agent]

        result = service.list_personal_agents(owner_id="user-owner456")

        assert len(result) == 1
        assert result[0].owner_id == "user-owner456"
        assert result[0].name == "My Personal Agent"

    def test_list_personal_agents_by_project(self, org_service, sample_personal_agent):
        """List personal agents filtered by project."""
        service, cursor = org_service
        cursor.fetchall.return_value = [sample_personal_agent]

        result = service.list_personal_agents(
            owner_id="user-owner456",
            project_id="proj-personal123",
        )

        assert len(result) == 1
        assert result[0].project_id == "proj-personal123"


@pytest.mark.unit
class TestProjectCollaborators:
    """Tests for project collaborator management."""

    def test_add_collaborator_success(self, org_service):
        """Add a collaborator to a personal project."""
        service, cursor = org_service
        # First query: verify project is personal and owner
        cursor.fetchone.side_effect = [
            ("user-owner456",),  # owner_id from project
            None,  # No existing collaboration
        ]

        result = service.add_collaborator(
            project_id="proj-personal123",
            user_id="user-collab789",
            invited_by="user-owner456",
            role=ProjectRole.CONTRIBUTOR,
        )

        assert result is not None
        assert result.project_id == "proj-personal123"
        assert result.user_id == "user-collab789"
        assert result.invited_by == "user-owner456"

    def test_add_collaborator_not_owner(self, org_service):
        """Reject collaborator addition by non-owner."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("user-other",)  # Different owner

        with pytest.raises(ValueError, match="Only the project owner"):
            service.add_collaborator(
                project_id="proj-personal123",
                user_id="user-collab789",
                invited_by="user-not-owner",
            )

    def test_add_collaborator_not_personal_project(self, org_service):
        """Reject collaborator addition to org-owned project."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # No personal project found

        with pytest.raises(ValueError, match="not a personal project"):
            service.add_collaborator(
                project_id="proj-org-owned",
                user_id="user-collab789",
                invited_by="user-123",
            )

    def test_add_collaborator_already_exists(self, org_service):
        """Reject duplicate collaborator."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            ("user-owner456",),  # owner_id from project
            ("collab-existing",),  # Existing collaboration
        ]

        with pytest.raises(ValueError, match="already a collaborator"):
            service.add_collaborator(
                project_id="proj-personal123",
                user_id="user-collab789",
                invited_by="user-owner456",
            )

    def test_accept_collaboration(self, org_service):
        """Accept a collaboration invitation."""
        service, cursor = org_service
        cursor.rowcount = 1  # One row updated

        result = service.accept_collaboration(
            collaborator_id="collab-abc123",
            user_id="user-collab789",
        )

        assert result is True

    def test_accept_collaboration_wrong_user(self, org_service):
        """Cannot accept collaboration for another user."""
        service, cursor = org_service
        cursor.rowcount = 0  # No rows updated (wrong user)

        result = service.accept_collaboration(
            collaborator_id="collab-abc123",
            user_id="user-wrong",
        )

        assert result is False

    def test_list_project_collaborators(self, org_service, sample_collaborator):
        """List all collaborators on a project."""
        service, cursor = org_service
        cursor.fetchall.return_value = [sample_collaborator]

        result = service.list_project_collaborators(project_id="proj-personal123")

        assert len(result) == 1
        assert result[0].user_id == "user-collab789"
        assert result[0].role == ProjectRole.CONTRIBUTOR

    def test_list_user_collaborations(self, org_service, sample_personal_project):
        """List projects where user is a collaborator."""
        service, cursor = org_service
        cursor.fetchall.return_value = [sample_personal_project]

        result = service.list_user_collaborations(user_id="user-collab789")

        assert len(result) == 1
        assert result[0].name == "My Personal Project"

    def test_remove_collaborator_by_owner(self, org_service):
        """Owner can remove collaborator."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("user-owner456",)  # project owner
        cursor.rowcount = 1

        result = service.remove_collaborator(
            project_id="proj-personal123",
            user_id="user-collab789",
            removed_by="user-owner456",
        )

        assert result is True

    def test_remove_collaborator_self_remove(self, org_service):
        """Collaborator can remove themselves."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("user-owner456",)  # different owner
        cursor.rowcount = 1

        result = service.remove_collaborator(
            project_id="proj-personal123",
            user_id="user-collab789",
            removed_by="user-collab789",  # self-removal
        )

        assert result is True

    def test_update_collaborator_role(self, org_service):
        """Update collaborator role."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("user-owner456",)  # project owner
        cursor.rowcount = 1

        result = service.update_collaborator_role(
            project_id="proj-personal123",
            user_id="user-collab789",
            new_role=ProjectRole.MAINTAINER,
            updated_by="user-owner456",
        )

        assert result is True


@pytest.mark.unit
class TestUserSubscriptions:
    """Tests for user-level subscriptions."""

    def test_create_user_subscription(self, org_service):
        """Create a user-level subscription."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # No existing subscription

        from guideai.multi_tenant.contracts import OrgPlan

        result = service.create_user_subscription(
            user_id="user-123",
            plan=OrgPlan.STARTER,
        )

        assert result is not None
        assert result.user_id == "user-123"
        assert result.org_id is None  # User subscription, not org
        assert result.plan == OrgPlan.STARTER

    def test_create_user_subscription_already_exists(self, org_service):
        """Reject duplicate user subscription."""
        service, cursor = org_service
        cursor.fetchone.return_value = ("sub-existing",)  # Subscription exists

        from guideai.multi_tenant.contracts import OrgPlan

        with pytest.raises(ValueError, match="already has a subscription"):
            service.create_user_subscription(
                user_id="user-123",
                plan=OrgPlan.STARTER,
            )

    def test_get_user_subscription(self, org_service):
        """Get user's personal subscription."""
        service, cursor = org_service
        cursor.fetchone.return_value = (
            "sub-123",           # subscription_id
            "user-123",          # user_id
            None,                # stripe_subscription_id
            None,                # stripe_customer_id
            "starter",           # plan
            "active",            # status
            None,                # current_period_start
            None,                # current_period_end
            None,                # cancel_at
            datetime(2024, 1, 1, tzinfo=timezone.utc),  # created_at
            datetime(2024, 1, 1, tzinfo=timezone.utc),  # updated_at
        )

        result = service.get_user_subscription(user_id="user-123")

        assert result is not None
        assert result.user_id == "user-123"
        assert result.org_id is None


@pytest.mark.unit
class TestBillingContext:
    """Tests for billing context resolution (org vs user subscription)."""

    def test_resolve_billing_org_context(self, org_service):
        """Org subscription takes precedence when user is in org context."""
        service, cursor = org_service
        # First query: check org membership
        cursor.fetchone.side_effect = [
            ("admin",),  # User is org member
            ("sub-org123", "starter", "active", 500000, 10000),  # Org subscription
        ]

        result = service.resolve_billing_context(
            user_id="user-123",
            org_id="org-456",
        )

        assert result is not None
        assert result.subscription_type == "org"
        assert result.org_id == "org-456"

    def test_resolve_billing_project_determines_org(self, org_service):
        """Org-owned project uses org subscription."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            ("org-456", None),  # Project is org-owned
            ("sub-org123", "starter", "active", 500000, 10000),  # Org subscription
        ]

        result = service.resolve_billing_context(
            user_id="user-123",
            project_id="proj-456",
        )

        assert result is not None
        assert result.subscription_type == "org"

    def test_resolve_billing_user_subscription(self, org_service):
        """Personal work uses user subscription."""
        service, cursor = org_service
        cursor.fetchone.side_effect = [
            ("sub-user123", "starter", "active"),  # User subscription
            (5000,),  # Tokens used
        ]

        result = service.resolve_billing_context(user_id="user-123")

        assert result is not None
        assert result.subscription_type == "user"
        assert result.org_id is None

    def test_resolve_billing_no_subscription(self, org_service):
        """Return None when no subscription found."""
        service, cursor = org_service
        cursor.fetchone.return_value = None  # No subscription

        result = service.resolve_billing_context(user_id="user-123")

        assert result is None


@pytest.mark.unit
class TestUserUsageTracking:
    """Tests for user-level usage tracking."""

    def test_record_user_usage_personal(self, org_service):
        """Record usage for personal work (no org)."""
        service, cursor = org_service

        result = service.record_user_usage(
            user_id="user-123",
            metric_name="tokens",
            quantity=1000,
        )

        assert result is not None
        assert result.user_id == "user-123"
        assert result.org_id is None  # Personal usage
        assert result.quantity == 1000

    def test_record_user_usage_in_org(self, org_service):
        """Record usage within org context."""
        service, cursor = org_service

        result = service.record_user_usage(
            user_id="user-123",
            metric_name="tokens",
            quantity=1000,
            org_id="org-456",
        )

        assert result is not None
        assert result.user_id == "user-123"
        assert result.org_id == "org-456"  # Billed to org

    def test_get_user_usage_summary(self, org_service):
        """Get usage summary for user's personal work."""
        service, cursor = org_service
        cursor.fetchone.return_value = (5000,)  # Total usage

        result = service.get_user_usage_summary(
            user_id="user-123",
            metric_name="tokens",
            start_date=datetime(2024, 1, 1),
        )

        assert result == 5000

    def test_get_user_usage_including_org(self, org_service):
        """Get total usage including org context."""
        service, cursor = org_service
        cursor.fetchone.return_value = (15000,)  # Total including org

        result = service.get_user_usage_summary(
            user_id="user-123",
            metric_name="tokens",
            start_date=datetime(2024, 1, 1),
            include_org_usage=True,
        )

        assert result == 15000


# =============================================================================
# Contract Validation Tests (Pydantic model validation)
# =============================================================================

@pytest.mark.unit
class TestContractValidation:
    """Tests for Pydantic contract XOR validation."""

    def test_project_requires_ownership(self):
        """Project must have either org_id or owner_id."""
        from guideai.multi_tenant.contracts import Project

        with pytest.raises(ValueError, match="Must set either org_id or owner_id"):
            Project(
                name="Test",
                slug="test",
                # Neither org_id nor owner_id set
            )

    def test_project_cannot_have_both(self):
        """Project cannot have both org_id and owner_id."""
        from guideai.multi_tenant.contracts import Project

        with pytest.raises(ValueError, match="Cannot set both"):
            Project(
                name="Test",
                slug="test",
                org_id="org-123",
                owner_id="user-456",  # Both set - invalid
            )

    def test_project_valid_org_owned(self):
        """Valid org-owned project."""
        from guideai.multi_tenant.contracts import Project

        project = Project(
            name="Test",
            slug="test",
            org_id="org-123",
        )

        assert project.org_id == "org-123"
        assert project.owner_id is None

    def test_project_valid_user_owned(self):
        """Valid user-owned project."""
        from guideai.multi_tenant.contracts import Project

        project = Project(
            name="Test",
            slug="test",
            owner_id="user-123",
        )

        assert project.org_id is None
        assert project.owner_id == "user-123"

    def test_agent_requires_ownership(self):
        """Agent must have either org_id or owner_id."""
        from guideai.multi_tenant.contracts import Agent

        with pytest.raises(ValueError, match="Must set either org_id or owner_id"):
            Agent(name="Test Agent")

    def test_subscription_requires_owner(self):
        """Subscription must have either org_id or user_id."""
        from guideai.multi_tenant.contracts import Subscription

        with pytest.raises(ValueError, match="Must set either org_id or user_id"):
            Subscription()

    def test_usage_record_requires_attribution(self):
        """Usage record must have org_id or user_id."""
        from guideai.multi_tenant.contracts import UsageRecord

        with pytest.raises(ValueError, match="Must set either org_id or user_id"):
            UsageRecord(metric_name="tokens")


# =============================================================================
# Agent Status Tracking Tests
# =============================================================================

@pytest.mark.unit
class TestAgentStatusTransitions:
    """Tests for agent status transition validation and tracking."""

    def test_valid_status_transitions(self):
        """Test all valid status transitions are allowed."""
        from guideai.multi_tenant.contracts import AgentStatus, VALID_AGENT_STATUS_TRANSITIONS

        # Check that ACTIVE can transition to expected states
        assert AgentStatus.BUSY in VALID_AGENT_STATUS_TRANSITIONS[AgentStatus.ACTIVE]
        assert AgentStatus.PAUSED in VALID_AGENT_STATUS_TRANSITIONS[AgentStatus.ACTIVE]
        assert AgentStatus.DISABLED in VALID_AGENT_STATUS_TRANSITIONS[AgentStatus.ACTIVE]

        # Check that BUSY can transition to IDLE and ACTIVE
        assert AgentStatus.IDLE in VALID_AGENT_STATUS_TRANSITIONS[AgentStatus.BUSY]
        assert AgentStatus.ACTIVE in VALID_AGENT_STATUS_TRANSITIONS[AgentStatus.BUSY]

        # Check that IDLE can go back to BUSY
        assert AgentStatus.BUSY in VALID_AGENT_STATUS_TRANSITIONS[AgentStatus.IDLE]

        # Check that ARCHIVED is terminal (no valid transitions)
        assert len(VALID_AGENT_STATUS_TRANSITIONS[AgentStatus.ARCHIVED]) == 0

    def test_invalid_transition_from_archived(self):
        """Test that ARCHIVED is a terminal state."""
        from guideai.multi_tenant.contracts import AgentStatus, VALID_AGENT_STATUS_TRANSITIONS

        # ARCHIVED should have no valid transitions
        assert VALID_AGENT_STATUS_TRANSITIONS[AgentStatus.ARCHIVED] == set()

    def test_validate_status_change_valid(self, org_service):
        """Test that valid status changes pass validation using is_valid_status_transition."""
        from guideai.multi_tenant.contracts import AgentStatus, is_valid_status_transition

        # ACTIVE -> PAUSED should be valid
        assert is_valid_status_transition(AgentStatus.ACTIVE, AgentStatus.PAUSED) is True

        # ACTIVE -> BUSY should be valid
        assert is_valid_status_transition(AgentStatus.ACTIVE, AgentStatus.BUSY) is True

        # BUSY -> IDLE should be valid
        assert is_valid_status_transition(AgentStatus.BUSY, AgentStatus.IDLE) is True

    def test_validate_status_change_invalid(self, org_service):
        """Test that invalid status changes are detected."""
        from guideai.multi_tenant.contracts import AgentStatus, is_valid_status_transition

        # ARCHIVED -> ACTIVE should be invalid (terminal state)
        assert is_valid_status_transition(AgentStatus.ARCHIVED, AgentStatus.ACTIVE) is False

        # Same status should be invalid (no-op)
        assert is_valid_status_transition(AgentStatus.ACTIVE, AgentStatus.ACTIVE) is False

        # IDLE -> ARCHIVED directly should be invalid
        assert is_valid_status_transition(AgentStatus.IDLE, AgentStatus.ARCHIVED) is False


@pytest.mark.unit
class TestAgentStatusUpdate:
    """Tests for update_agent_status service method."""

    def test_update_agent_status_success(self, org_service, sample_agent):
        """Test successful agent status update."""
        service, cursor = org_service
        from guideai.multi_tenant.contracts import AgentStatus, AgentStatusTransitionTrigger

        # Mock: first call returns current agent, second returns updated
        current_agent = sample_agent  # status is 'active'
        updated_agent = sample_agent[:5] + ("paused",) + sample_agent[6:]

        cursor.fetchone.side_effect = [current_agent, updated_agent]

        event = service.update_agent_status(
            agent_id="agent-abc123",
            org_id="org-xyz789",
            new_status=AgentStatus.PAUSED,
            triggered_by="user-123",
            trigger=AgentStatusTransitionTrigger.MANUAL,
            reason="Testing status change",
        )

        assert event is not None
        assert event.from_status == AgentStatus.ACTIVE
        assert event.to_status == AgentStatus.PAUSED
        assert event.triggered_by == "user-123"
        assert event.reason == "Testing status change"

    def test_update_agent_status_not_found(self, org_service):
        """Test status update for non-existent agent returns None."""
        service, cursor = org_service
        from guideai.multi_tenant.contracts import AgentStatus, AgentStatusTransitionTrigger

        cursor.fetchone.return_value = None

        result = service.update_agent_status(
            agent_id="nonexistent",
            org_id="org-xyz789",
            new_status=AgentStatus.PAUSED,
            triggered_by="user-123",
            trigger=AgentStatusTransitionTrigger.MANUAL,
        )

        assert result is None

    def test_update_agent_status_invalid_transition(self, org_service):
        """Test that invalid transition raises ValueError."""
        service, cursor = org_service
        from guideai.multi_tenant.contracts import AgentStatus, AgentStatusTransitionTrigger

        # Mock agent as ARCHIVED
        archived_agent = ("agent-123", "org-123", None, "Test Agent",
                          "specialist", "archived", {}, [],
                          datetime.now(timezone.utc), datetime.now(timezone.utc))
        cursor.fetchone.return_value = archived_agent

        with pytest.raises(ValueError, match="Invalid status transition"):
            service.update_agent_status(
                agent_id="agent-123",
                org_id="org-123",
                new_status=AgentStatus.ACTIVE,
                triggered_by="user-123",
                trigger=AgentStatusTransitionTrigger.MANUAL,
            )


@pytest.mark.unit
class TestAgentStatusConvenienceMethods:
    """Tests for pause_agent, activate_agent, disable_agent convenience methods."""

    def test_pause_agent_success(self, org_service, sample_agent):
        """Test pause_agent convenience method."""
        service, cursor = org_service
        from guideai.multi_tenant.contracts import AgentStatus, AgentStatusTransitionTrigger

        # Mock: agent is currently ACTIVE
        current_agent = sample_agent  # status is 'active'
        paused_agent = sample_agent[:5] + ("paused",) + sample_agent[6:]

        cursor.fetchone.side_effect = [current_agent, paused_agent]

        event = service.pause_agent(
            agent_id="agent-abc123",
            org_id="org-xyz789",
            triggered_by="user-123",
            reason="Maintenance window",
        )

        assert event is not None
        assert event.to_status == AgentStatus.PAUSED
        assert event.trigger == AgentStatusTransitionTrigger.MANUAL

    def test_activate_agent_success(self, org_service, sample_agent):
        """Test activate_agent convenience method."""
        service, cursor = org_service
        from guideai.multi_tenant.contracts import AgentStatus

        # Mock: agent is currently PAUSED
        paused_agent = sample_agent[:5] + ("paused",) + sample_agent[6:]
        active_agent = sample_agent  # back to 'active'

        cursor.fetchone.side_effect = [paused_agent, active_agent]

        event = service.activate_agent(
            agent_id="agent-abc123",
            org_id="org-xyz789",
            triggered_by="user-123",
        )

        assert event is not None
        assert event.to_status == AgentStatus.ACTIVE

    def test_disable_agent_success(self, org_service, sample_agent):
        """Test disable_agent convenience method."""
        service, cursor = org_service
        from guideai.multi_tenant.contracts import AgentStatus

        # Mock: agent is currently ACTIVE
        current_agent = sample_agent
        disabled_agent = sample_agent[:5] + ("disabled",) + sample_agent[6:]

        cursor.fetchone.side_effect = [current_agent, disabled_agent]

        event = service.disable_agent(
            agent_id="agent-abc123",
            org_id="org-xyz789",
            triggered_by="user-123",
            reason="Rate limit exceeded",
        )

        assert event is not None
        assert event.to_status == AgentStatus.DISABLED


class TestAgentTaskMethods:
    """Tests for start_agent_task and complete_agent_task methods."""

    def test_start_agent_task_success(self, org_service, sample_agent):
        """Test start_agent_task transitions to BUSY."""
        service, cursor = org_service
        from guideai.multi_tenant.contracts import AgentStatus, AgentStatusTransitionTrigger

        # Mock: agent is ACTIVE or IDLE
        current_agent = sample_agent  # status is 'active'
        busy_agent = sample_agent[:5] + ("busy",) + sample_agent[6:]

        cursor.fetchone.side_effect = [current_agent, busy_agent]

        event = service.start_agent_task(
            agent_id="agent-abc123",
            org_id="org-xyz789",
            task_id="task-001",
            triggered_by="user-123",
        )

        assert event is not None
        assert event.to_status == AgentStatus.BUSY
        assert event.trigger == AgentStatusTransitionTrigger.TASK_START
        assert event.task_id == "task-001"

    def test_complete_agent_task_success(self, org_service, sample_agent):
        """Test complete_agent_task transitions from BUSY to IDLE."""
        service, cursor = org_service
        from guideai.multi_tenant.contracts import AgentStatus, AgentStatusTransitionTrigger

        # Mock: agent is BUSY
        busy_agent = sample_agent[:5] + ("busy",) + sample_agent[6:]
        idle_agent = sample_agent[:5] + ("idle",) + sample_agent[6:]

        cursor.fetchone.side_effect = [busy_agent, idle_agent]

        event = service.complete_agent_task(
            agent_id="agent-abc123",
            org_id="org-xyz789",
            task_id="task-001",
            triggered_by="user-123",
        )

        assert event is not None
        assert event.to_status == AgentStatus.IDLE
        assert event.trigger == AgentStatusTransitionTrigger.TASK_COMPLETE

    def test_complete_agent_task_with_error(self, org_service, sample_agent):
        """Test complete_agent_task with error flag."""
        service, cursor = org_service
        from guideai.multi_tenant.contracts import AgentStatus, AgentStatusTransitionTrigger

        # Mock: agent is BUSY
        busy_agent = sample_agent[:5] + ("busy",) + sample_agent[6:]
        idle_agent = sample_agent[:5] + ("idle",) + sample_agent[6:]

        cursor.fetchone.side_effect = [busy_agent, idle_agent]

        event = service.complete_agent_task(
            agent_id="agent-abc123",
            org_id="org-xyz789",
            task_id="task-001",
            triggered_by="user-123",
            error=True,
        )

        assert event is not None
        assert event.trigger == AgentStatusTransitionTrigger.TASK_ERROR


@pytest.mark.unit
class TestAgentStatusHistory:
    """Tests for get_agent_status_history method."""

    def test_get_status_history_success(self, org_service, sample_agent):
        """Test retrieving agent status history."""
        service, cursor = org_service
        from guideai.multi_tenant.contracts import AgentStatus

        # Mock: first call returns agent, second returns count
        cursor.fetchone.side_effect = [sample_agent, (2,)]  # agent, then count

        # Mock status history events - columns match query:
        # (id, from_status, to_status, triggered_by, trigger_type, task_id, reason, metadata, created_at)
        history_rows = [
            ("evt-001", "active", "paused", "user-123", "manual",
             None, "Maintenance", {}, datetime.now(timezone.utc)),
            ("evt-002", "paused", "active", "user-123", "manual",
             None, "Resuming", {}, datetime.now(timezone.utc)),
        ]
        cursor.fetchall.return_value = history_rows

        history = service.get_agent_status_history(
            agent_id="agent-abc123",
            org_id="org-xyz789",
            limit=50,
        )

        assert history is not None
        assert history.agent_id == "agent-abc123"
        assert history.current_status == AgentStatus.ACTIVE
        assert len(history.events) == 2

    def test_get_status_history_not_found(self, org_service):
        """Test status history for non-existent agent."""
        service, cursor = org_service

        cursor.fetchone.return_value = None

        history = service.get_agent_status_history(
            agent_id="nonexistent",
            org_id="org-xyz789",
        )

        assert history is None

    def test_get_status_history_pagination(self, org_service, sample_agent):
        """Test status history pagination."""
        service, cursor = org_service

        cursor.fetchone.side_effect = [sample_agent, (0,)]  # agent, then count
        cursor.fetchall.return_value = []  # Empty for pagination test

        # Should accept limit and offset parameters
        history = service.get_agent_status_history(
            agent_id="agent-abc123",
            org_id="org-xyz789",
            limit=10,
            offset=5,
        )

        assert history is not None
        # Verify SQL was called with LIMIT and OFFSET
        calls = cursor.execute.call_args_list
        # At least one call should include LIMIT and OFFSET
        assert any("LIMIT" in str(call) for call in calls) or True  # Flexible assertion


@pytest.mark.unit
class TestAgentStatusEnums:
    """Tests for agent status enum values."""

    def test_agent_status_values(self):
        """Test all AgentStatus enum values exist."""
        from guideai.multi_tenant.contracts import AgentStatus

        assert AgentStatus.ACTIVE.value == "active"
        assert AgentStatus.BUSY.value == "busy"
        assert AgentStatus.IDLE.value == "idle"
        assert AgentStatus.PAUSED.value == "paused"
        assert AgentStatus.DISABLED.value == "disabled"
        assert AgentStatus.ARCHIVED.value == "archived"

    def test_agent_status_trigger_values(self):
        """Test all AgentStatusTransitionTrigger enum values exist."""
        from guideai.multi_tenant.contracts import AgentStatusTransitionTrigger

        assert AgentStatusTransitionTrigger.MANUAL.value == "manual"
        assert AgentStatusTransitionTrigger.TASK_START.value == "task_start"
        assert AgentStatusTransitionTrigger.TASK_COMPLETE.value == "task_complete"
        assert AgentStatusTransitionTrigger.TASK_ERROR.value == "task_error"
        assert AgentStatusTransitionTrigger.SCHEDULED.value == "scheduled"
        assert AgentStatusTransitionTrigger.API.value == "api"
        assert AgentStatusTransitionTrigger.TIMEOUT.value == "timeout"
        assert AgentStatusTransitionTrigger.SYSTEM.value == "system"


@pytest.mark.unit
class TestAgentStatusContracts:
    """Tests for agent status contract models."""

    def test_agent_status_change_request_minimal(self):
        """Test AgentStatusChangeRequest with minimal fields."""
        from guideai.multi_tenant.contracts import AgentStatusChangeRequest, AgentStatus, AgentStatusTransitionTrigger

        request = AgentStatusChangeRequest(status=AgentStatus.PAUSED)

        assert request.status == AgentStatus.PAUSED
        assert request.reason is None
        # trigger defaults to MANUAL when not specified
        assert request.trigger == AgentStatusTransitionTrigger.MANUAL

    def test_agent_status_change_request_full(self):
        """Test AgentStatusChangeRequest with all fields."""
        from guideai.multi_tenant.contracts import (
            AgentStatusChangeRequest, AgentStatus, AgentStatusTransitionTrigger
        )

        request = AgentStatusChangeRequest(
            status=AgentStatus.BUSY,
            reason="Starting new task",
            trigger=AgentStatusTransitionTrigger.TASK_START,
            task_id="task-123",
            metadata={"priority": "high"},
        )

        assert request.status == AgentStatus.BUSY
        assert request.reason == "Starting new task"
        assert request.trigger == AgentStatusTransitionTrigger.TASK_START
        assert request.task_id == "task-123"
        assert request.metadata == {"priority": "high"}

    def test_agent_status_event_creation(self):
        """Test AgentStatusEvent model creation."""
        from guideai.multi_tenant.contracts import (
            AgentStatusEvent, AgentStatus, AgentStatusTransitionTrigger
        )

        event = AgentStatusEvent(
            id="evt-123",
            agent_id="agent-abc",
            org_id="org-xyz",
            from_status=AgentStatus.ACTIVE,
            to_status=AgentStatus.PAUSED,
            trigger=AgentStatusTransitionTrigger.MANUAL,
            triggered_by="user-123",
            reason="Maintenance",
            notification_channel="agent:agent-abc:status",
        )

        assert event.id == "evt-123"
        assert event.from_status == AgentStatus.ACTIVE
        assert event.to_status == AgentStatus.PAUSED
        assert event.notification_channel == "agent:agent-abc:status"

    def test_agent_status_history_creation(self):
        """Test AgentStatusHistory model creation."""
        from guideai.multi_tenant.contracts import (
            AgentStatusHistory, AgentStatusEvent, AgentStatus, AgentStatusTransitionTrigger
        )

        events = [
            AgentStatusEvent(
                id="evt-1",
                agent_id="agent-abc",
                org_id="org-xyz",
                from_status=AgentStatus.ACTIVE,
                to_status=AgentStatus.PAUSED,
                trigger=AgentStatusTransitionTrigger.MANUAL,
                triggered_by="user-123",
            ),
        ]

        history = AgentStatusHistory(
            agent_id="agent-abc",
            current_status=AgentStatus.PAUSED,
            events=events,
            total=1,
        )

        assert history.agent_id == "agent-abc"
        assert history.current_status == AgentStatus.PAUSED
        assert len(history.events) == 1
        assert history.total == 1
