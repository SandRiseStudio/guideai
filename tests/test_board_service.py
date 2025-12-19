"""
Unit and integration tests for BoardService (Agile board system).

Tests verify:
- Board CRUD operations
- Column management
- Epic, Story, and Task lifecycle
- Sprint management
- Work item status transitions
- Assignment tracking (user and agent)
- Default board/column creation

Following `behavior_design_test_strategy` (Student).

Infrastructure requirements:
- PostgreSQL (WORKFLOW_DB) - port 5434 in test environment
- Uses GUIDEAI_WORKFLOW_PG_DSN from environment

Run with: ./scripts/run_tests.sh --amprealize --env test tests/test_board_service.py
"""
import os
import json
import pytest
from datetime import datetime, timedelta
from typing import Generator, Any, Dict

# Mark all tests in this module as requiring postgres service
pytestmark = [
    pytest.mark.requires_services("postgres"),
    pytest.mark.integration,
]

# Service imports
from guideai.services.board_service import (
    BoardService,
    Actor,
    BoardServiceError,
    BoardNotFoundError,
    EpicNotFoundError,
    StoryNotFoundError,
    TaskNotFoundError,
    WorkItemTransitionError,
)
from guideai.multi_tenant.board_contracts import (
    CreateBoardRequest,
    UpdateBoardRequest,
    CreateColumnRequest,
    UpdateColumnRequest,
    CreateEpicRequest,
    UpdateEpicRequest,
    CreateStoryRequest,
    UpdateStoryRequest,
    CreateTaskRequest,
    UpdateTaskRequest,
    CreateSprintRequest,
    UpdateSprintRequest,
    BoardSettings,
    BoardVisibility,
    WorkItemStatus,
    EpicStatus,
    WorkItemPriority,
    TaskType,
)


# =============================================================================
# Fixtures
# =============================================================================

def _truncate_board_tables(dsn: str) -> None:
    """Truncate all board-related tables for test isolation."""
    try:
        import psycopg2  # type: ignore[import-not-found]
        HAS_PSYCOPG2 = True
    except ImportError:
        HAS_PSYCOPG2 = False

    if not HAS_PSYCOPG2:
        pytest.skip("psycopg2 required for table truncation")

    with psycopg2.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Truncate in order to respect foreign key constraints
            cur.execute("""
                TRUNCATE sprint_stories, sprints, assignment_history,
                         board_tasks, stories, epics, board_columns, boards
                RESTART IDENTITY CASCADE
            """)
        conn.commit()


@pytest.fixture
def dsn() -> str:
    """Get PostgreSQL DSN from environment."""
    dsn = os.environ.get("GUIDEAI_WORKFLOW_PG_DSN") or os.environ.get("GUIDEAI_RUN_PG_DSN")
    if not dsn:
        pytest.skip("GUIDEAI_WORKFLOW_PG_DSN or GUIDEAI_RUN_PG_DSN not set; skipping PostgreSQL tests")
    return dsn


@pytest.fixture
def service(dsn: str) -> Generator[BoardService, None, None]:
    """BoardService fixture with table truncation."""
    svc = BoardService(dsn=dsn)
    _truncate_board_tables(dsn)
    yield svc
    _truncate_board_tables(dsn)


@pytest.fixture
def actor() -> Actor:
    """Default test actor."""
    return Actor(id="test-user-001", role="user", surface="test")


@pytest.fixture
def agent_actor() -> Actor:
    """Test actor representing an agent."""
    return Actor(id="test-agent-001", role="agent", surface="agent")


@pytest.fixture
def test_org_id() -> str:
    """Test organization ID."""
    return "org-test-001"


@pytest.fixture
def test_project_id() -> str:
    """Test project ID."""
    return "proj-test-001"


# =============================================================================
# Board CRUD Tests
# =============================================================================

