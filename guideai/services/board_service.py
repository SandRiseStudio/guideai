"""
Board Service - Unified WorkItem-based Agile Board management.

Uses a single work_items table with item_type discriminator for epics/stories/tasks.
Provides CRUD for boards, columns, work items, and sprints.

Feature: 13.4.5 (Agent assignment) and 13.5.x (Agile Board System)
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from guideai.multi_tenant.board_contracts import (
    AcceptanceCriterion,
    AssigneeType,
    AssignmentAction,
    AssignmentHistory,
    AssignWorkItemRequest,
    Board,
    BoardColumn,
    BoardEvent,
    BoardEventType,
    BoardSettings,
    BoardVisibility,
    BoardWithColumns,
    ChecklistItem,
    CreateBoardRequest,
    CreateColumnRequest,
    CreateEpicRequest,
    CreateLabelRequest,
    CreateWorkItemRequest,
    CreateStoryRequest,
    CreateTaskRequest,
    DeleteResult,
    Epic,
    EpicStatus,
    Label,
    LabelColor,
    LabelListResponse,
    MoveWorkItemRequest,
    ReorderBoardColumnsRequest,
    ReorderWorkItemsRequest,
    Sprint,
    SprintStory,
    SprintStatus,
    CreateSprintRequest,
    Story,
    Task,
    TaskType,
    UpdateBoardRequest,
    UpdateColumnRequest,
    UpdateEpicRequest,
    UpdateLabelRequest,
    UpdateSprintRequest,
    UpdateStoryRequest,
    UpdateTaskRequest,
    UpdateWorkItemRequest,
    WorkItem,
    WorkItemPriority,
    WorkItemStatus,
    WorkItemType,
    is_valid_status_transition,
)
from guideai.storage.postgres_pool import PostgresPool
from guideai.telemetry import TelemetryClient
from guideai.utils.dsn import resolve_postgres_dsn

logger = logging.getLogger(__name__)

_BOARD_PG_DSN_ENV = "GUIDEAI_BOARD_PG_DSN"
_DEFAULT_PG_DSN = "postgresql://guideai:guideai@localhost:5432/guideai"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _short_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _parse_jsonb(value: Any, default: Any = None) -> Any:
    """Parse JSONB field that may already be decoded by psycopg2."""
    if value is None:
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value) if value else (default if default is not None else {})
    return value


class Actor:
    """Represents the actor performing an operation."""
    def __init__(self, id: str, role: str = "user", surface: str = "api") -> None:
        self.id = id
        self.role = role
        self.surface = surface


def _actor_payload(actor: Actor) -> Dict[str, str]:
    return {"id": actor.id, "role": actor.role, "surface": actor.surface}


# Exceptions
class BoardServiceError(Exception):
    """Base exception for board service."""

class WorkItemTransitionError(BoardServiceError):
    """Invalid status transition."""

class BoardNotFoundError(BoardServiceError):
    """Board not found."""

class WorkItemNotFoundError(BoardServiceError):
    """Work item not found."""


# Backwards-compat exceptions (older API had type-specific not-found errors)
class EpicNotFoundError(WorkItemNotFoundError):
    """Epic not found."""


class StoryNotFoundError(WorkItemNotFoundError):
    """Story not found."""


class TaskNotFoundError(WorkItemNotFoundError):
    """Task not found."""

class ColumnNotFoundError(BoardServiceError):
    """Column not found."""


class ConcurrencyConflictError(BoardServiceError):
    """Optimistic concurrency conflict."""


# Event handler type
BoardEventHandler = Callable[[BoardEvent], None]


class BoardService:
    """Service for managing boards and work items."""

    def __init__(
        self,
        dsn: Optional[str] = None,
        pool: Optional[PostgresPool] = None,
        telemetry: Optional[TelemetryClient] = None,
    ) -> None:
        if pool is None:
            if dsn is None:
                dsn = resolve_postgres_dsn(
                    service="BOARD",
                    explicit_dsn=None,
                    env_var=_BOARD_PG_DSN_ENV,
                    default_dsn=_DEFAULT_PG_DSN,
                )
            pool = PostgresPool(dsn, schema="board")
        self._pool = pool
        self._telemetry = telemetry
        self._event_handlers: List[BoardEventHandler] = []

    def register_event_handler(self, handler: BoardEventHandler) -> None:
        """Register a callback for board events."""
        self._event_handlers.append(handler)

    def _emit_event(self, event: BoardEvent) -> None:
        """Emit event to all registered handlers."""
        for handler in self._event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.warning(f"Event handler error: {e}")

    # =========================================================================
    # Board CRUD
    # =========================================================================

    def create_board(
        self, request: CreateBoardRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> Board:
        timestamp = _now()
        settings = request.settings or BoardSettings()
        board_id_holder: List[str] = []  # Capture generated UUID

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                # Let database generate UUID via gen_random_uuid()
                cur.execute(
                    """
                    INSERT INTO boards (project_id, name, description, settings,
                                       created_at, updated_at, created_by, org_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (request.project_id, request.name, request.description,
                     json.dumps(settings.model_dump()), timestamp, timestamp, actor.id, org_id),
                )
                row = cur.fetchone()
                board_uuid = str(row[0]) if row else None
                if board_uuid:
                    board_id_holder.append(board_uuid)
                    if request.create_default_columns:
                        self._create_default_columns(cur, board_uuid, timestamp)

        self._pool.run_transaction(
            operation="board.create", service_prefix="board",
            actor=_actor_payload(actor), metadata={"board_id": board_id_holder[0] if board_id_holder else "pending"},
            executor=_execute, telemetry=self._telemetry,
        )
        return self.get_board(board_id_holder[0], org_id=org_id)

    def _create_default_columns(self, cur: Any, board_id: str, timestamp: datetime) -> None:
        """Create default columns for a board.

        Args:
            cur: Database cursor
            board_id: UUID string of the board
            timestamp: Creation timestamp
        """
        # Default columns with name, position, optional color
        defaults = [
            ("Backlog", 0, "#6B7280"),
            ("To Do", 1, "#3B82F6"),
            ("In Progress", 2, "#F59E0B"),
            ("In Review", 3, "#8B5CF6"),
            ("Done", 4, "#10B981"),
        ]
        for name, pos, color in defaults:
            # Let database generate UUID via gen_random_uuid()
            cur.execute(
                """INSERT INTO columns (board_id, name, position, color, created_at, updated_at)
                   VALUES (%s::uuid, %s, %s, %s, %s, %s)""",
                (board_id, name, pos, color, timestamp, timestamp),
            )

    def get_board(
        self,
        board_id: str,
        include_columns: bool = False,
        *,
        org_id: Optional[str] = None,
    ) -> Board | BoardWithColumns:
        def _query(conn: Any) -> Optional[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                # Use 'id' column (database schema uses UUID id, not board_id)
                cur.execute("SELECT * FROM boards WHERE id = %s::uuid", (board_id,))
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
            return None

        result = self._pool.run_query(
            operation="board.get", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        if not result:
            raise BoardNotFoundError(f"Board {board_id} not found")
        # Map database 'id' to contract 'board_id'
        board = Board(
            board_id=str(result["id"]), project_id=result["project_id"],
            name=result["name"], description=result["description"],
            settings=BoardSettings(**_parse_jsonb(result["settings"])),
            created_at=result["created_at"], updated_at=result["updated_at"],
            created_by=result["created_by"], is_default=False,  # is_default not in schema, default to False
            org_id=result.get("org_id"),
        )

        if include_columns:
            return self.get_board_with_columns(board_id, org_id=org_id)
        return board

    def get_board_with_columns(self, board_id: str, *, org_id: Optional[str] = None) -> BoardWithColumns:
        board = self.get_board(board_id, include_columns=False, org_id=org_id)
        if isinstance(board, BoardWithColumns):
            return board
        columns = self.list_columns(board_id, org_id=org_id)
        return BoardWithColumns(**board.model_dump(), columns=columns)

    def list_boards(
        self,
        *,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Board]:
        def _query(conn: Any) -> List[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            conditions: list[str] = []
            values: list[Any] = []
            if project_id:
                conditions.append("project_id = %s")
                values.append(project_id)
            where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            values.extend([limit, offset])
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM boards {where_sql} ORDER BY created_at ASC LIMIT %s OFFSET %s",
                    values,
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        results = self._pool.run_query(
            operation="board.list", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        return [
            Board(
                board_id=str(r["id"]),  # Map database 'id' to contract 'board_id'
                project_id=r["project_id"],
                name=r["name"],
                description=r.get("description"),
                settings=BoardSettings(**_parse_jsonb(r.get("settings"))),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
                created_by=r["created_by"],
                is_default=r.get("is_default", False),
                org_id=r.get("org_id"),
            )
            for r in results
        ]

    def update_board(
        self, board_id: str, request: UpdateBoardRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> Board:
        self.get_board(board_id, org_id=org_id)  # Verify exists
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            updates, values = [], []
            if request.name is not None:
                updates.append("name = %s"); values.append(request.name)
            if request.description is not None:
                updates.append("description = %s"); values.append(request.description)
            if request.settings is not None:
                updates.append("settings = %s"); values.append(json.dumps(request.settings.model_dump()))
            # Note: is_default not in database schema, skip
            if not updates:
                return
            updates.append("updated_at = %s"); values.append(timestamp)
            values.append(board_id)
            with conn.cursor() as cur:
                cur.execute(f"UPDATE boards SET {', '.join(updates)} WHERE id = %s::uuid", values)

        self._pool.run_transaction(
            operation="board.update", service_prefix="board",
            actor=_actor_payload(actor), metadata={"board_id": board_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return self.get_board(board_id, org_id=org_id)

    def delete_board(self, board_id: str, actor: Actor, *, org_id: Optional[str] = None) -> DeleteResult:
        self.get_board(board_id, org_id=org_id)

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM boards WHERE id = %s::uuid", (board_id,))

        self._pool.run_transaction(
            operation="board.delete", service_prefix="board",
            actor=_actor_payload(actor), metadata={"board_id": board_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return DeleteResult(deleted_id=board_id, deleted_type="board")

    # =========================================================================
    # Column CRUD
    # =========================================================================

    def create_column(
        self, request: CreateColumnRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> BoardColumn:
        self.get_board(request.board_id, org_id=org_id)
        column_id_holder: List[str] = []  # Capture generated UUID
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                # Let database generate UUID, use 'columns' table
                cur.execute(
                    """INSERT INTO columns (board_id, name, position, wip_limit, created_at, updated_at)
                       VALUES (%s::uuid, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (request.board_id, request.name, request.position,
                     request.wip_limit, timestamp, timestamp),
                )
                row = cur.fetchone()
                if row:
                    column_id_holder.append(str(row[0]))

        self._pool.run_transaction(
            operation="column.create", service_prefix="board",
            actor=_actor_payload(actor), metadata={"column_id": column_id_holder[0] if column_id_holder else "pending"},
            executor=_execute, telemetry=self._telemetry,
        )
        return self.get_column(column_id_holder[0], org_id=org_id)

    def get_column(self, column_id: str, *, org_id: Optional[str] = None) -> BoardColumn:
        def _query(conn: Any) -> Optional[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                # Use 'columns' table and 'id' column
                cur.execute("SELECT * FROM columns WHERE id = %s::uuid", (column_id,))
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
            return None

        result = self._pool.run_query(
            operation="column.get", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        if not result:
            raise ColumnNotFoundError(f"Column {column_id} not found")
        return BoardColumn(
            column_id=str(result["id"]), board_id=str(result["board_id"]),
            name=result["name"], position=result["position"],
            status_mapping=WorkItemStatus.TODO,  # Default, status_mapping not in schema
            wip_limit=result.get("wip_limit"),
            settings={},  # settings not in schema
            created_at=result["created_at"],
            updated_at=result.get("updated_at") or result["created_at"],
        )

    def list_columns(self, board_id: str, *, org_id: Optional[str] = None) -> List[BoardColumn]:
        def _query(conn: Any) -> List[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                # Use 'columns' table (database schema uses 'columns', not 'board_columns')
                cur.execute(
                    "SELECT * FROM columns WHERE board_id = %s::uuid ORDER BY position",
                    (board_id,)
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        results = self._pool.run_query(
            operation="column.list", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        return [
            BoardColumn(
                column_id=str(r["id"]), board_id=str(r["board_id"]),
                name=r["name"], position=r["position"],
                status_mapping=WorkItemStatus.TODO,  # Default, status_mapping not in schema
                wip_limit=r.get("wip_limit"),
                settings={},  # settings not in schema
                created_at=r["created_at"],
                updated_at=r.get("updated_at") or r["created_at"],
            ) for r in results
        ]

    def update_column(
        self, column_id: str, request: UpdateColumnRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> BoardColumn:
        current_col = self.get_column(column_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                # Handle position change with proper reordering to maintain uniqueness
                if request.position is not None and request.position != current_col.position:
                    new_pos = request.position
                    old_pos = current_col.position
                    board_id = current_col.board_id

                    # To avoid unique constraint violations during reordering:
                    # 1. Add a large offset (1000) to all affected positions
                    # 2. Then set the final positions
                    # This ensures no intermediate duplicates

                    if new_pos < old_pos:
                        # Moving up: target gets new_pos, columns in [new_pos, old_pos) shift +1
                        # Step 1: Offset affected columns
                        cur.execute(
                            """UPDATE columns
                               SET position = position + 1000
                               WHERE board_id = %s::uuid AND (id = %s::uuid OR (position >= %s AND position < %s))""",
                            (board_id, column_id, new_pos, old_pos),
                        )
                        # Step 2: Set final positions
                        # Target column goes to new_pos
                        cur.execute(
                            "UPDATE columns SET position = %s, updated_at = %s WHERE id = %s::uuid",
                            (new_pos, timestamp, column_id),
                        )
                        # Shifted columns go to their new positions (original + 1)
                        cur.execute(
                            """UPDATE columns
                               SET position = position - 1000 + 1, updated_at = %s
                               WHERE board_id = %s::uuid AND position >= 1000""",
                            (timestamp, board_id),
                        )
                    else:
                        # Moving down: target gets new_pos, columns in (old_pos, new_pos] shift -1
                        # Step 1: Offset affected columns
                        cur.execute(
                            """UPDATE columns
                               SET position = position + 1000
                               WHERE board_id = %s::uuid AND (id = %s::uuid OR (position > %s AND position <= %s))""",
                            (board_id, column_id, old_pos, new_pos),
                        )
                        # Step 2: Set final positions
                        # Target column goes to new_pos
                        cur.execute(
                            "UPDATE columns SET position = %s, updated_at = %s WHERE id = %s::uuid",
                            (new_pos, timestamp, column_id),
                        )
                        # Shifted columns go to their new positions (original - 1)
                        cur.execute(
                            """UPDATE columns
                               SET position = position - 1000 - 1, updated_at = %s
                               WHERE board_id = %s::uuid AND position >= 1000""",
                            (timestamp, board_id),
                        )

                # Handle other updates (name, wip_limit - status_mapping not in schema)
                updates, values = [], []
                if request.name is not None:
                    updates.append("name = %s"); values.append(request.name)
                # Note: status_mapping not in database schema, skip
                if request.wip_limit is not None:
                    updates.append("wip_limit = %s"); values.append(request.wip_limit)

                if updates:
                    updates.append("updated_at = %s"); values.append(timestamp)
                    where_sql = "id = %s::uuid"
                    where_values: list[Any] = [column_id]
                    if request.expected_updated_at is not None:
                        where_sql += " AND updated_at = %s"
                        where_values.append(request.expected_updated_at)
                    cur.execute(
                        f"UPDATE columns SET {', '.join(updates)} WHERE {where_sql}",
                        values + where_values,
                    )
                    if request.expected_updated_at is not None and cur.rowcount == 0:
                        raise ConcurrencyConflictError(
                            f"Column {column_id} updated_at did not match expected_updated_at"
                        )

        self._pool.run_transaction(
            operation="column.update", service_prefix="board",
            actor=_actor_payload(actor), metadata={"column_id": column_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return self.get_column(column_id, org_id=org_id)

    # =========================================================================
    # Drag & drop (move / reorder)
    # =========================================================================

    def move_work_item(
        self, item_id: str, request: MoveWorkItemRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> WorkItem:
        """Move a work item between columns and/or change its position."""
        item = self.get_work_item(item_id, org_id=org_id)
        if item.board_id is None:
            raise BoardServiceError(f"Work item {item_id} has no board_id")

        from_column_id = item.column_id
        to_column_id = request.column_id if request.column_id is not None else item.column_id
        if to_column_id is None:
            raise BoardServiceError(f"Work item {item_id} has no column_id")

        requested_position = max(0, int(request.position))
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                # Normalize target position to end-of-column
                cur.execute(
                    """SELECT COALESCE(MAX(position), -1) + 1
                       FROM work_items
                       WHERE board_id = %s AND column_id = %s AND id <> %s""",
                    (item.board_id, to_column_id, item_id),
                )
                (max_plus_one,) = cur.fetchone()
                target_position = min(requested_position, int(max_plus_one))

                if from_column_id == to_column_id:
                    # Close gap at old position
                    cur.execute(
                        """UPDATE work_items
                           SET position = position - 1
                           WHERE board_id = %s AND column_id = %s AND position > %s""",
                        (item.board_id, to_column_id, item.position),
                    )
                    # Make room at new position
                    cur.execute(
                        """UPDATE work_items
                           SET position = position + 1
                           WHERE board_id = %s AND column_id = %s AND position >= %s AND id <> %s""",
                        (item.board_id, to_column_id, target_position, item_id),
                    )
                    cur.execute(
                        """UPDATE work_items
                           SET position = %s, updated_at = %s
                           WHERE id = %s""",
                        (target_position, timestamp, item_id),
                    )
                else:
                    if from_column_id is not None:
                        # Close gap in source column
                        cur.execute(
                            """UPDATE work_items
                               SET position = position - 1
                               WHERE board_id = %s AND column_id = %s AND position > %s""",
                            (item.board_id, from_column_id, item.position),
                        )
                    # Make room in destination column
                    cur.execute(
                        """UPDATE work_items
                           SET position = position + 1
                           WHERE board_id = %s AND column_id = %s AND position >= %s""",
                        (item.board_id, to_column_id, target_position),
                    )
                    cur.execute(
                        """UPDATE work_items
                           SET column_id = %s, position = %s, updated_at = %s
                           WHERE id = %s""",
                        (to_column_id, target_position, timestamp, item_id),
                    )

                # Update column versions last (optimistic concurrency guard)
                if from_column_id is not None:
                    if request.expected_from_column_updated_at is None:
                        cur.execute(
                            "UPDATE columns SET updated_at = %s WHERE id = %s",
                            (timestamp, from_column_id),
                        )
                    else:
                        cur.execute(
                            """UPDATE columns SET updated_at = %s
                               WHERE id = %s AND updated_at = %s""",
                            (timestamp, from_column_id, request.expected_from_column_updated_at),
                        )
                        if cur.rowcount == 0:
                            raise ConcurrencyConflictError(
                                f"Source column {from_column_id} updated_at did not match expected"
                            )

                if to_column_id is not None and to_column_id != from_column_id:
                    if request.expected_to_column_updated_at is None:
                        cur.execute(
                            "UPDATE columns SET updated_at = %s WHERE id = %s",
                            (timestamp, to_column_id),
                        )
                    else:
                        cur.execute(
                            """UPDATE columns SET updated_at = %s
                               WHERE id = %s AND updated_at = %s""",
                            (timestamp, to_column_id, request.expected_to_column_updated_at),
                        )
                        if cur.rowcount == 0:
                            raise ConcurrencyConflictError(
                                f"Destination column {to_column_id} updated_at did not match expected"
                            )

        self._pool.run_transaction(
            operation="work_item.move",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"item_id": item_id, "from_column_id": from_column_id, "to_column_id": to_column_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

        moved = self.get_work_item(item_id, org_id=org_id)
        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_MOVED,
            board_id=moved.board_id, item_id=item_id, item_type=moved.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=timestamp,
            payload={"from_column_id": from_column_id, "to_column_id": to_column_id, "position": moved.position},
            org_id=org_id,
        ))
        return moved

    def reorder_work_items(
        self, request: ReorderWorkItemsRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> None:
        """Reorder all work items within a single column."""
        column = self.get_column(request.column_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id FROM work_items
                       WHERE board_id = %s AND column_id = %s""",
                    (column.board_id, request.column_id),
                )
                existing_ids = [r[0] for r in cur.fetchall()]
                if set(existing_ids) != set(request.ordered_item_ids):
                    raise BoardServiceError("ordered_item_ids must match items in the column")

                case_parts: list[str] = []
                values: list[Any] = []
                for idx, item_id in enumerate(request.ordered_item_ids):
                    case_parts.append("WHEN %s THEN %s")
                    values.extend([item_id, idx])

                values.extend([timestamp, column.board_id, request.column_id])
                cur.execute(
                    f"""UPDATE work_items
                        SET position = CASE id {' '.join(case_parts)} END,
                            updated_at = %s
                        WHERE board_id = %s AND column_id = %s""",
                    values,
                )

                if request.expected_column_updated_at is None:
                    cur.execute(
                        "UPDATE columns SET updated_at = %s WHERE id = %s",
                        (timestamp, request.column_id),
                    )
                else:
                    cur.execute(
                        """UPDATE columns SET updated_at = %s
                           WHERE id = %s AND updated_at = %s""",
                        (timestamp, request.column_id, request.expected_column_updated_at),
                    )
                    if cur.rowcount == 0:
                        raise ConcurrencyConflictError(
                            f"Column {request.column_id} updated_at did not match expected"
                        )

        self._pool.run_transaction(
            operation="work_item.reorder",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"column_id": request.column_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

    def reorder_columns(
        self, board_id: str, request: ReorderBoardColumnsRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> None:
        """Reorder columns within a board."""
        self.get_board(board_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM columns WHERE board_id = %s",
                    (board_id,),
                )
                existing_ids = [str(r[0]) for r in cur.fetchall()]
                if set(existing_ids) != set(request.ordered_column_ids):
                    raise BoardServiceError("ordered_column_ids must match columns in the board")

                case_parts: list[str] = []
                values: list[Any] = []
                for idx, col_id in enumerate(request.ordered_column_ids):
                    case_parts.append("WHEN %s THEN %s")
                    values.extend([col_id, idx])

                # Postgres enforces UNIQUE constraints row-by-row during UPDATE.
                # Swapping positions in-place can raise UniqueViolation on
                # (board_id, position). Use a two-step update:
                # 1) shift all positions into a temporary range (preserves uniqueness)
                # 2) assign final positions.
                cur.execute(
                    "SELECT COALESCE(MAX(position), 0) FROM columns WHERE board_id = %s",
                    (board_id,),
                )
                max_position = int(cur.fetchone()[0] or 0)
                temp_offset = max_position + len(existing_ids) + 1
                cur.execute(
                    "UPDATE columns SET position = position + %s WHERE board_id = %s",
                    (temp_offset, board_id),
                )

                values.append(board_id)
                cur.execute(
                    f"""UPDATE columns
                        SET position = CASE id {' '.join(case_parts)} END
                        WHERE board_id = %s""",
                    values,
                )

                if request.expected_columns_updated_at:
                    for col_id, expected in request.expected_columns_updated_at.items():
                        cur.execute(
                            """UPDATE columns SET updated_at = %s
                               WHERE id = %s AND updated_at = %s""",
                            (timestamp, col_id, expected),
                        )
                        if cur.rowcount == 0:
                            raise ConcurrencyConflictError(
                                f"Column {col_id} updated_at did not match expected"
                            )
                else:
                    cur.execute(
                        "UPDATE columns SET updated_at = %s WHERE board_id = %s",
                        (timestamp, board_id),
                    )

        self._pool.run_transaction(
            operation="column.reorder",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"board_id": board_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

    def delete_column(self, column_id: str, actor: Actor, *, org_id: Optional[str] = None) -> DeleteResult:
        self.get_column(column_id, org_id=org_id)

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM columns WHERE id = %s", (column_id,))

        self._pool.run_transaction(
            operation="column.delete", service_prefix="board",
            actor=_actor_payload(actor), metadata={"column_id": column_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return DeleteResult(deleted_id=column_id, deleted_type="column")

    # =========================================================================
    # WorkItem CRUD (unified for epic/story/task)
    # =========================================================================

    def create_work_item(
        self, request: CreateWorkItemRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> WorkItem:
        """Create a work item (epic, story, or task)."""
        timestamp = _now()

        # Default status to preserve legacy expectations.
        initial_status = WorkItemStatus.BACKLOG
        if request.item_type == WorkItemType.EPIC:
            initial_status = WorkItemStatus.DRAFT
        elif request.item_type == WorkItemType.TASK:
            initial_status = WorkItemStatus.TODO

        # Convert acceptance criteria strings to objects
        criteria = [
            AcceptanceCriterion(id=_short_id("ac"), description=c, is_met=False)
            for c in request.acceptance_criteria
        ]
        checklist = [
            ChecklistItem(id=_short_id("cl"), description=c, is_done=False)
            for c in request.checklist
        ]

        def _execute(conn: Any) -> str:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            # Map priority enum to integer (critical=4, high=3, medium=2, low=1)
            priority_map = {"critical": 4, "high": 3, "medium": 2, "low": 1}
            priority_int = priority_map.get(request.priority.value, 2)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO work_items (
                        item_type, board_id, column_id,
                        title, description, status, priority, position,
                        labels, metadata,
                        created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id
                    """,
                    (
                        request.item_type.value,
                        request.board_id, request.column_id,
                        request.title, request.description,
                        initial_status.value, priority_int, 0,
                        request.labels,  # Postgres array, not JSON
                        json.dumps(request.metadata),
                        timestamp, timestamp,
                    ),
                )
                row = cur.fetchone()
                return str(row[0]) if row else ""

        item_id = self._pool.run_transaction(
            operation="work_item.create", service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"item_type": request.item_type.value},
            executor=_execute, telemetry=self._telemetry,
        )

        item = self.get_work_item(item_id, org_id=org_id)
        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_CREATED,
            board_id=request.board_id, item_id=item_id, item_type=request.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=timestamp,
            payload={"title": request.title}, org_id=org_id,
        ))
        return item

    def get_work_item(self, item_id: str, *, org_id: Optional[str] = None) -> WorkItem:
        """Get a work item by ID."""
        def _query(conn: Any) -> Optional[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM work_items WHERE id = %s", (item_id,))
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
            return None

        result = self._pool.run_query(
            operation="work_item.get", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        if not result:
            raise WorkItemNotFoundError(f"Work item {item_id} not found")
        return self._row_to_work_item(result)

    def _row_to_work_item(self, row: Dict) -> WorkItem:
        """Convert a database row to a WorkItem."""
        # Map priority integer back to enum (4=critical, 3=high, 2=medium, 1=low)
        priority_int = row.get("priority", 2)
        priority_reverse_map = {4: "critical", 3: "high", 2: "medium", 1: "low"}
        priority_str = priority_reverse_map.get(priority_int, "medium")

        return WorkItem(
            item_id=str(row["id"]),  # Map UUID id to item_id for contract
            item_type=WorkItemType(row["item_type"]),
            project_id=str(row["project_id"]) if row.get("project_id") else None,
            board_id=str(row["board_id"]) if row.get("board_id") else None,
            column_id=str(row["column_id"]) if row.get("column_id") else None,
            parent_id=str(row["parent_id"]) if row.get("parent_id") else None,
            title=row["title"],
            description=row.get("description"),
            status=WorkItemStatus(row["status"]),
            priority=WorkItemPriority(priority_str),
            position=row.get("position", 0),
            story_points=row.get("story_points"),
            estimated_hours=row.get("estimated_hours"),
            actual_hours=row.get("actual_hours"),
            assignee_id=row.get("assignee_id"),
            assignee_type=AssigneeType(row["assignee_type"]) if row.get("assignee_type") else None,
            assigned_at=row.get("assigned_at"),
            assigned_by=row.get("assigned_by"),
            start_date=row.get("start_date"),
            target_date=row.get("target_date"),
            due_date=row.get("due_date"),
            started_at=row.get("started_at"),
            completed_at=row.get("completed_at"),
            color=row.get("color"),
            labels=_parse_jsonb(row.get("labels"), []),
            acceptance_criteria=[
                AcceptanceCriterion(**c) for c in _parse_jsonb(row.get("acceptance_criteria"), [])
            ],
            checklist=[
                ChecklistItem(**c) for c in _parse_jsonb(row.get("checklist"), [])
            ],
            attachments=[],  # TODO: parse attachments
            behavior_id=row.get("behavior_id"),
            run_id=str(row["run_id"]) if row.get("run_id") else None,
            metadata=_parse_jsonb(row.get("metadata"), {}),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=row.get("created_by") or "system",  # Default to system if not set
            org_id=row.get("org_id"),
        )

    def update_work_item(
        self, item_id: str, request: UpdateWorkItemRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> WorkItem:
        """Update a work item."""
        item = self.get_work_item(item_id, org_id=org_id)

        # Validate status transition
        if request.status and not is_valid_status_transition(item.status, request.status):
            raise WorkItemTransitionError(
                f"Invalid status transition: {item.status} -> {request.status}"
            )
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            updates, values = [], []

            if request.title is not None:
                updates.append("title = %s"); values.append(request.title)
            if request.description is not None:
                updates.append("description = %s"); values.append(request.description)
            if request.status is not None:
                updates.append("status = %s"); values.append(request.status.value)
            if request.priority is not None:
                updates.append("priority = %s"); values.append(request.priority.value)
            if request.board_id is not None:
                updates.append("board_id = %s"); values.append(request.board_id)
            if request.column_id is not None:
                updates.append("column_id = %s"); values.append(request.column_id)
            if request.parent_id is not None:
                updates.append("parent_id = %s"); values.append(request.parent_id)
            if request.position is not None:
                updates.append("position = %s"); values.append(request.position)
            if request.story_points is not None:
                updates.append("story_points = %s"); values.append(request.story_points)
            if request.estimated_hours is not None:
                updates.append("estimated_hours = %s"); values.append(float(request.estimated_hours))
            if request.actual_hours is not None:
                updates.append("actual_hours = %s"); values.append(float(request.actual_hours))
            if request.start_date is not None:
                updates.append("start_date = %s"); values.append(request.start_date)
            if request.target_date is not None:
                updates.append("target_date = %s"); values.append(request.target_date)
            if request.due_date is not None:
                updates.append("due_date = %s"); values.append(request.due_date)
            if request.color is not None:
                updates.append("color = %s"); values.append(request.color)
            if request.labels is not None:
                updates.append("labels = %s"); values.append(json.dumps(request.labels))
            if request.acceptance_criteria is not None:
                updates.append("acceptance_criteria = %s")
                values.append(json.dumps([c.model_dump() for c in request.acceptance_criteria]))
            if request.checklist is not None:
                updates.append("checklist = %s")
                values.append(json.dumps([c.model_dump() for c in request.checklist]))
            if request.behavior_id is not None:
                updates.append("behavior_id = %s"); values.append(request.behavior_id)
            if request.run_id is not None:
                updates.append("run_id = %s"); values.append(request.run_id)
            if request.metadata is not None:
                updates.append("metadata = %s"); values.append(json.dumps(request.metadata))

            if not updates:
                return
            updates.append("updated_at = %s"); values.append(timestamp)
            values.append(item_id)

            with conn.cursor() as cur:
                cur.execute(f"UPDATE work_items SET {', '.join(updates)} WHERE id = %s", values)

        self._pool.run_transaction(
            operation="work_item.update", service_prefix="board",
            actor=_actor_payload(actor), metadata={"item_id": item_id},
            executor=_execute, telemetry=self._telemetry,
        )

        updated = self.get_work_item(item_id, org_id=org_id)
        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_UPDATED,
            board_id=updated.board_id, item_id=item_id, item_type=updated.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=timestamp,
            payload={}, org_id=org_id,
        ))
        return updated

    def delete_work_item(
        self, item_id: str, actor: Actor, *, org_id: Optional[str] = None, cascade: bool = True
    ) -> DeleteResult:
        """Delete a work item and optionally cascade to children."""
        item = self.get_work_item(item_id, org_id=org_id)
        deleted_children: List[str] = []

        def _execute(conn: Any) -> None:
            nonlocal deleted_children
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                if cascade:
                    # Find and delete children
                    cur.execute("SELECT id FROM work_items WHERE parent_id = %s", (item_id,))
                    deleted_children = [str(r[0]) for r in cur.fetchall()]
                    if deleted_children:
                        cur.execute("DELETE FROM work_items WHERE parent_id = %s", (item_id,))
                cur.execute("DELETE FROM work_items WHERE id = %s", (item_id,))

        self._pool.run_transaction(
            operation="work_item.delete", service_prefix="board",
            actor=_actor_payload(actor), metadata={"item_id": item_id},
            executor=_execute, telemetry=self._telemetry,
        )

        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_DELETED,
            board_id=item.board_id, item_id=item_id, item_type=item.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=_now(),
            payload={"cascade_deleted": deleted_children}, org_id=org_id,
        ))
        return DeleteResult(deleted_id=item_id, deleted_type=item.item_type.value, cascade_deleted=deleted_children)

    def list_work_items(
        self,
        *,
        project_id: Optional[str] = None,
        board_id: Optional[str] = None,
        item_type: Optional[WorkItemType] = None,
        parent_id: Optional[str] = None,
        status: Optional[WorkItemStatus] = None,
        assignee_id: Optional[str] = None,
        labels: Optional[List[str]] = None,
        sprint_id: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[WorkItem]:
        """
        List work items with filters.

        Args:
            labels: Filter by labels (any of - items with at least one matching label).
                   Uses PostgreSQL JSONB ?| operator for efficient GIN index queries.
            sprint_id: Filter by sprint (items assigned to this sprint).
        """
        def _query(conn: Any) -> List[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            conditions, values = [], []

            if project_id:
                conditions.append("project_id = %s"); values.append(project_id)
            if board_id:
                conditions.append("board_id = %s"); values.append(board_id)
            if item_type:
                conditions.append("item_type = %s"); values.append(item_type.value)
            if parent_id:
                conditions.append("parent_id = %s"); values.append(parent_id)
            if status:
                conditions.append("status = %s"); values.append(status.value)
            if assignee_id:
                conditions.append("assignee_id = %s"); values.append(assignee_id)
            if labels:
                # Use ?| operator for "any of" matching (uses GIN index)
                conditions.append("labels ?| %s"); values.append(labels)
            if sprint_id:
                conditions.append("sprint_id = %s"); values.append(sprint_id)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            values.extend([limit, offset])

            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM work_items {where} ORDER BY position, created_at LIMIT %s OFFSET %s",
                    values
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        results = self._pool.run_query(
            operation="work_item.list", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        return [self._row_to_work_item(r) for r in results]

    # =========================================================================
    # Assignment
    # =========================================================================

    def assign_work_item(
        self, item_id: str, request: AssignWorkItemRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> WorkItem:
        """Assign a work item to a user or agent."""
        item = self.get_work_item(item_id, org_id=org_id)
        timestamp = _now()
        previous_assignee = item.assignee_id
        previous_type = item.assignee_type

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE work_items SET assignee_id = %s, assignee_type = %s,
                       assigned_at = %s, assigned_by = %s, updated_at = %s WHERE id = %s""",
                    (request.assignee_id, request.assignee_type.value, timestamp, actor.id, timestamp, item_id),
                )
                # Record history
                cur.execute(
                    """INSERT INTO assignment_history
                       (history_id, project_id, assignable_id, assignable_type, assignee_id, assignee_type,
                        action, performed_by, performed_at, previous_assignee_id, previous_assignee_type, reason, org_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (_short_id("ahist"), item.project_id, item_id, item.item_type.value,
                     request.assignee_id, request.assignee_type.value,
                     AssignmentAction.REASSIGNED.value if previous_assignee else AssignmentAction.ASSIGNED.value,
                     actor.id, timestamp, previous_assignee, previous_type.value if previous_type else None,
                     request.reason, org_id),
                )

        self._pool.run_transaction(
            operation="work_item.assign", service_prefix="board",
            actor=_actor_payload(actor), metadata={"item_id": item_id},
            executor=_execute, telemetry=self._telemetry,
        )

        updated = self.get_work_item(item_id, org_id=org_id)
        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_ASSIGNED,
            board_id=updated.board_id, item_id=item_id, item_type=updated.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=timestamp,
            payload={"assignee_id": request.assignee_id, "assignee_type": request.assignee_type.value},
            org_id=org_id,
        ))
        return updated

    def unassign_work_item(
        self, item_id: str, actor: Actor, *, reason: Optional[str] = None, org_id: Optional[str] = None
    ) -> WorkItem:
        """Unassign a work item."""
        item = self.get_work_item(item_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE work_items SET assignee_id = NULL, assignee_type = NULL,
                       assigned_at = NULL, assigned_by = NULL, updated_at = %s WHERE id = %s""",
                    (timestamp, item_id),
                )
                if item.assignee_id:
                    cur.execute(
                        """INSERT INTO assignment_history
                           (history_id, project_id, assignable_id, assignable_type, assignee_id, assignee_type,
                            action, performed_by, performed_at, previous_assignee_id, previous_assignee_type, reason, org_id)
                           VALUES (%s, %s, %s, %s, NULL, NULL, %s, %s, %s, %s, %s, %s, %s)""",
                        (_short_id("ahist"), item.project_id, item_id, item.item_type.value,
                         AssignmentAction.UNASSIGNED.value, actor.id, timestamp,
                         item.assignee_id, item.assignee_type.value if item.assignee_type else None,
                         reason, org_id),
                    )

        self._pool.run_transaction(
            operation="work_item.unassign", service_prefix="board",
            actor=_actor_payload(actor), metadata={"item_id": item_id},
            executor=_execute, telemetry=self._telemetry,
        )

        updated = self.get_work_item(item_id, org_id=org_id)
        self._emit_event(BoardEvent(
            event_id=_short_id("evt"), event_type=BoardEventType.ITEM_UNASSIGNED,
            board_id=updated.board_id, item_id=item_id, item_type=updated.item_type,
            actor_id=actor.id, actor_type=actor.role, timestamp=timestamp,
            payload={}, org_id=org_id,
        ))
        return updated

    # =========================================================================
    # Sprint CRUD
    # =========================================================================

    def create_sprint(
        self, request: CreateSprintRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> Sprint:
        timestamp = _now()
        sprint_id: Optional[str] = None

        def _execute(conn: Any) -> None:
            nonlocal sprint_id
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO sprints (board_id, name, goal, status,
                       start_date, end_date, created_at, updated_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                       RETURNING id""",
                    (request.board_id, request.name,
                     request.goal, SprintStatus.PLANNING.value, request.start_date,
                     request.end_date, timestamp, timestamp),
                )
                result = cur.fetchone()
                if result:
                    sprint_id = str(result[0])

        self._pool.run_transaction(
            operation="sprint.create", service_prefix="board",
            actor=_actor_payload(actor), metadata={},
            executor=_execute, telemetry=self._telemetry,
        )
        if not sprint_id:
            raise BoardServiceError("Failed to create sprint")
        return self.get_sprint(sprint_id, org_id=org_id)

    def get_sprint(self, sprint_id: str, *, org_id: Optional[str] = None) -> Sprint:
        def _query(conn: Any) -> Optional[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM sprints WHERE id = %s", (sprint_id,))
                row = cur.fetchone()
                if row:
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, row))
            return None

        result = self._pool.run_query(
            operation="sprint.get", service_prefix="board", executor=_query, telemetry=self._telemetry
        )
        if not result:
            raise BoardServiceError(f"Sprint {sprint_id} not found")
        return Sprint(
            sprint_id=str(result["id"]), project_id=None,
            board_id=str(result["board_id"]), name=result["name"], goal=result.get("goal"),
            status=SprintStatus(result["status"].strip("'") if result["status"] else "planning"),
            start_date=result.get("start_date"), end_date=result.get("end_date"),
            velocity_planned=None,
            velocity_completed=None,
            metadata={},
            created_at=result["created_at"], updated_at=result["updated_at"],
            created_by=None, org_id=org_id,
        )

    def update_sprint(
        self, sprint_id: str, request: UpdateSprintRequest, actor: Actor, *, org_id: Optional[str] = None
    ) -> Sprint:
        self.get_sprint(sprint_id, org_id=org_id)
        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            updates, values = [], []
            if request.name is not None:
                updates.append("name = %s"); values.append(request.name)
            if request.goal is not None:
                updates.append("goal = %s"); values.append(request.goal)
            if request.status is not None:
                updates.append("status = %s"); values.append(request.status.value)
            if request.start_date is not None:
                updates.append("start_date = %s"); values.append(request.start_date)
            if request.end_date is not None:
                updates.append("end_date = %s"); values.append(request.end_date)
            # Note: velocity_planned not in current DB schema
            if not updates:
                return
            updates.append("updated_at = %s"); values.append(timestamp)
            values.append(sprint_id)
            with conn.cursor() as cur:
                cur.execute(f"UPDATE sprints SET {', '.join(updates)} WHERE id = %s", values)

        self._pool.run_transaction(
            operation="sprint.update", service_prefix="board",
            actor=_actor_payload(actor), metadata={"sprint_id": sprint_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return self.get_sprint(sprint_id, org_id=org_id)

    def delete_sprint(self, sprint_id: str, actor: Actor, *, org_id: Optional[str] = None) -> DeleteResult:
        self.get_sprint(sprint_id, org_id=org_id)

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM sprints WHERE id = %s", (sprint_id,))

        self._pool.run_transaction(
            operation="sprint.delete", service_prefix="board",
            actor=_actor_payload(actor), metadata={"sprint_id": sprint_id},
            executor=_execute, telemetry=self._telemetry,
        )
        return DeleteResult(deleted_id=sprint_id, deleted_type="sprint")

    # =========================================================================
    # Legacy API shims (epic/story/task + sprint membership)
    # =========================================================================

    def _epic_status_from_work_item(self, status: WorkItemStatus) -> EpicStatus:
        if status == WorkItemStatus.DRAFT:
            return EpicStatus.DRAFT
        if status == WorkItemStatus.DONE:
            return EpicStatus.COMPLETED
        return EpicStatus.ACTIVE

    def _work_item_status_from_epic(self, status: EpicStatus) -> WorkItemStatus:
        if status == EpicStatus.DRAFT:
            return WorkItemStatus.DRAFT
        if status == EpicStatus.COMPLETED:
            return WorkItemStatus.DONE
        return WorkItemStatus.IN_PROGRESS

    def _legacy_epic_from_work_item(self, item: WorkItem) -> Epic:
        return Epic(
            epic_id=item.item_id,
            project_id=item.project_id,
            board_id=item.board_id,
            name=item.title,
            description=item.description,
            status=self._epic_status_from_work_item(item.status),
            priority=item.priority,
            story_points=item.story_points,
            color=item.color,
            labels=list(item.labels or []),
            created_at=item.created_at,
            updated_at=item.updated_at,
            created_by=item.created_by,
            org_id=item.org_id,
        )

    def _legacy_story_from_work_item(self, item: WorkItem) -> Story:
        return Story(
            story_id=item.item_id,
            project_id=item.project_id,
            board_id=item.board_id,
            epic_id=item.parent_id,
            column_id=item.column_id,
            title=item.title,
            description=item.description,
            status=item.status,
            priority=item.priority,
            story_points=item.story_points,
            labels=list(item.labels or []),
            created_at=item.created_at,
            updated_at=item.updated_at,
            created_by=item.created_by,
            org_id=item.org_id,
        )

    def _legacy_task_from_work_item(self, item: WorkItem) -> Task:
        task_type_value = (item.metadata or {}).get("task_type")
        task_type: TaskType | None = None
        if isinstance(task_type_value, str):
            try:
                task_type = TaskType(task_type_value)
            except Exception:
                task_type = None

        assignee_user_id: str | None = None
        assignee_agent_id: str | None = None
        if item.assignee_id and item.assignee_type:
            if item.assignee_type == AssigneeType.USER:
                assignee_user_id = item.assignee_id
            elif item.assignee_type == AssigneeType.AGENT:
                assignee_agent_id = item.assignee_id

        return Task(
            task_id=item.item_id,
            project_id=item.project_id,
            board_id=item.board_id,
            story_id=item.parent_id,
            column_id=item.column_id,
            title=item.title,
            description=item.description,
            status=item.status,
            priority=item.priority,
            task_type=task_type,
            estimated_hours=item.estimated_hours,
            actual_hours=item.actual_hours,
            assignee_user_id=assignee_user_id,
            assignee_agent_id=assignee_agent_id,
            labels=list(item.labels or []),
            behavior_id=item.behavior_id,
            run_id=item.run_id,
            created_at=item.created_at,
            updated_at=item.updated_at,
            created_by=item.created_by,
            org_id=item.org_id,
        )

    def _require_project_id(self, *, project_id: Optional[str], board_id: Optional[str], org_id: Optional[str]) -> str:
        if project_id:
            return project_id
        if board_id:
            board = self.get_board(board_id, include_columns=False, org_id=org_id)
            if isinstance(board, BoardWithColumns):
                return board.project_id
            return board.project_id
        raise BoardServiceError("project_id is required when board_id is not provided")

    def create_epic(self, request: CreateEpicRequest, actor: Actor, *, org_id: Optional[str] = None) -> Epic:
        project_id = self._require_project_id(
            project_id=getattr(request, "project_id", None),
            board_id=getattr(request, "board_id", None),
            org_id=org_id,
        )
        title = getattr(request, "title", None) or getattr(request, "name", None)
        if not title:
            raise BoardServiceError("Epic title/name is required")

        unified = CreateWorkItemRequest(
            item_type=WorkItemType.EPIC,
            project_id=project_id,
            board_id=getattr(request, "board_id", None),
            column_id=None,
            parent_id=None,
            title=title,
            description=getattr(request, "description", None),
            priority=getattr(request, "priority", WorkItemPriority.MEDIUM),
            story_points=getattr(request, "story_points", None),
            color=getattr(request, "color", None),
            labels=list(getattr(request, "labels", []) or []),
            metadata=dict(getattr(request, "metadata", {}) or {}),
        )
        created = self.create_work_item(unified, actor, org_id=org_id)
        return self._legacy_epic_from_work_item(created)

    def update_epic(
        self,
        epic_id: str,
        request: UpdateEpicRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Epic:
        item = self.get_work_item(epic_id, org_id=org_id)
        if item.item_type != WorkItemType.EPIC:
            raise EpicNotFoundError(f"Epic {epic_id} not found")

        title = request.title or request.name
        new_status: WorkItemStatus | None = None
        if request.status is not None:
            new_status = self._work_item_status_from_epic(request.status)

        unified = UpdateWorkItemRequest(
            title=title,
            description=request.description,
            status=new_status,
            priority=request.priority,
            story_points=request.story_points,
            color=request.color,
            labels=request.labels,
            metadata=request.metadata,
        )
        updated = self.update_work_item(epic_id, unified, actor, org_id=org_id)
        return self._legacy_epic_from_work_item(updated)

    def create_story(self, request: CreateStoryRequest, actor: Actor, *, org_id: Optional[str] = None) -> Story:
        if not request.epic_id:
            raise BoardServiceError("epic_id is required")
        epic = self.get_work_item(request.epic_id, org_id=org_id)
        if epic.item_type != WorkItemType.EPIC:
            raise EpicNotFoundError(f"Epic {request.epic_id} not found")

        project_id = request.project_id or epic.project_id
        board_id = request.board_id or epic.board_id

        unified = CreateWorkItemRequest(
            item_type=WorkItemType.STORY,
            project_id=project_id,
            board_id=board_id,
            column_id=request.column_id,
            parent_id=request.epic_id,
            title=request.title,
            description=request.description,
            priority=request.priority,
            story_points=request.story_points,
            labels=list(request.labels or []),
            metadata=dict(request.metadata or {}),
        )
        created = self.create_work_item(unified, actor, org_id=org_id)
        return self._legacy_story_from_work_item(created)

    def update_story(
        self,
        story_id: str,
        request: UpdateStoryRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Story:
        item = self.get_work_item(story_id, org_id=org_id)
        if item.item_type != WorkItemType.STORY:
            raise StoryNotFoundError(f"Story {story_id} not found")

        new_status = request.status
        if request.column_id is not None and request.status is None:
            col = self.get_column(request.column_id, org_id=org_id)
            new_status = col.status_mapping

        unified = UpdateWorkItemRequest(
            title=request.title,
            description=request.description,
            column_id=request.column_id,
            status=new_status,
            story_points=request.story_points,
            priority=request.priority,
            labels=request.labels,
            metadata=request.metadata,
        )
        updated = self.update_work_item(story_id, unified, actor, org_id=org_id)
        return self._legacy_story_from_work_item(updated)

    def create_task(self, request: CreateTaskRequest, actor: Actor, *, org_id: Optional[str] = None) -> Task:
        if not request.story_id:
            raise BoardServiceError("story_id is required")
        story = self.get_work_item(request.story_id, org_id=org_id)
        if story.item_type != WorkItemType.STORY:
            raise StoryNotFoundError(f"Story {request.story_id} not found")

        project_id = request.project_id or story.project_id
        board_id = request.board_id or story.board_id

        metadata = dict(request.metadata or {})
        if request.task_type is not None:
            metadata["task_type"] = request.task_type.value

        unified = CreateWorkItemRequest(
            item_type=WorkItemType.TASK,
            project_id=project_id,
            board_id=board_id,
            column_id=request.column_id,
            parent_id=request.story_id,
            title=request.title,
            description=request.description,
            priority=request.priority,
            estimated_hours=request.estimated_hours,
            labels=list(request.labels or []),
            metadata=metadata,
        )
        created = self.create_work_item(unified, actor, org_id=org_id)
        return self._legacy_task_from_work_item(created)

    def update_task(
        self,
        task_id: str,
        request: UpdateTaskRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Task:
        item = self.get_work_item(task_id, org_id=org_id)
        if item.item_type != WorkItemType.TASK:
            raise TaskNotFoundError(f"Task {task_id} not found")

        metadata = dict(request.metadata or {}) if request.metadata is not None else None
        if request.task_type is not None:
            if metadata is None:
                metadata = dict(item.metadata or {})
            metadata["task_type"] = request.task_type.value

        new_status = request.status
        if request.column_id is not None and request.status is None:
            col = self.get_column(request.column_id, org_id=org_id)
            new_status = col.status_mapping

        unified = UpdateWorkItemRequest(
            title=request.title,
            description=request.description,
            status=new_status,
            priority=request.priority,
            column_id=request.column_id,
            estimated_hours=request.estimated_hours,
            actual_hours=request.actual_hours,
            labels=request.labels,
            metadata=metadata,
        )
        updated = self.update_work_item(task_id, unified, actor, org_id=org_id)

        if request.assignee_user_id and request.assignee_agent_id:
            raise BoardServiceError("Only one of assignee_user_id or assignee_agent_id may be set")

        if request.assignee_user_id is not None:
            updated = self.assign_work_item(
                task_id,
                AssignWorkItemRequest(assignee_id=request.assignee_user_id, assignee_type=AssigneeType.USER),
                actor,
                org_id=org_id,
            )
        elif request.assignee_agent_id is not None:
            updated = self.assign_work_item(
                task_id,
                AssignWorkItemRequest(assignee_id=request.assignee_agent_id, assignee_type=AssigneeType.AGENT),
                actor,
                org_id=org_id,
            )

        return self._legacy_task_from_work_item(updated)

    def add_story_to_sprint(
        self,
        sprint_id: str,
        story_id: str,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> None:
        self.get_sprint(sprint_id, org_id=org_id)
        story = self.get_work_item(story_id, org_id=org_id)
        if story.item_type != WorkItemType.STORY:
            raise StoryNotFoundError(f"Story {story_id} not found")

        timestamp = _now()

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sprint_stories (sprint_id, story_id, added_at, added_by, org_id)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (sprint_id, story_id) DO NOTHING
                    """,
                    (sprint_id, story_id, timestamp, actor.id, org_id),
                )

        self._pool.run_transaction(
            operation="sprint_story.add",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"sprint_id": sprint_id, "story_id": story_id},
            executor=_execute,
            telemetry=self._telemetry,
        )

    def list_sprint_stories(self, sprint_id: str, *, org_id: Optional[str] = None) -> List[SprintStory]:
        def _query(conn: Any) -> List[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sprint_id, story_id, added_at, added_by FROM sprint_stories WHERE sprint_id = %s ORDER BY added_at ASC",
                    (sprint_id,),
                )
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, row)) for row in cur.fetchall()]

        results = self._pool.run_query(
            operation="sprint_story.list",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        return [SprintStory(**r) for r in results]

    # =========================================================================
    # Label CRUD Operations
    # =========================================================================

    def create_label(
        self,
        project_id: str,
        request: CreateLabelRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Label:
        """Create a new label for a project."""
        label_id = _short_id("lbl")
        timestamp = _now()

        def _execute(conn: Any) -> Dict:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO labels (label_id, project_id, name, color, description, created_at, updated_at, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING label_id, project_id, name, color, description, created_at, updated_at, created_by
                    """,
                    (
                        label_id,
                        project_id,
                        request.name,
                        request.color.value,
                        request.description,
                        timestamp,
                        timestamp,
                        actor.id,
                    ),
                )
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, cur.fetchone()))

        row = self._pool.run_transaction(
            operation="label.create",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"label_id": label_id, "project_id": project_id, "name": request.name},
            executor=_execute,
            telemetry=self._telemetry,
        )
        return self._row_to_label(row)

    def get_label(self, label_id: str, *, org_id: Optional[str] = None) -> Label:
        """Get a label by ID."""
        def _query(conn: Any) -> Optional[Dict]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT label_id, project_id, name, color, description, created_at, updated_at, created_by FROM labels WHERE label_id = %s",
                    (label_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, row))

        row = self._pool.run_query(
            operation="label.get",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        if not row:
            raise BoardServiceError(f"Label {label_id} not found")
        return self._row_to_label(row)

    def list_labels(
        self,
        project_id: str,
        *,
        org_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> LabelListResponse:
        """List all labels for a project."""
        def _query(conn: Any) -> tuple[List[Dict], int]:
            self._pool.set_tenant_context(conn, org_id, None)
            with conn.cursor() as cur:
                # Get total count
                cur.execute("SELECT COUNT(*) FROM labels WHERE project_id = %s", (project_id,))
                total = cur.fetchone()[0]

                # Get labels
                cur.execute(
                    "SELECT label_id, project_id, name, color, description, created_at, updated_at, created_by FROM labels WHERE project_id = %s ORDER BY name ASC LIMIT %s OFFSET %s",
                    (project_id, limit, offset),
                )
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, row)) for row in cur.fetchall()]
                return rows, total

        rows, total = self._pool.run_query(
            operation="label.list",
            service_prefix="board",
            executor=_query,
            telemetry=self._telemetry,
        )
        return LabelListResponse(
            labels=[self._row_to_label(r) for r in rows],
            total=total,
        )

    def update_label(
        self,
        label_id: str,
        request: UpdateLabelRequest,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> Label:
        """Update a label."""
        # First verify label exists
        self.get_label(label_id, org_id=org_id)

        def _execute(conn: Any) -> Dict:
            self._pool.set_tenant_context(conn, org_id, actor.id)

            # Build dynamic UPDATE
            updates, values = [], []
            if request.name is not None:
                updates.append("name = %s")
                values.append(request.name)
            if request.color is not None:
                updates.append("color = %s")
                values.append(request.color.value)
            if request.description is not None:
                updates.append("description = %s")
                values.append(request.description)

            if not updates:
                # No changes, return existing
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT label_id, project_id, name, color, description, created_at, updated_at, created_by FROM labels WHERE label_id = %s",
                        (label_id,),
                    )
                    cols = [d[0] for d in cur.description]
                    return dict(zip(cols, cur.fetchone()))

            # updated_at is handled by trigger, but we set it explicitly for immediate response
            updates.append("updated_at = NOW()")
            values.append(label_id)

            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE labels SET {', '.join(updates)} WHERE label_id = %s RETURNING label_id, project_id, name, color, description, created_at, updated_at, created_by",
                    values,
                )
                cols = [d[0] for d in cur.description]
                return dict(zip(cols, cur.fetchone()))

        row = self._pool.run_transaction(
            operation="label.update",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"label_id": label_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        return self._row_to_label(row)

    def delete_label(
        self,
        label_id: str,
        actor: Actor,
        *,
        org_id: Optional[str] = None,
    ) -> DeleteResult:
        """Delete a label."""
        # First verify label exists
        label = self.get_label(label_id, org_id=org_id)

        def _execute(conn: Any) -> None:
            self._pool.set_tenant_context(conn, org_id, actor.id)
            with conn.cursor() as cur:
                cur.execute("DELETE FROM labels WHERE label_id = %s", (label_id,))

        self._pool.run_transaction(
            operation="label.delete",
            service_prefix="board",
            actor=_actor_payload(actor),
            metadata={"label_id": label_id, "project_id": label.project_id},
            executor=_execute,
            telemetry=self._telemetry,
        )
        return DeleteResult(deleted_id=label_id, deleted_type="label")

    def _row_to_label(self, row: Dict) -> Label:
        """Convert a database row to a Label model."""
        return Label(
            label_id=row["label_id"],
            project_id=row["project_id"],
            name=row["name"],
            color=LabelColor(row["color"]) if row["color"] else LabelColor.GRAY,
            description=row.get("description"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=row.get("created_by"),
        )
