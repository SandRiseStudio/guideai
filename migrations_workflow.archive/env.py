"""Alembic environment configuration for Workflow DB migrations.

Behavior: behavior_migrate_postgres_schema

This Alembic environment is intentionally scoped to the WorkflowService
Postgres database (typically port 5434 in tests). It uses:
- GUIDEAI_WORKFLOW_PG_DSN if set
- otherwise DATABASE_URL

It is separate from the main `migrations/` chain to avoid applying non-workflow
schemas (telemetry, metrics, etc.) into the workflow database.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add project root to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

config = context.config

DATABASE_URL = os.environ.get("GUIDEAI_WORKFLOW_PG_DSN") or os.environ.get(
    "DATABASE_URL",
    "postgresql://guideai_user:local_dev_pw@localhost:5434/guideai_workflow",
)

# Override sqlalchemy.url from ini.
# NOTE: Alembic stores config in a `ConfigParser` which treats `%` as
# interpolation markers. Our DSNs include percent-encoded query params
# (e.g. `%20`), so we must escape them.
config.set_main_option("sqlalchemy.url", DATABASE_URL.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# We use raw op.execute / SQL in these revisions; no autogenerate.
target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # Use separate version table to isolate from main guideai migrations
        version_table="workflow_alembic_version",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            # Use separate version table to isolate from main guideai migrations
            version_table="workflow_alembic_version",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
