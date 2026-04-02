"""
Test for DuckDB → PostgreSQL migration script.

Validates that scripts/migrate_telemetry_duckdb_to_postgres.py correctly
migrates fact tables from DuckDB to TimescaleDB.
"""

import os
import subprocess
import sys
from pathlib import Path

import psycopg2
import pytest

SCRIPTS_DIR = Path("scripts")
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

DEFAULT_TELEMETRY_DSN = "postgresql://guideai_telemetry:dev_telemetry_pass@localhost:5432/telemetry"
TELEMETRY_PG_DSN = os.environ.get("GUIDEAI_TELEMETRY_PG_DSN", DEFAULT_TELEMETRY_DSN)


def _truncate_fact_tables(pg_dsn: str) -> None:
    """Reset telemetry fact tables to ensure validation counts match DuckDB snapshot."""
    from conftest import safe_truncate
    safe_truncate(pg_dsn, [
        "fact_behavior_usage", "fact_compliance_steps",
        "fact_execution_status", "fact_token_savings",
    ])


@pytest.fixture(scope="module", autouse=True)
def run_full_migration_once():
    """Ensure the Postgres warehouse has migrated DuckDB data before assertions."""
    script = Path("scripts/migrate_telemetry_duckdb_to_postgres.py")
    assert script.exists(), "Migration script not found"

    env = os.environ.copy()
    env["GUIDEAI_TELEMETRY_PG_DSN"] = TELEMETRY_PG_DSN
    pg_dsn = TELEMETRY_PG_DSN

    _truncate_fact_tables(pg_dsn)

    result = subprocess.run(
        [sys.executable, str(script), "--batch-size", "500"],
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Migration script failed before tests: {result.stderr}\n{result.stdout}"


def test_migration_script_runs_successfully():
    """Test that migration script executes without errors."""
    script = Path("scripts/migrate_telemetry_duckdb_to_postgres.py")
    assert script.exists(), "Migration script not found"

    # Run in dry-run mode to avoid side effects
    result = subprocess.run(
        [sys.executable, str(script), "--dry-run"],
        env={**os.environ, "GUIDEAI_TELEMETRY_PG_DSN": TELEMETRY_PG_DSN},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, f"Migration script failed: {result.stderr}"
    assert "Dry run complete" in result.stdout
    assert "Would migrate" in result.stdout


def test_migrated_data_integrity():
    """Verify migrated data exists and has correct structure."""
    conn = psycopg2.connect(TELEMETRY_PG_DSN)
    try:
        cur = conn.cursor()

        # Check fact_behavior_usage
        cur.execute("SELECT COUNT(*), MAX(behavior_count) FROM fact_behavior_usage")
        row = cur.fetchone()
        assert row is not None, "fact_behavior_usage query returned no rows"
        count, max_behaviors = row
        assert count >= 1, "fact_behavior_usage should have migrated data"
        assert max_behaviors >= 0, "behavior_count should be non-negative"

        # Check behavior_ids is valid JSONB
        cur.execute("SELECT behavior_ids FROM fact_behavior_usage LIMIT 1")
        row = cur.fetchone()
        assert row is not None, "fact_behavior_usage behavior_ids query returned no rows"
        behavior_ids = row[0]
        assert isinstance(behavior_ids, list), "behavior_ids should be deserialized as list"

        # Check fact_compliance_steps
        cur.execute("SELECT COUNT(*) FROM fact_compliance_steps")
        row = cur.fetchone()
        assert row is not None, "fact_compliance_steps query returned no rows"
        count = row[0]
        assert count >= 1, "fact_compliance_steps should have migrated data"

        # Check fact_execution_status
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT status) FROM fact_execution_status")
        row = cur.fetchone()
        assert row is not None, "fact_execution_status query returned no rows"
        count, status_count = row
        assert count >= 1, "fact_execution_status should have migrated data"
        assert status_count >= 1, "Should have at least one status value"

        # Check fact_token_savings
        cur.execute("SELECT COUNT(*), AVG(token_savings_pct) FROM fact_token_savings")
        row = cur.fetchone()
        assert row is not None, "fact_token_savings query returned no rows"
        count, avg_savings = row
        assert count >= 1, "fact_token_savings should have migrated data"
        assert avg_savings is not None, "token_savings_pct should be non-null"

        cur.close()
    finally:
        conn.close()


def test_parse_behavior_ids():
    """Test behavior_ids parsing helper function."""
    # Import the parse function from the migration script dynamically to avoid path issues
    import importlib

    migration_module = importlib.import_module("migrate_telemetry_duckdb_to_postgres")
    parse_behavior_ids = migration_module.parse_behavior_ids

    # Test various formats
    assert parse_behavior_ids("[behavior_one]") == ["behavior_one"]
    assert parse_behavior_ids("[behavior_one, behavior_two]") == ["behavior_one", "behavior_two"]
    assert parse_behavior_ids('["behavior_one", "behavior_two"]') == ["behavior_one", "behavior_two"]
    assert parse_behavior_ids("set()") == []
    assert parse_behavior_ids("") == []
    assert parse_behavior_ids(None) == []
