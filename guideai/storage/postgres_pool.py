"""Shared SQLAlchemy-powered PostgreSQL connection pooling utilities."""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from typing import Dict, Tuple

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

__all__ = ["PostgresPool"]

_POOL_CACHE: Dict[Tuple[str, int, int, int, int, int], Engine] = {}
_CACHE_LOCK = threading.Lock()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _pool_config() -> Tuple[int, int, int, int, int]:
    pool_size = _int_env("GUIDEAI_PG_POOL_SIZE", 10)
    max_overflow = _int_env("GUIDEAI_PG_POOL_MAX_OVERFLOW", 20)
    pool_timeout = _int_env("GUIDEAI_PG_POOL_TIMEOUT", 30)
    pool_recycle = _int_env("GUIDEAI_PG_POOL_RECYCLE", 1800)
    connect_timeout = _int_env("GUIDEAI_PG_CONNECT_TIMEOUT", 5)
    return pool_size, max_overflow, pool_timeout, pool_recycle, connect_timeout


def _get_engine(dsn: str) -> Engine:
    config = _pool_config()
    key = (dsn, *config)
    with _CACHE_LOCK:
        engine = _POOL_CACHE.get(key)
        if engine is None:
            pool_size, max_overflow, pool_timeout, pool_recycle, connect_timeout = config
            engine = create_engine(
                dsn,
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
                pool_recycle=pool_recycle,
                pool_pre_ping=True,
                connect_args={"connect_timeout": connect_timeout},
                future=True,
            )
            _POOL_CACHE[key] = engine
        return engine


class _ConnectionProxy:
    def __init__(self, pool: "PostgresPool", *, autocommit: bool) -> None:
        self._pool = pool
        self._autocommit = autocommit

    @contextmanager
    def cursor(self, *args, **kwargs):
        with self._pool.connection(autocommit=self._autocommit) as conn:
            with conn.cursor(*args, **kwargs) as cur:
                yield cur

    def commit(self) -> None:  # noqa: D401 - proxy commit for compatibility
        """No-op commit placeholder for autocommit connections."""
        return None

    def rollback(self) -> None:
        """No-op rollback placeholder for autocommit connections."""
        return None


class PostgresPool:
    """Lightweight wrapper around SQLAlchemy engine for pooled connections."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._engine = _get_engine(dsn)

    @contextmanager
    def connection(self, *, autocommit: bool = True):
        """Acquire a raw psycopg2 connection with optional autocommit."""
        with self._engine.connect() as connection:
            raw = connection.connection
            previous_autocommit = getattr(raw, "autocommit", False)
            try:
                if hasattr(raw, "autocommit"):
                    raw.autocommit = autocommit
                yield raw
                if not autocommit and hasattr(raw, "commit"):
                    raw.commit()
            except Exception:
                if not autocommit and hasattr(raw, "rollback"):
                    raw.rollback()
                raise
            finally:
                if hasattr(raw, "autocommit"):
                    raw.autocommit = previous_autocommit

    def proxy(self, *, autocommit: bool = True) -> _ConnectionProxy:
        """Return a compatibility proxy exposing cursor()/commit() helpers."""
        return _ConnectionProxy(self, autocommit=autocommit)

    def close(self) -> None:
        """Dispose underlying engine connections."""
        self._engine.dispose()
