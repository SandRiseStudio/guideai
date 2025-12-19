"""Fix assignment_history and sprint_stories schema mismatches

Revision ID: wf0005_fix_assignment_history
Revises: wf0004_unified_work_items
Create Date: 2025-12-12

Behavior: behavior_migrate_postgres_schema

BoardService uses different column names than the original wf0002 migration:
- assignment_history: history_id, assignable_id, assignable_type, action,
  performed_by, performed_at, previous_assignee_id, previous_assignee_type
- sprint_stories: needs org_id column

This migration renames/adds columns to match BoardService expectations.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "wf0005_fix_assignment_history"
down_revision: Union[str, None] = "wf0004_unified_work_items"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add assignment_action enum for assignment_history.action column
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'assignment_action') THEN
                CREATE TYPE assignment_action AS ENUM ('assigned', 'reassigned', 'unassigned');
            END IF;
        END$$;
        """
    )

    # Rename assignment_history columns to match BoardService expectations
    # assignment_id -> history_id
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'assignment_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'history_id'
            ) THEN
                ALTER TABLE assignment_history RENAME COLUMN assignment_id TO history_id;
            END IF;
        END$$;
        """
    )

    # work_item_id -> assignable_id
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'work_item_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'assignable_id'
            ) THEN
                ALTER TABLE assignment_history RENAME COLUMN work_item_id TO assignable_id;
            END IF;
        END$$;
        """
    )

    # work_item_type -> assignable_type
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'work_item_type'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'assignable_type'
            ) THEN
                ALTER TABLE assignment_history RENAME COLUMN work_item_type TO assignable_type;
            END IF;
        END$$;
        """
    )

    # changed_by -> performed_by
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'changed_by'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'performed_by'
            ) THEN
                ALTER TABLE assignment_history RENAME COLUMN changed_by TO performed_by;
            END IF;
        END$$;
        """
    )

    # changed_at -> performed_at
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'changed_at'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'performed_at'
            ) THEN
                ALTER TABLE assignment_history RENAME COLUMN changed_at TO performed_at;
            END IF;
        END$$;
        """
    )

    # old_assignee_id -> previous_assignee_id
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'old_assignee_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'previous_assignee_id'
            ) THEN
                ALTER TABLE assignment_history RENAME COLUMN old_assignee_id TO previous_assignee_id;
            END IF;
        END$$;
        """
    )

    # old_assignee_type -> previous_assignee_type
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'old_assignee_type'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'previous_assignee_type'
            ) THEN
                ALTER TABLE assignment_history RENAME COLUMN old_assignee_type TO previous_assignee_type;
            END IF;
        END$$;
        """
    )

    # Rename new_assignee_id -> assignee_id (service expects this column)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'new_assignee_id'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'assignee_id'
            ) THEN
                ALTER TABLE assignment_history RENAME COLUMN new_assignee_id TO assignee_id;
            END IF;
        END$$;
        """
    )

    # Rename new_assignee_type -> assignee_type (service expects this column)
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'new_assignee_type'
            ) AND NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'assignee_type'
            ) THEN
                ALTER TABLE assignment_history RENAME COLUMN new_assignee_type TO assignee_type;
            END IF;
        END$$;
        """
    )

    # Add action column (service expects it)
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'assignment_history' AND column_name = 'action'
            ) THEN
                ALTER TABLE assignment_history ADD COLUMN action assignment_action NOT NULL DEFAULT 'assigned';
            END IF;
        END$$;
        """
    )

    # Drop the CHECK constraint on the old column name if it exists
    op.execute(
        """
        DO $$
        BEGIN
            ALTER TABLE assignment_history DROP CONSTRAINT IF EXISTS assignment_history_work_item_type_check;
        EXCEPTION WHEN others THEN
            NULL;
        END$$;
        """
    )

    # Update assignable_type to be TEXT without constraint (service uses item_type values like 'epic', 'story', 'task')
    # First, let's change any constraint on this column

    # Add org_id to sprint_stories table
    op.execute(
        """
        ALTER TABLE sprint_stories ADD COLUMN IF NOT EXISTS org_id TEXT
        """
    )

    # Update sprint_stories foreign key to reference work_items instead of stories
    # The stories are now created in work_items table, so we need to update the FK
    op.execute(
        """
        DO $$
        BEGIN
            -- Drop the old foreign key constraint
            ALTER TABLE sprint_stories DROP CONSTRAINT IF EXISTS sprint_stories_story_id_fkey;

            -- Add new foreign key to work_items table
            ALTER TABLE sprint_stories ADD CONSTRAINT sprint_stories_story_id_fkey
                FOREIGN KEY (story_id) REFERENCES work_items(item_id) ON DELETE CASCADE;
        EXCEPTION
            WHEN undefined_table THEN
                NULL;  -- work_items table doesn't exist yet, skip
            WHEN others THEN
                RAISE NOTICE 'Error updating sprint_stories FK: %', SQLERRM;
        END$$;
        """
    )


def downgrade() -> None:
    # Reverse column renames (not fully implemented)
    op.execute("ALTER TABLE sprint_stories DROP COLUMN IF EXISTS org_id")
