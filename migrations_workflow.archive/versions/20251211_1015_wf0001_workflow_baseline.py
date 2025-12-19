"""Workflow DB baseline schema (workflow service + refactor)

Revision ID: wf0001_workflow_baseline
Revises: None
Create Date: 2025-12-11

Behavior: behavior_migrate_postgres_schema

Applies the legacy workflow-only SQL migrations:
- schema/migrations/003_create_workflow_service.sql
- schema/migrations/009_refactor_workflow_schema.sql

This is a stepping stone while we port these SQL migrations to native Alembic.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

from migrations.sql_utils import execute_sql_filenames


revision: str = "wf0001_workflow_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SQL_MIGRATIONS = [
    "003_create_workflow_service.sql",
    "009_refactor_workflow_schema.sql",
]


def upgrade() -> None:
    execute_sql_filenames(op, SQL_MIGRATIONS)


def downgrade() -> None:
    raise NotImplementedError(
        "Cannot downgrade workflow baseline migration."
    )
