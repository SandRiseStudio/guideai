-- Migration 016: Audit Log WORM Storage schema
-- Implements hot-tier PostgreSQL storage for audit logs per AUDIT_LOG_STORAGE.md
-- Created: 2025-11-24
-- Purpose: Compliance-grade audit logging with INSERT-only policies and hash chain integrity

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Audit Log Events (Hot Tier)
-- =============================================================================
-- Events are INSERT-only; no UPDATE/DELETE allowed for compliance
-- Retention: 30 days in PostgreSQL, then archived to S3 with Object Lock

CREATE TABLE IF NOT EXISTS audit_log_events (
    -- Primary key (UUID v4)
    id TEXT PRIMARY KEY,

    -- Timestamp (UTC)
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Event classification
    event_type TEXT NOT NULL,

    -- Actor information
    actor_id TEXT,
    actor_type TEXT NOT NULL DEFAULT 'user' CHECK (actor_type IN ('user', 'service', 'system')),

    -- Resource being accessed/modified
    resource_type TEXT,
    resource_id TEXT,

    -- Action details
    action TEXT NOT NULL,
    outcome TEXT NOT NULL DEFAULT 'success' CHECK (outcome IN ('success', 'failure', 'error')),

    -- Client context
    client_ip INET,
    user_agent TEXT,
    session_id TEXT,
    run_id TEXT,

    -- Extensible details (JSON)
    details JSONB,

    -- Integrity hash (SHA-256 of event content)
    event_hash TEXT NOT NULL,

    -- Archival tracking
    archived_at TIMESTAMPTZ,
    archive_key TEXT,

    -- Constraints
    CONSTRAINT valid_event_type CHECK (event_type ~ '^[a-z]+\.[a-z_]+$')
);

-- Index for time-range queries (most common pattern)
CREATE INDEX IF NOT EXISTS idx_audit_log_events_timestamp
    ON audit_log_events (timestamp DESC);

-- Index for actor-based queries (compliance investigations)
CREATE INDEX IF NOT EXISTS idx_audit_log_events_actor
    ON audit_log_events (actor_id, timestamp DESC)
    WHERE actor_id IS NOT NULL;

-- Index for resource-based queries (data access auditing)
CREATE INDEX IF NOT EXISTS idx_audit_log_events_resource
    ON audit_log_events (resource_type, resource_id, timestamp DESC)
    WHERE resource_type IS NOT NULL;

-- Index for event type filtering
CREATE INDEX IF NOT EXISTS idx_audit_log_events_type
    ON audit_log_events (event_type, timestamp DESC);

-- Index for run correlation
CREATE INDEX IF NOT EXISTS idx_audit_log_events_run
    ON audit_log_events (run_id, timestamp DESC)
    WHERE run_id IS NOT NULL;

-- Index for archival cleanup (find unarchived events older than retention)
CREATE INDEX IF NOT EXISTS idx_audit_log_events_archival
    ON audit_log_events (timestamp)
    WHERE archived_at IS NULL;

-- =============================================================================
-- Audit Log Archives (S3 Archive Metadata)
-- =============================================================================
-- Tracks archives stored in S3 with Object Lock for chain verification

CREATE TABLE IF NOT EXISTS audit_log_archives (
    -- Archive identifier
    id SERIAL PRIMARY KEY,

    -- S3 location
    s3_key TEXT NOT NULL UNIQUE,
    version_id TEXT,

    -- Archive contents
    event_count INTEGER NOT NULL,
    start_timestamp TIMESTAMPTZ NOT NULL,
    end_timestamp TIMESTAMPTZ NOT NULL,

    -- Hash chain integrity
    archive_hash TEXT NOT NULL,
    previous_hash TEXT,

    -- Cryptographic signature (Ed25519 base64)
    signature TEXT,
    signing_key_id TEXT,

    -- Retention tracking
    retention_until TIMESTAMPTZ,
    legal_hold BOOLEAN NOT NULL DEFAULT FALSE,

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for hash chain traversal
CREATE INDEX IF NOT EXISTS idx_audit_log_archives_created
    ON audit_log_archives (created_at);

-- Index for finding archives by time range
CREATE INDEX IF NOT EXISTS idx_audit_log_archives_timestamps
    ON audit_log_archives (start_timestamp, end_timestamp);

-- =============================================================================
-- INSERT-Only Role for Audit Writers
-- =============================================================================
-- Create a role with INSERT-only permissions for compliance

DO $$
BEGIN
    -- Create role if it doesn't exist
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_writer') THEN
        CREATE ROLE audit_writer;
    END IF;
END
$$;

-- Grant INSERT-only on audit_log_events (no UPDATE, DELETE)
GRANT INSERT ON audit_log_events TO audit_writer;

-- Grant INSERT on audit_log_archives (for recording archive metadata)
GRANT INSERT ON audit_log_archives TO audit_writer;

-- Grant SELECT for verification queries
GRANT SELECT ON audit_log_events TO audit_writer;
GRANT SELECT ON audit_log_archives TO audit_writer;

-- Grant usage on sequences
GRANT USAGE ON SEQUENCE audit_log_archives_id_seq TO audit_writer;

-- =============================================================================
-- Audit Reader Role (for compliance queries)
-- =============================================================================
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'audit_reader') THEN
        CREATE ROLE audit_reader;
    END IF;
END
$$;

GRANT SELECT ON audit_log_events TO audit_reader;
GRANT SELECT ON audit_log_archives TO audit_reader;

-- =============================================================================
-- Prevent DELETE/UPDATE via Row Level Security (optional, requires enable)
-- =============================================================================
-- Uncomment to enable RLS for stricter enforcement:
-- ALTER TABLE audit_log_events ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY audit_events_insert_only ON audit_log_events
--     FOR ALL USING (FALSE)  -- No one can SELECT by default
--     WITH CHECK (TRUE);     -- But INSERTs are allowed
-- CREATE POLICY audit_events_select ON audit_log_events
--     FOR SELECT USING (TRUE);

-- =============================================================================
-- Comments
-- =============================================================================
COMMENT ON TABLE audit_log_events IS 'Immutable audit log events (INSERT-only hot tier, 30-day retention)';
COMMENT ON TABLE audit_log_archives IS 'S3 archive metadata with hash chain for WORM verification';
COMMENT ON COLUMN audit_log_events.event_hash IS 'SHA-256 hash of event content for integrity verification';
COMMENT ON COLUMN audit_log_archives.archive_hash IS 'SHA-256 hash of archive content';
COMMENT ON COLUMN audit_log_archives.previous_hash IS 'Hash of previous archive for chain verification';
COMMENT ON COLUMN audit_log_archives.signature IS 'Ed25519 signature (base64) for authenticity';
