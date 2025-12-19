#!/usr/bin/env python3
"""Apply PostgreSQL migrations to the AgentOrchestrator (shared/central) database.

This script runs migrations against the orchestrator database, which serves as
the central/shared database for cross-service tables like organizations.

Usage::

    ./scripts/run_postgres_orchestrator_migration.py --dsn postgresql://user:pass@localhost:5438/orchestrator
    ./scripts/run_postgres_orchestrator_migration.py --migration schema/migrations/023_create_organizations.sql

When ``--dsn`` is omitted, the script falls back to ``GUIDEAI_ORCHESTRATOR_PG_DSN``
or constructs it from component environment variables.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import List

from _postgres_migration_utils import (
    discover_dsn,
    execute_statements,
    load_migration,
    split_sql_statements,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MIGRATION = REPO_ROOT / "schema" / "migrations" / "011_create_agent_orchestrator.sql"


def construct_dsn_from_env() -> str | None:
    """Construct DSN from individual environment variables."""
    host = os.environ.get("GUIDEAI_PG_HOST_AGENT_ORCHESTRATOR", "localhost")
    port = os.environ.get("GUIDEAI_PG_PORT_AGENT_ORCHESTRATOR", "5438")
    user = os.environ.get("GUIDEAI_PG_USER_AGENT_ORCHESTRATOR", "orchestrator")
    password = os.environ.get("GUIDEAI_PG_PASS_AGENT_ORCHESTRATOR", "orchestrator_dev")
    db = os.environ.get("GUIDEAI_PG_DB_AGENT_ORCHESTRATOR", "orchestrator")

    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Apply PostgreSQL AgentOrchestrator migration")
    parser.add_argument("--dsn", help="PostgreSQL DSN (overrides GUIDEAI_ORCHESTRATOR_PG_DSN)")
    parser.add_argument(
        "--migration",
        type=Path,
        default=DEFAULT_MIGRATION,
        help=f"Path to migration SQL file (default: {DEFAULT_MIGRATION.relative_to(REPO_ROOT)})",
    )
    parser.add_argument("--connect-timeout", type=int, default=10, help="Connection timeout in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Print statements without executing them")

    args = parser.parse_args(argv)

    # Try to discover DSN from various sources
    dsn = args.dsn or os.environ.get("GUIDEAI_ORCHESTRATOR_PG_DSN") or os.environ.get("GUIDEAI_AGENT_ORCHESTRATOR_PG_DSN")
    if not dsn:
        dsn = construct_dsn_from_env()

    if not dsn:
        print("❌ Could not determine DSN. Set GUIDEAI_ORCHESTRATOR_PG_DSN or provide --dsn")
        return 1

    migration_sql = load_migration(args.migration)
    statements = split_sql_statements(migration_sql)

    if not statements:
        print("⚠️ No statements found in migration; nothing to do.")
        return 0

    if args.dry_run:
        print("-- Dry run --")
        for index, statement in enumerate(statements, start=1):
            print(f"[{index}] {statement.strip()}\n")
        return 0

    # Mask password in display
    display_dsn = dsn.split("@")[-1] if "@" in dsn else dsn
    print(f"Applying orchestrator migration using DSN: ...@{display_dsn}")
    print(f"Executing {len(statements)} statements from {args.migration}")

    execute_statements(dsn, statements, connect_timeout=args.connect_timeout)

    print("✅ Migration applied successfully.")
    print(
        "📌 Remember to run 'guideai record-action' to capture this deployment in the audit log "
        "per behavior_replayable_actions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
