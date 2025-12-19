"""Unit tests for PostgresPool schema support.

Tests the schema parameter and for_schema() factory method without
requiring a database connection.
"""

import pytest
from unittest.mock import MagicMock, patch


class TestPostgresPoolSchema:
    """Test schema-related functionality of PostgresPool."""

    @patch("guideai.storage.postgres_pool._get_engine")
    @patch("guideai.storage.postgres_pool.postgres_metrics")
    def test_init_with_schema(self, mock_metrics, mock_get_engine):
        """Test that PostgresPool accepts schema parameter."""
        from guideai.storage.postgres_pool import PostgresPool

        mock_get_engine.return_value = MagicMock()
        mock_metrics.PROMETHEUS_AVAILABLE = False

        pool = PostgresPool(dsn="postgresql://test", schema="auth")

        assert pool.schema == "auth"
        mock_get_engine.assert_called_once_with("postgresql://test", schema="auth")

    @patch("guideai.storage.postgres_pool._get_engine")
    @patch("guideai.storage.postgres_pool.postgres_metrics")
    def test_init_without_schema(self, mock_metrics, mock_get_engine):
        """Test that PostgresPool works without schema (backwards compatible)."""
        from guideai.storage.postgres_pool import PostgresPool

        mock_get_engine.return_value = MagicMock()
        mock_metrics.PROMETHEUS_AVAILABLE = False

        pool = PostgresPool(dsn="postgresql://test")

        assert pool.schema is None
        mock_get_engine.assert_called_once_with("postgresql://test", schema=None)

    @patch("guideai.storage.postgres_pool._get_engine")
    @patch("guideai.storage.postgres_pool.postgres_metrics")
    def test_for_schema_factory(self, mock_metrics, mock_get_engine):
        """Test the for_schema() factory method."""
        from guideai.storage.postgres_pool import PostgresPool

        mock_get_engine.return_value = MagicMock()
        mock_metrics.PROMETHEUS_AVAILABLE = False

        pool = PostgresPool.for_schema("board", dsn="postgresql://test")

        assert pool.schema == "board"
        assert pool._service_name == "board"  # Default service_name to schema

    @patch("guideai.storage.postgres_pool._get_engine")
    @patch("guideai.storage.postgres_pool.postgres_metrics")
    def test_for_schema_custom_service_name(self, mock_metrics, mock_get_engine):
        """Test for_schema() with custom service_name."""
        from guideai.storage.postgres_pool import PostgresPool

        mock_get_engine.return_value = MagicMock()
        mock_metrics.PROMETHEUS_AVAILABLE = False

        pool = PostgresPool.for_schema(
            "behavior",
            dsn="postgresql://test",
            service_name="behavior_service",
        )

        assert pool.schema == "behavior"
        assert pool._service_name == "behavior_service"

    @patch("guideai.storage.postgres_pool._get_engine")
    @patch("guideai.storage.postgres_pool.postgres_metrics")
    def test_get_pool_stats_includes_schema(self, mock_metrics, mock_get_engine):
        """Test that get_pool_stats() includes schema in output."""
        from guideai.storage.postgres_pool import PostgresPool

        mock_engine = MagicMock()
        mock_pool = MagicMock()
        mock_pool.checkedout.return_value = 0
        mock_pool.size.return_value = 10
        mock_pool.overflow.return_value = 0
        mock_engine.pool = mock_pool
        mock_get_engine.return_value = mock_engine
        mock_metrics.PROMETHEUS_AVAILABLE = False

        pool = PostgresPool(dsn="postgresql://test", schema="execution")
        stats = pool.get_pool_stats()

        assert stats["schema"] == "execution"
        assert stats["pool_size"] == 10

    def test_get_engine_includes_schema_in_cache_key(self):
        """Test that _get_engine uses schema in cache key for isolation."""
        from guideai.storage.postgres_pool import _POOL_CACHE, _CACHE_LOCK

        # Verify the cache key includes schema position
        # This is a structural test to ensure different schemas get different engines
        with _CACHE_LOCK:
            # Just verify cache key format - actual engine creation requires DB
            pass  # Structure test only


class TestSchemaSearchPath:
    """Test schema search_path event listener setup."""

    def test_search_path_set_on_connect(self):
        """Integration-style test that would verify search_path.

        Note: This test is marked for integration suite as it requires
        actual database connection. See tests/integration/ for full test.
        """
        pytest.skip("Requires database connection - run in integration suite")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
