"""Add unified work_items table to Workflow DB

Revision ID: wf0004_unified_work_items
Revises: wf0003_fix_sprints_schema
Create Date: 2025-12-12

Behavior: behavior_migrate_postgres_schema

The workflow DB needs the unified `work_items` table that `BoardService.create_work_item()`
uses. This is a port of `schema/migrations/031_unified_work_items.sql` for the workflow
Alembic chain.

The unified table consolidates epics, stories, and tasks with a `item_type` discriminator
and hierarchical `parent_id`.

Also adds 'draft' to work_item_status enum which the Python WorkItemStatus enum expects.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "wf0004_unified_work_items"
down_revision: Union[str, None] = "wf0003_fix_sprints_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add 'draft' to work_item_status enum if not present
    # PostgreSQL requires adding enum values with ALTER TYPE
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum
                WHERE enumlabel = 'draft'
                AND enumtypid = (SELECT oid FROM pg_type WHERE typname = 'work_item_status')
            ) THEN
                ALTER TYPE work_item_status ADD VALUE 'draft' BEFORE 'backlog';
            END IF;
        END$$;
        """
    )

    # Add work_item_type ENUM if not exists
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'work_item_type') THEN
                CREATE TYPE work_item_type AS ENUM ('epic', 'story', 'task');
            END IF;
        END$$;
        """
    )

    # Create unified work_items table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS work_items (
            -- Primary key and type discriminator
            item_id TEXT PRIMARY KEY,
            item_type work_item_type NOT NULL,

            -- Hierarchy and placement
            project_id TEXT NOT NULL,
            board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
            column_id TEXT REFERENCES board_columns(column_id) ON DELETE SET NULL,
            parent_id TEXT REFERENCES work_items(item_id) ON DELETE SET NULL,
            sprint_id TEXT REFERENCES sprints(sprint_id) ON DELETE SET NULL,

            -- Core fields
            title TEXT NOT NULL,
            description TEXT,
            status work_item_status NOT NULL DEFAULT 'backlog',
            priority work_item_priority NOT NULL DEFAULT 'medium',
            position INTEGER NOT NULL DEFAULT 0,

            -- Estimation
            story_points INTEGER,
            estimated_hours DECIMAL(5,2),
            actual_hours DECIMAL(5,2),

            -- Polymorphic assignment
            assignee_id TEXT,
            assignee_type assignee_type,
            assigned_at TIMESTAMPTZ,
            assigned_by TEXT,

            -- Dates
            start_date DATE,
            target_date DATE,
            due_date DATE,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,

            -- Visual/organizational
            color TEXT,
            labels JSONB NOT NULL DEFAULT '[]'::jsonb,

            -- Rich content
            acceptance_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
            checklist JSONB NOT NULL DEFAULT '[]'::jsonb,
            attachments JSONB NOT NULL DEFAULT '[]'::jsonb,

            -- Agent integration
            behavior_id TEXT,
            run_id TEXT,

            -- Metadata
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,

            -- Multi-tenant context
            org_id TEXT,

            -- Constraints
            CONSTRAINT valid_work_item_assignee CHECK (
                (assignee_id IS NULL AND assignee_type IS NULL) OR
                (assignee_id IS NOT NULL AND assignee_type IS NOT NULL)
            ),
            CONSTRAINT valid_hierarchy CHECK (
                (item_type = 'epic' AND parent_id IS NULL) OR
                (item_type IN ('story', 'task'))
            )
        );
        """
    )

    # Create indexes
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_work_items_item_type ON work_items (item_type);
        CREATE INDEX IF NOT EXISTS idx_work_items_project_id ON work_items (project_id);
        CREATE INDEX IF NOT EXISTS idx_work_items_board_id ON work_items (board_id);
        CREATE INDEX IF NOT EXISTS idx_work_items_column_id ON work_items (column_id);
        CREATE INDEX IF NOT EXISTS idx_work_items_parent_id ON work_items (parent_id);
        CREATE INDEX IF NOT EXISTS idx_work_items_sprint_id ON work_items (sprint_id);
        CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items (status);
        CREATE INDEX IF NOT EXISTS idx_work_items_priority ON work_items (priority);
        CREATE INDEX IF NOT EXISTS idx_work_items_assignee ON work_items (assignee_id, assignee_type) WHERE assignee_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_work_items_behavior_id ON work_items (behavior_id) WHERE behavior_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_work_items_run_id ON work_items (run_id) WHERE run_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_work_items_org_id ON work_items (org_id) WHERE org_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_work_items_position ON work_items (column_id, position);
        CREATE INDEX IF NOT EXISTS idx_work_items_created_at ON work_items (created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_work_items_hierarchy ON work_items (project_id, item_type, parent_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS work_items CASCADE")
    op.execute("DROP TYPE IF EXISTS work_item_type")
