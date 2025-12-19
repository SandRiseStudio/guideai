"""Create Board entity tables in Workflow DB

Revision ID: wf0002_board_entities
Revises: wf0001_workflow_baseline
Create Date: 2025-12-11

Behavior: behavior_migrate_postgres_schema

Ports the Agile Board tables needed by `BoardService` in the workflow database.
This is adapted from `migrations/versions/20251210_0004_create_board_entities.py`
(which targets the main Alembic chain).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "wf0002_board_entities"
down_revision: Union[str, None] = "wf0001_workflow_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: This uses op.execute blocks to preserve RLS/policy DDL and enums.
    # The goal is to be functionally equivalent to legacy SQL while we migrate
    # incrementally to SQLAlchemy-native operations.

    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE assignee_type AS ENUM ('user', 'agent');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;

        DO $$ BEGIN
            CREATE TYPE work_item_status AS ENUM (
                'backlog',
                'todo',
                'in_progress',
                'in_review',
                'done',
                'cancelled'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;

        DO $$ BEGIN
            CREATE TYPE epic_status AS ENUM (
                'draft',
                'active',
                'completed',
                'cancelled'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;

        DO $$ BEGIN
            CREATE TYPE work_item_priority AS ENUM (
                'critical',
                'high',
                'medium',
                'low'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;

        DO $$ BEGIN
            CREATE TYPE task_type AS ENUM (
                'feature',
                'bug',
                'chore',
                'spike',
                'documentation'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS boards (
            board_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            settings JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            org_id TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_boards_project_id ON boards (project_id);
        CREATE INDEX IF NOT EXISTS idx_boards_org_id ON boards (org_id) WHERE org_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_boards_is_default ON boards (project_id, is_default) WHERE is_default = TRUE;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS board_columns (
            column_id TEXT PRIMARY KEY,
            board_id TEXT NOT NULL REFERENCES boards(board_id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            status_mapping work_item_status NOT NULL,
            wip_limit INTEGER,
            settings JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (board_id, position)
        );

        CREATE INDEX IF NOT EXISTS idx_board_columns_board_id ON board_columns (board_id);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS epics (
            epic_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            description TEXT,
            status epic_status NOT NULL DEFAULT 'draft',
            priority work_item_priority NOT NULL DEFAULT 'medium',
            color TEXT,
            start_date DATE,
            target_date DATE,
            completed_at TIMESTAMPTZ,
            labels JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            org_id TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_epics_project_id ON epics (project_id);
        CREATE INDEX IF NOT EXISTS idx_epics_board_id ON epics (board_id);
        CREATE INDEX IF NOT EXISTS idx_epics_status ON epics (status);
        CREATE INDEX IF NOT EXISTS idx_epics_org_id ON epics (org_id) WHERE org_id IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS stories (
            story_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
            epic_id TEXT REFERENCES epics(epic_id) ON DELETE SET NULL,
            column_id TEXT REFERENCES board_columns(column_id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            description TEXT,
            status work_item_status NOT NULL DEFAULT 'backlog',
            priority work_item_priority NOT NULL DEFAULT 'medium',
            story_points INTEGER,
            position INTEGER NOT NULL DEFAULT 0,
            assignee_id TEXT,
            assignee_type assignee_type,
            assigned_at TIMESTAMPTZ,
            assigned_by TEXT,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            due_date DATE,
            labels JSONB NOT NULL DEFAULT '[]'::jsonb,
            acceptance_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            org_id TEXT,
            CONSTRAINT valid_assignee CHECK (
                (assignee_id IS NULL AND assignee_type IS NULL) OR
                (assignee_id IS NOT NULL AND assignee_type IS NOT NULL)
            )
        );

        CREATE INDEX IF NOT EXISTS idx_stories_project_id ON stories (project_id);
        CREATE INDEX IF NOT EXISTS idx_stories_board_id ON stories (board_id);
        CREATE INDEX IF NOT EXISTS idx_stories_epic_id ON stories (epic_id);
        CREATE INDEX IF NOT EXISTS idx_stories_column_id ON stories (column_id);
        CREATE INDEX IF NOT EXISTS idx_stories_status ON stories (status);
        CREATE INDEX IF NOT EXISTS idx_stories_assignee ON stories (assignee_id, assignee_type) WHERE assignee_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_stories_org_id ON stories (org_id) WHERE org_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_stories_position ON stories (column_id, position);
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS board_tasks (
            task_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
            story_id TEXT REFERENCES stories(story_id) ON DELETE CASCADE,
            column_id TEXT REFERENCES board_columns(column_id) ON DELETE SET NULL,
            title TEXT NOT NULL,
            description TEXT,
            status work_item_status NOT NULL DEFAULT 'todo',
            priority work_item_priority NOT NULL DEFAULT 'medium',
            task_type task_type NOT NULL DEFAULT 'feature',
            position INTEGER NOT NULL DEFAULT 0,
            behavior_name TEXT,
            run_id TEXT,
            assignee_id TEXT,
            assignee_type assignee_type,
            assigned_at TIMESTAMPTZ,
            assigned_by TEXT,
            due_date DATE,
            estimate_minutes INTEGER,
            actual_minutes INTEGER,
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            org_id TEXT,
            CONSTRAINT valid_task_assignee CHECK (
                (assignee_id IS NULL AND assignee_type IS NULL) OR
                (assignee_id IS NOT NULL AND assignee_type IS NOT NULL)
            )
        );

        CREATE INDEX IF NOT EXISTS idx_tasks_story_id ON board_tasks (story_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_board_id ON board_tasks (board_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_column_id ON board_tasks (column_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON board_tasks (status);
        CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON board_tasks (assignee_id, assignee_type) WHERE assignee_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_tasks_run_id ON board_tasks (run_id) WHERE run_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_tasks_org_id ON board_tasks (org_id) WHERE org_id IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS assignment_history (
            assignment_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            work_item_type TEXT NOT NULL CHECK (work_item_type IN ('story', 'task')),
            work_item_id TEXT NOT NULL,
            old_assignee_id TEXT,
            old_assignee_type assignee_type,
            new_assignee_id TEXT,
            new_assignee_type assignee_type,
            changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            changed_by TEXT NOT NULL,
            reason TEXT,
            metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
            org_id TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_assignment_history_work_item ON assignment_history (work_item_type, work_item_id);
        CREATE INDEX IF NOT EXISTS idx_assignment_history_project_id ON assignment_history (project_id);
        CREATE INDEX IF NOT EXISTS idx_assignment_history_changed_at ON assignment_history (changed_at);
        CREATE INDEX IF NOT EXISTS idx_assignment_history_org_id ON assignment_history (org_id) WHERE org_id IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sprints (
            sprint_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            board_id TEXT REFERENCES boards(board_id) ON DELETE SET NULL,
            name TEXT NOT NULL,
            goal TEXT,
            status TEXT NOT NULL DEFAULT 'planned' CHECK (status IN ('planned', 'active', 'completed', 'cancelled')),
            start_date DATE NOT NULL,
            end_date DATE NOT NULL,
            velocity_target INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_by TEXT NOT NULL,
            org_id TEXT,
            CONSTRAINT valid_sprint_dates CHECK (end_date >= start_date)
        );

        CREATE INDEX IF NOT EXISTS idx_sprints_project_id ON sprints (project_id);
        CREATE INDEX IF NOT EXISTS idx_sprints_board_id ON sprints (board_id);
        CREATE INDEX IF NOT EXISTS idx_sprints_status ON sprints (status);
        CREATE INDEX IF NOT EXISTS idx_sprints_dates ON sprints (start_date, end_date);
        CREATE INDEX IF NOT EXISTS idx_sprints_org_id ON sprints (org_id) WHERE org_id IS NOT NULL;
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sprint_stories (
            sprint_id TEXT REFERENCES sprints(sprint_id) ON DELETE CASCADE,
            story_id TEXT REFERENCES stories(story_id) ON DELETE CASCADE,
            added_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            added_by TEXT NOT NULL,
            PRIMARY KEY (sprint_id, story_id)
        );

        CREATE INDEX IF NOT EXISTS idx_sprint_stories_story_id ON sprint_stories (story_id);
        """
    )


def downgrade() -> None:
    raise NotImplementedError("Workflow board entities downgrade not implemented")
