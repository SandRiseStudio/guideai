"""Add missing columns to organizations table.

Revision ID: add_org_columns
Revises: 20251219_align_behavior_schema
Create Date: 2024-12-19

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "add_org_columns"
down_revision = "20251219_align_behavior_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add missing columns to organizations table."""

    # Add display_name column
    op.add_column(
        "organizations",
        sa.Column("display_name", sa.String(255), nullable=True),
        schema="auth"
    )

    # Add plan column with default 'free'
    op.add_column(
        "organizations",
        sa.Column("plan", sa.String(32), server_default="free", nullable=False),
        schema="auth"
    )

    # Add status column with default 'active'
    op.add_column(
        "organizations",
        sa.Column("status", sa.String(32), server_default="active", nullable=False),
        schema="auth"
    )

    # Add stripe_customer_id column
    op.add_column(
        "organizations",
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
        schema="auth"
    )

    # Add metadata column
    op.add_column(
        "organizations",
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=True),
        schema="auth"
    )


def downgrade() -> None:
    """Remove added columns from organizations table."""
    op.drop_column("organizations", "metadata", schema="auth")
    op.drop_column("organizations", "stripe_customer_id", schema="auth")
    op.drop_column("organizations", "status", schema="auth")
    op.drop_column("organizations", "plan", schema="auth")
    op.drop_column("organizations", "display_name", schema="auth")
