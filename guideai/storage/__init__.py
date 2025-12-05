"""Storage adapters for guideai multi-tier architecture.

This package provides storage adapters for:
- PostgreSQL: Primary database with connection pooling
- OpenSearch/Elasticsearch: Audit log indexing and search
- S3: WORM-compliant archive storage
- Redis: Caching layer

Storage Tier Hierarchy (per AUDIT_LOG_STORAGE.md):
- Hot: PostgreSQL (7-day partition, full CRUD)
- Warm: OpenSearch (90-day retention, query-optimized)
- Cold: S3 WORM (7-year archive, immutable)
"""

from guideai.storage.opensearch_storage import (
    AuditEvent,
    AuditLogIndexer,
    AggregationResult,
    SearchResult,
    get_audit_indexer,
)
from guideai.storage.postgres_pool import PostgresPool
from guideai.storage.s3_worm_storage import S3WORMStorage

__all__ = [
    # OpenSearch
    "AuditEvent",
    "AuditLogIndexer",
    "AggregationResult",
    "SearchResult",
    "get_audit_indexer",
    # PostgreSQL
    "PostgresPool",
    # S3
    "S3WORMStorage",
]
