#!/usr/bin/env python3
"""Initialize DuckDB warehouse schema for analytics.

This script creates the necessary tables and views for GuideAI analytics
before the API server starts. It uses the schema from prd_metrics_schema_duckdb.sql.
"""

import sys
from pathlib import Path


def init_warehouse(db_path: str, schema_file: str) -> None:
    """Initialize DuckDB warehouse with schema.

    Args:
        db_path: Path to DuckDB file
        schema_file: Path to SQL schema file
    """
    try:
        import duckdb
    except ImportError:
        print("ERROR: duckdb not installed", file=sys.stderr)
        sys.exit(1)

    db_file = Path(db_path)
    sql_file = Path(schema_file)

    if not sql_file.exists():
        print(f"ERROR: Schema file not found: {schema_file}", file=sys.stderr)
        sys.exit(1)

    # Create parent directory if needed
    db_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"Initializing DuckDB warehouse at {db_path}...")

    try:
        # Connect to database (creates if doesn't exist)
        conn = duckdb.connect(str(db_path))

        # Read schema file
        schema_sql = sql_file.read_text()

        # Remove comments and split by semicolon
        statements = []
        for line in schema_sql.split('\n'):
            # Skip comment lines
            if line.strip().startswith('--'):
                continue
            statements.append(line)

        # Rejoin and split by semicolon
        full_sql = '\n'.join(statements)
        for statement in full_sql.split(';'):
            statement = statement.strip()
            if statement:
                try:
                    conn.execute(statement)
                except Exception as stmt_err:
                    # Log but continue (for CREATE IF NOT EXISTS)
                    print(f"  Statement warning: {stmt_err}")

        conn.close()
        print("✓ DuckDB warehouse initialized successfully")

    except Exception as e:
        print(f"ERROR: Failed to initialize warehouse: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else "/app/data/telemetry.duckdb"
    schema_file = sys.argv[2] if len(sys.argv) > 2 else "/app/docs/analytics/prd_metrics_schema_duckdb.sql"

    init_warehouse(db_path, schema_file)
