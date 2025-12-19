"""Fix sprints schema to match BoardService expectations

Revision ID: wf0003_fix_sprints_schema
Revises: wf0002_board_entities
Create Date: 2025-12-12

Behavior: behavior_migrate_postgres_schema

The workflow DB originally created `sprints` with a legacy column (`velocity_target`)
plus a status CHECK constraint that doesn't accept the newer `planning` value.
`BoardService` inserts/updates `velocity_planned` and uses `SprintStatus.PLANNING`.

This migration:
- Adds `velocity_planned` and `velocity_completed` (if missing)
- Backfills `velocity_planned` from `velocity_target`
- Normalizes `status` from `planned` -> `planning`
- Updates the status CHECK constraint to accept `planning`
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "wf0003_fix_sprints_schema"
down_revision: Union[str, None] = "wf0003_board_columns_updated_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Columns expected by BoardService
    op.execute("ALTER TABLE sprints ADD COLUMN IF NOT EXISTS velocity_planned INTEGER")
    op.execute("ALTER TABLE sprints ADD COLUMN IF NOT EXISTS velocity_completed INTEGER")

    # Backfill from legacy column if present
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'sprints' AND column_name = 'velocity_target'
            ) THEN
                UPDATE sprints
                SET velocity_planned = velocity_target
                WHERE velocity_planned IS NULL AND velocity_target IS NOT NULL;
            END IF;
        END $$;
        """
    )

    # Normalize status values to the newer enum-like strings
    op.execute("UPDATE sprints SET status = 'planning' WHERE status = 'planned'")

    # Update CHECK constraint to accept planning
    op.execute("ALTER TABLE sprints DROP CONSTRAINT IF EXISTS sprints_status_check")
    op.execute(
        """
        ALTER TABLE sprints
        ADD CONSTRAINT sprints_status_check
        CHECK (status IN ('planning', 'active', 'completed', 'cancelled'))
        """
    )


def downgrade() -> None:
    raise NotImplementedError("Workflow sprint schema downgrade not implemented")
