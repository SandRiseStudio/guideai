"""Helpers for executing bundled SQL inside Alembic revisions.

These utilities exist to support the migration path from legacy SQL scripts
(`schema/migrations/*.sql`) to Alembic-managed schema history.

We load SQL via `importlib.resources` so it works from source checkouts and
packaged installs (as long as the `schema.migrations` package data is included).
"""

from __future__ import annotations

from importlib import resources
from typing import Iterable, List, Optional


def load_sql_from_schema_migrations(filename: str) -> str:
    """Load a SQL file bundled under `schema/migrations/`."""

    try:
        # `schema.migrations` is a Python package (see schema/__init__.py).
        sql_path = resources.files("schema.migrations").joinpath(filename)
        return sql_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"SQL migration not found: schema/migrations/{filename}") from exc


def split_sql_statements(sql: str) -> List[str]:
    """Split a SQL script into executable statements.

    Handles single quotes, double quotes, line/block comments, and dollar-quoted
    bodies so we do not split inside PL/pgSQL functions.
    """

    statements: List[str] = []
    current: List[str] = []
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    dollar_quote: Optional[str] = None

    length = len(sql)
    i = 0

    while i < length:
        ch = sql[i]

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                current.append("\n")
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and i + 1 < length and sql[i + 1] == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if dollar_quote is not None:
            if sql.startswith(dollar_quote, i):
                current.append(dollar_quote)
                i += len(dollar_quote)
                dollar_quote = None
                continue
            current.append(ch)
            i += 1
            continue

        if not in_single and not in_double and dollar_quote is None:
            if ch == "-" and i + 1 < length and sql[i + 1] == "-":
                in_line_comment = True
                i += 2
                continue

            if ch == "/" and i + 1 < length and sql[i + 1] == "*":
                in_block_comment = True
                i += 2
                continue

        if not in_single and not in_double and ch == "$":
            j = i + 1
            while j < length and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < length and sql[j] == "$":
                dollar_quote = sql[i : j + 1]
                current.append(dollar_quote)
                i = j + 1
                continue

        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
            i += 1
            continue

        if ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
            i += 1
            continue

        if ch == ";" and not in_single and not in_double and dollar_quote is None:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current.clear()
            i += 1
            continue

        current.append(ch)
        i += 1

    final = "".join(current).strip()
    if final:
        statements.append(final)

    return statements


def execute_sql_filenames(op, filenames: Iterable[str]) -> None:
    """Execute one or more SQL migration files via Alembic `op`."""

    for filename in filenames:
        sql = load_sql_from_schema_migrations(filename)
        for statement in split_sql_statements(sql):
            op.execute(statement)