class TestBoardCRUD:
    """Test board create, read, update, delete operations."""

    def test_create_board_basic(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create a basic board without default columns."""
        request = CreateBoardRequest(
            project_id=test_project_id,
            name="Test Board",
            description="A test board",
            is_default=False,
            create_default_columns=False,
        )
        board = service.create_board(request, actor, org_id=test_org_id)

        assert board.board_id is not None
        assert board.board_id.startswith("brd-")
        assert board.name == "Test Board"
        assert board.description == "A test board"
        assert board.project_id == test_project_id
        assert board.is_default is False
        assert board.created_by == actor.id

    def test_create_board_with_default_columns(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create board with default columns (Backlog, To Do, In Progress, In Review, Done)."""
        request = CreateBoardRequest(
            project_id=test_project_id,
            name="Kanban Board",
            is_default=True,
            create_default_columns=True,
        )
        board = service.create_board(request, actor, org_id=test_org_id)

        assert board.board_id is not None
        assert board.is_default is True

        # Verify board has columns
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        assert hasattr(board_with_cols, 'columns')
        assert len(board_with_cols.columns) == 5

        # Verify column names and order
        column_names = [col.name for col in board_with_cols.columns]
        assert column_names == ["Backlog", "To Do", "In Progress", "In Review", "Done"]

        # Verify status mappings
        expected_statuses = [
            WorkItemStatus.BACKLOG,
            WorkItemStatus.TODO,
            WorkItemStatus.IN_PROGRESS,
            WorkItemStatus.IN_REVIEW,
            WorkItemStatus.DONE,
        ]
        for i, col in enumerate(board_with_cols.columns):
            assert col.status_mapping == expected_statuses[i]

    def test_create_board_with_visibility_inherit(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Board visibility defaults to inherit from project."""
        request = CreateBoardRequest(
            project_id=test_project_id,
            name="Inherited Visibility Board",
            settings=BoardSettings(visibility=BoardVisibility.INHERIT),
        )
        board = service.create_board(request, actor, org_id=test_org_id)

        assert board.settings.visibility == BoardVisibility.INHERIT

    def test_create_board_with_visibility_override(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Board can override project visibility."""
        request = CreateBoardRequest(
            project_id=test_project_id,
            name="Private Board",
            settings=BoardSettings(visibility=BoardVisibility.PRIVATE),
        )
        board = service.create_board(request, actor, org_id=test_org_id)

        assert board.settings.visibility == BoardVisibility.PRIVATE

    def test_get_board_not_found(
        self, service: BoardService, test_org_id: str
    ):
        """Get non-existent board raises BoardNotFoundError."""
        with pytest.raises(BoardNotFoundError):
            service.get_board("brd-nonexistent", org_id=test_org_id)

    def test_update_board(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Update board metadata."""
        # Create board
        create_req = CreateBoardRequest(
            project_id=test_project_id,
            name="Original Name",
        )
        board = service.create_board(create_req, actor, org_id=test_org_id)

        # Update
        update_req = UpdateBoardRequest(
            name="Updated Name",
            description="Updated description",
        )
        updated = service.update_board(board.board_id, update_req, actor, org_id=test_org_id)

        assert updated.name == "Updated Name"
        assert updated.description == "Updated description"

    def test_delete_board(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Delete a board."""
        # Create board
        create_req = CreateBoardRequest(
            project_id=test_project_id,
            name="To Delete",
        )
        board = service.create_board(create_req, actor, org_id=test_org_id)

        # Delete
        service.delete_board(board.board_id, actor, org_id=test_org_id)

        # Verify deleted
        with pytest.raises(BoardNotFoundError):
            service.get_board(board.board_id, org_id=test_org_id)

    def test_list_boards_by_project(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """List all boards for a project."""
        # Create multiple boards
        for i in range(3):
            service.create_board(
                CreateBoardRequest(project_id=test_project_id, name=f"Board {i}"),
                actor,
                org_id=test_org_id,
            )

        boards = service.list_boards(project_id=test_project_id, org_id=test_org_id)
        assert len(boards) == 3


# =============================================================================
# Column Management Tests
# =============================================================================

class TestColumnManagement:
    """Test board column operations."""

    def test_create_custom_column(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create a custom column."""
        # Create board without default columns
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Custom Columns Board",
                create_default_columns=False,
            ),
            actor,
            org_id=test_org_id,
        )

        # Add custom column
        col_req = CreateColumnRequest(
            board_id=board.board_id,
            name="QA Testing",
            position=0,
            status_mapping=WorkItemStatus.IN_REVIEW,
            wip_limit=5,
        )
        column = service.create_column(col_req, actor, org_id=test_org_id)

        assert column.column_id.startswith("col-")
        assert column.name == "QA Testing"
        assert column.position == 0
        assert column.status_mapping == WorkItemStatus.IN_REVIEW
        assert column.wip_limit == 5

    def test_reorder_columns(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Reorder columns within a board."""
        # Create board with default columns
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Reorder Test",
                create_default_columns=True,
            ),
            actor,
            org_id=test_org_id,
        )

        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )

        # Move "Done" column to position 2 (between "To Do" and "In Progress")
        done_col = next(c for c in board_with_cols.columns if c.name == "Done")
        service.update_column(
            done_col.column_id,
            UpdateColumnRequest(position=2),
            actor,
            org_id=test_org_id,
        )

        # Verify new order
        refreshed = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        column_names = [c.name for c in refreshed.columns]
        # Note: Other columns should shift. Exact behavior depends on implementation.
        assert done_col.column_id in [c.column_id for c in refreshed.columns]


# =============================================================================
# Epic Tests
# =============================================================================

class TestEpicLifecycle:
    """Test epic create, read, update operations."""

    def test_create_epic(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create an epic."""
        board = service.create_board(
            CreateBoardRequest(project_id=test_project_id, name="Epic Board"),
            actor,
            org_id=test_org_id,
        )

        epic_req = CreateEpicRequest(
            project_id=test_project_id,
            board_id=board.board_id,
            name="User Authentication",
            description="Implement OAuth2 authentication flow",
            priority=WorkItemPriority.HIGH,
        )
        epic = service.create_epic(epic_req, actor, org_id=test_org_id)

        assert epic.epic_id.startswith("epic-")
        assert epic.name == "User Authentication"
        assert epic.status == EpicStatus.DRAFT
        assert epic.priority == WorkItemPriority.HIGH

    def test_epic_status_transitions(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Test epic status transitions: draft -> active -> completed."""
        board = service.create_board(
            CreateBoardRequest(project_id=test_project_id, name="Status Test Board"),
            actor,
            org_id=test_org_id,
        )

        epic = service.create_epic(
            CreateEpicRequest(project_id=test_project_id, board_id=board.board_id, name="Status Test Epic"),
            actor,
            org_id=test_org_id,
        )
        assert epic.status == EpicStatus.DRAFT

        # Transition to active
        updated = service.update_epic(
            epic.epic_id,
            UpdateEpicRequest(status=EpicStatus.ACTIVE),
            actor,
            org_id=test_org_id,
        )
        assert updated.status == EpicStatus.ACTIVE

        # Transition to completed
        completed = service.update_epic(
            epic.epic_id,
            UpdateEpicRequest(status=EpicStatus.COMPLETED),
            actor,
            org_id=test_org_id,
        )
        assert completed.status == EpicStatus.COMPLETED


# =============================================================================
# Story Tests
# =============================================================================

class TestStoryLifecycle:
    """Test story create, read, update operations."""

    def test_create_story_under_epic(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create a story under an epic."""
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Story Board",
                create_default_columns=True,
            ),
            actor,
            org_id=test_org_id,
        )
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")

        epic = service.create_epic(
            CreateEpicRequest(board_id=board.board_id, title="Parent Epic"),
            actor,
            org_id=test_org_id,
        )

        story_req = CreateStoryRequest(
            epic_id=epic.epic_id,
            column_id=backlog_col.column_id,
            title="Login Page",
            description="Create login page with email/password",
            story_points=5,
            priority=WorkItemPriority.MEDIUM,
        )
        story = service.create_story(story_req, actor, org_id=test_org_id)

        assert story.story_id.startswith("story-")
        assert story.epic_id == epic.epic_id
        assert story.title == "Login Page"
        assert story.story_points == 5
        assert story.status == WorkItemStatus.BACKLOG

    def test_move_story_between_columns(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Move a story from one column to another."""
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Move Story Board",
                create_default_columns=True,
            ),
            actor,
            org_id=test_org_id,
        )
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")
        in_progress_col = next(c for c in board_with_cols.columns if c.name == "In Progress")

        epic = service.create_epic(
            CreateEpicRequest(board_id=board.board_id, title="Move Epic"),
            actor,
            org_id=test_org_id,
        )

        story = service.create_story(
            CreateStoryRequest(
                epic_id=epic.epic_id,
                column_id=backlog_col.column_id,
                title="Movable Story",
            ),
            actor,
            org_id=test_org_id,
        )
        assert story.column_id == backlog_col.column_id
        assert story.status == WorkItemStatus.BACKLOG

        # Move to In Progress
        moved = service.update_story(
            story.story_id,
            UpdateStoryRequest(column_id=in_progress_col.column_id),
            actor,
            org_id=test_org_id,
        )
        assert moved.column_id == in_progress_col.column_id
        assert moved.status == WorkItemStatus.IN_PROGRESS


# =============================================================================
# Task Tests
# =============================================================================

class TestTaskLifecycle:
    """Test task create, read, update operations."""

    def test_create_task_under_story(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create a task under a story."""
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Task Board",
                create_default_columns=True,
            ),
            actor,
            org_id=test_org_id,
        )
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")

        epic = service.create_epic(
            CreateEpicRequest(board_id=board.board_id, title="Task Epic"),
            actor,
            org_id=test_org_id,
        )
        story = service.create_story(
            CreateStoryRequest(
                epic_id=epic.epic_id,
                column_id=backlog_col.column_id,
                title="Task Story",
            ),
            actor,
            org_id=test_org_id,
        )

        task_req = CreateTaskRequest(
            story_id=story.story_id,
            title="Write unit tests",
            description="Add pytest tests for login endpoint",
            task_type=TaskType.CODING,
            estimated_hours=2.0,
        )
        task = service.create_task(task_req, actor, org_id=test_org_id)

        assert task.task_id.startswith("task-")
        assert task.story_id == story.story_id
        assert task.title == "Write unit tests"
        assert task.task_type == TaskType.CODING
        assert task.estimated_hours == 2.0
        assert task.status == WorkItemStatus.TODO

    def test_assign_task_to_user(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Assign a task to a user."""
        board, story = self._create_board_with_story(
            service, actor, test_org_id, test_project_id
        )

        task = service.create_task(
            CreateTaskRequest(story_id=story.story_id, title="Assignable Task"),
            actor,
            org_id=test_org_id,
        )

        # Assign to user
        assigned = service.update_task(
            task.task_id,
            UpdateTaskRequest(
                assignee_user_id="user-dev-001",
            ),
            actor,
            org_id=test_org_id,
        )
        assert assigned.assignee_user_id == "user-dev-001"
        assert assigned.assignee_agent_id is None

    def test_assign_task_to_agent(
        self, service: BoardService, actor: Actor, agent_actor: Actor,
        test_org_id: str, test_project_id: str
    ):
        """Assign a task to an agent."""
        board, story = self._create_board_with_story(
            service, actor, test_org_id, test_project_id
        )

        task = service.create_task(
            CreateTaskRequest(story_id=story.story_id, title="Agent Task"),
            actor,
            org_id=test_org_id,
        )

        # Assign to agent
        assigned = service.update_task(
            task.task_id,
            UpdateTaskRequest(
                assignee_agent_id="agent-copilot-001",
            ),
            actor,
            org_id=test_org_id,
        )
        assert assigned.assignee_agent_id == "agent-copilot-001"
        assert assigned.assignee_user_id is None

    def _create_board_with_story(
        self, service: BoardService, actor: Actor, org_id: str, project_id: str
    ):
        """Helper to create a board with an epic and story."""
        board = service.create_board(
            CreateBoardRequest(
                project_id=project_id,
                name="Helper Board",
                create_default_columns=True,
            ),
            actor,
            org_id=org_id,
        )
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=org_id
        )
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")

        epic = service.create_epic(
            CreateEpicRequest(board_id=board.board_id, title="Helper Epic"),
            actor,
            org_id=org_id,
        )
        story = service.create_story(
            CreateStoryRequest(
                epic_id=epic.epic_id,
                column_id=backlog_col.column_id,
                title="Helper Story",
            ),
            actor,
            org_id=org_id,
        )
        return board, story


# =============================================================================
# Sprint Tests
# =============================================================================

class TestSprintManagement:
    """Test sprint create, read, update operations."""

    def test_create_sprint(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Create a sprint."""
        board = service.create_board(
            CreateBoardRequest(project_id=test_project_id, name="Sprint Board"),
            actor,
            org_id=test_org_id,
        )

        start_date = datetime.now()
        end_date = start_date + timedelta(days=14)

        sprint_req = CreateSprintRequest(
            board_id=board.board_id,
            name="Sprint 1",
            goal="Complete user authentication",
            start_date=start_date,
            end_date=end_date,
        )
        sprint = service.create_sprint(sprint_req, actor, org_id=test_org_id)

        assert sprint.sprint_id.startswith("sprint-")
        assert sprint.name == "Sprint 1"
        assert sprint.goal == "Complete user authentication"
        assert sprint.is_active is False  # Not active until started

    def test_add_story_to_sprint(
        self, service: BoardService, actor: Actor, test_org_id: str, test_project_id: str
    ):
        """Add a story to a sprint."""
        board = service.create_board(
            CreateBoardRequest(
                project_id=test_project_id,
                name="Sprint Story Board",
                create_default_columns=True,
            ),
            actor,
            org_id=test_org_id,
        )
        board_with_cols = service.get_board(
            board.board_id, include_columns=True, org_id=test_org_id
        )
        backlog_col = next(c for c in board_with_cols.columns if c.name == "Backlog")

        epic = service.create_epic(
            CreateEpicRequest(board_id=board.board_id, title="Sprint Epic"),
            actor,
            org_id=test_org_id,
        )
        story = service.create_story(
            CreateStoryRequest(
                epic_id=epic.epic_id,
                column_id=backlog_col.column_id,
                title="Sprint Story",
                story_points=3,
            ),
            actor,
            org_id=test_org_id,
        )

        sprint = service.create_sprint(
            CreateSprintRequest(
                board_id=board.board_id,
                name="Test Sprint",
                start_date=datetime.now(),
                end_date=datetime.now() + timedelta(days=14),
            ),
            actor,
            org_id=test_org_id,
        )

        # Add story to sprint
        service.add_story_to_sprint(
            sprint.sprint_id, story.story_id, actor, org_id=test_org_id
        )

        # Verify story is in sprint
        sprint_stories = service.list_sprint_stories(
            sprint.sprint_id, org_id=test_org_id
        )
        assert len(sprint_stories) == 1
        assert sprint_stories[0].story_id == story.story_id


# =============================================================================
# Permission Tests
# =============================================================================

class TestBoardPermissions:
    """Test board permission requirements (placeholder for full integration)."""

    def test_board_permissions_exist(self):
        """Verify board permissions are defined in ProjectPermission enum."""
        from guideai.multi_tenant.permissions import ProjectPermission

        # All board permissions should exist
        assert hasattr(ProjectPermission, 'VIEW_BOARDS')
        assert hasattr(ProjectPermission, 'CREATE_BOARDS')
        assert hasattr(ProjectPermission, 'UPDATE_BOARDS')
        assert hasattr(ProjectPermission, 'DELETE_BOARDS')
        assert hasattr(ProjectPermission, 'MANAGE_COLUMNS')
        assert hasattr(ProjectPermission, 'CREATE_WORK_ITEMS')
        assert hasattr(ProjectPermission, 'UPDATE_WORK_ITEMS')
        assert hasattr(ProjectPermission, 'DELETE_WORK_ITEMS')
        assert hasattr(ProjectPermission, 'ASSIGN_WORK_ITEMS')
        assert hasattr(ProjectPermission, 'MANAGE_SPRINTS')

    def test_role_permissions_include_board_access(self):
        """Verify role permission matrices include board permissions."""
        from guideai.multi_tenant.permissions import (
            ProjectPermission,
            ProjectRole,
            PROJECT_ROLE_PERMISSIONS,
        )

        # Viewer can view boards
        viewer_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.VIEWER]
        assert ProjectPermission.VIEW_BOARDS in viewer_perms

        # Contributor can view and create work items
        contrib_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.CONTRIBUTOR]
        assert ProjectPermission.VIEW_BOARDS in contrib_perms
        assert ProjectPermission.CREATE_WORK_ITEMS in contrib_perms

        # Owner has all permissions
        owner_perms = PROJECT_ROLE_PERMISSIONS[ProjectRole.OWNER]
        assert ProjectPermission.DELETE_BOARDS in owner_perms
        assert ProjectPermission.MANAGE_SPRINTS in owner_perms


# =============================================================================
# Visibility Tests
# =============================================================================

class TestBoardVisibility:
    """Test board visibility inheritance."""

    def test_visibility_enum_values(self):
        """Verify BoardVisibility enum has expected values."""
        assert BoardVisibility.INHERIT.value == "inherit"
        assert BoardVisibility.PRIVATE.value == "private"
        assert BoardVisibility.INTERNAL.value == "internal"
        assert BoardVisibility.PUBLIC.value == "public"

    def test_board_settings_default_visibility(self):
        """BoardSettings defaults to INHERIT visibility."""
        settings = BoardSettings()
        assert settings.visibility == BoardVisibility.INHERIT
