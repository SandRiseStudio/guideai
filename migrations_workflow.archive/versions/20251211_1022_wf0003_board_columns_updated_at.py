"""Add board_columns.updated_at (Workflow DB)

Revision ID: wf0003_board_columns_updated_at
Revises: wf0002_board_entities
Create Date: 2025-12-11

Behavior: behavior_migrate_postgres_schema

Adds `updated_at` to `board_columns` in the workflow database to support
optimistic concurrency for column reorder/updates.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "wf0003_board_columns_updated_at"
down_revision: Union[str, None] = "wf0002_board_entities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE board_columns ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ")
    op.execute("UPDATE board_columns SET updated_at = created_at WHERE updated_at IS NULL")
    op.execute("ALTER TABLE board_columns ALTER COLUMN updated_at SET NOT NULL")
    op.execute("ALTER TABLE board_columns ALTER COLUMN updated_at SET DEFAULT NOW()")


def downgrade() -> None:
    op.execute("ALTER TABLE board_columns DROP COLUMN IF EXISTS updated_at")
