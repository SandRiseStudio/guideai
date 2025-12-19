-- Migration 019: Add weekly partitioning to audit_log_events
-- Implements time-based partitioning for efficient data management per AUDIT_LOG_STORAGE.md
-- Created: 2025-12-02
-- Purpose: Enable efficient archival and cleanup of audit logs by week

-- =============================================================================
-- Convert audit_log_events to partitioned table
-- =============================================================================
-- PostgreSQL native partitioning by RANGE on timestamp
-- Each partition covers one week of data

-- Step 1: Rename existing table (if upgrading existing deployment)
DO $$
BEGIN
    IF EXISTS (
        SELECT FROM pg_tables
        WHERE schemaname = 'public'
        AND tablename = 'audit_log_events'
        AND NOT EXISTS (
            SELECT FROM pg_partitioned_table pt
            JOIN pg_class c ON pt.partrelid = c.oid
            WHERE c.relname = 'audit_log_events'
        )
    ) THEN
        -- Table exists but is not partitioned - rename for migration
        ALTER TABLE audit_log_events RENAME TO audit_log_events_legacy;
    END IF;
END
$$;

-- Step 2: Create partitioned table (if not exists)
CREATE TABLE IF NOT EXISTS audit_log_events (
    -- Primary key (UUID v4)
    id TEXT NOT NULL,

    -- Timestamp (UTC) - partition key
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

    -- Hash chain links
    content_hash TEXT,
    previous_hash TEXT,

    -- Ed25519 signature
    signature TEXT,

    -- Archival tracking
    archived_at TIMESTAMPTZ,
    archive_key TEXT,

    -- Primary key must include partition key
    PRIMARY KEY (id, timestamp),

    -- Constraints
    CONSTRAINT valid_event_type_part CHECK (event_type ~ '^[a-z]+\.[a-z_]+$')
) PARTITION BY RANGE (timestamp);

-- =============================================================================
-- Create initial partitions (current week + 4 weeks future)
-- =============================================================================
-- Partitions are named audit_log_events_YYYY_WXX

-- Function to create weekly partitions
CREATE OR REPLACE FUNCTION create_audit_log_partition(partition_date DATE)
RETURNS TEXT AS $$
DECLARE
    week_start DATE;
    week_end DATE;
    partition_name TEXT;
BEGIN
    -- Calculate week boundaries (Monday to Sunday)
    week_start := date_trunc('week', partition_date)::DATE;
    week_end := week_start + INTERVAL '7 days';

    partition_name := 'audit_log_events_' ||
                      to_char(week_start, 'IYYY') || '_w' ||
                      to_char(week_start, 'IW');

    -- Create partition if it doesn't exist
    BEGIN
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF audit_log_events
             FOR VALUES FROM (%L) TO (%L)',
            partition_name,
            week_start,
            week_end
        );
        RETURN partition_name;
    EXCEPTION
        WHEN duplicate_table THEN
            RETURN partition_name;
    END;
END;
$$ LANGUAGE plpgsql;

-- Create partitions for current week and next 4 weeks
SELECT create_audit_log_partition(CURRENT_DATE);
SELECT create_audit_log_partition(CURRENT_DATE + INTERVAL '1 week');
SELECT create_audit_log_partition(CURRENT_DATE + INTERVAL '2 weeks');
SELECT create_audit_log_partition(CURRENT_DATE + INTERVAL '3 weeks');
SELECT create_audit_log_partition(CURRENT_DATE + INTERVAL '4 weeks');

-- Also create partitions for previous 4 weeks (for data migration)
SELECT create_audit_log_partition(CURRENT_DATE - INTERVAL '1 week');
SELECT create_audit_log_partition(CURRENT_DATE - INTERVAL '2 weeks');
SELECT create_audit_log_partition(CURRENT_DATE - INTERVAL '3 weeks');
SELECT create_audit_log_partition(CURRENT_DATE - INTERVAL '4 weeks');

-- =============================================================================
-- Automatic partition creation via pg_partman (optional)
-- =============================================================================
-- If pg_partman extension is available, set up automatic maintenance
-- Uncomment if pg_partman is installed:

-- CREATE EXTENSION IF NOT EXISTS pg_partman;
-- SELECT partman.create_parent(
--     p_parent_table := 'public.audit_log_events',
--     p_control := 'timestamp',
--     p_type := 'native',
--     p_interval := '1 week',
--     p_premake := 4
-- );
-- UPDATE partman.part_config SET
--     retention := '30 days',
--     retention_keep_table := TRUE  -- Keep tables for archival
-- WHERE parent_table = 'public.audit_log_events';

-- =============================================================================
-- Migration job: Move data from legacy table if exists
-- =============================================================================
DO $$
DECLARE
    batch_size INTEGER := 10000;
    migrated INTEGER := 0;
    total INTEGER;
BEGIN
    IF EXISTS (SELECT FROM pg_tables WHERE tablename = 'audit_log_events_legacy') THEN
        SELECT COUNT(*) INTO total FROM audit_log_events_legacy;
        RAISE NOTICE 'Migrating % records from legacy table...', total;

        -- Insert in batches to avoid long locks
        WHILE EXISTS (SELECT 1 FROM audit_log_events_legacy LIMIT 1) LOOP
            WITH moved AS (
                DELETE FROM audit_log_events_legacy
                WHERE id IN (
                    SELECT id FROM audit_log_events_legacy
                    ORDER BY timestamp
                    LIMIT batch_size
                )
                RETURNING *
            )
            INSERT INTO audit_log_events
            SELECT * FROM moved;

            GET DIAGNOSTICS migrated = ROW_COUNT;
            RAISE NOTICE 'Migrated % records', migrated;

            -- Commit each batch
            COMMIT;
        END LOOP;

        -- Drop legacy table after successful migration
        DROP TABLE IF EXISTS audit_log_events_legacy;
        RAISE NOTICE 'Migration complete, legacy table dropped';
    END IF;
END
$$;

-- =============================================================================
-- Indexes on partitioned table
-- =============================================================================
-- Indexes are created on the parent and automatically inherited by partitions

CREATE INDEX IF NOT EXISTS idx_audit_part_actor
    ON audit_log_events (actor_id, timestamp DESC)
    WHERE actor_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_audit_part_resource
    ON audit_log_events (resource_type, resource_id, timestamp DESC)
    WHERE resource_type IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_audit_part_type
    ON audit_log_events (event_type, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_part_run
    ON audit_log_events (run_id, timestamp DESC)
    WHERE run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_audit_part_hash_chain
    ON audit_log_events (content_hash, previous_hash)
    WHERE content_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_audit_part_archival
    ON audit_log_events (timestamp)
    WHERE archived_at IS NULL;

-- =============================================================================
-- Helper function to archive and detach old partitions
-- =============================================================================
CREATE OR REPLACE FUNCTION archive_old_audit_partitions(
    retention_days INTEGER DEFAULT 30
)
RETURNS TABLE (partition_name TEXT, status TEXT) AS $$
DECLARE
    p RECORD;
    cutoff_date DATE;
BEGIN
    cutoff_date := CURRENT_DATE - (retention_days || ' days')::INTERVAL;

    FOR p IN
        SELECT pt.relname AS partition_name,
               pg_get_expr(pt.relpartbound, pt.oid) AS bounds
        FROM pg_class pt
        JOIN pg_inherits i ON i.inhrelid = pt.oid
        JOIN pg_class parent ON i.inhparent = parent.oid
        WHERE parent.relname = 'audit_log_events'
        AND pt.relname LIKE 'audit_log_events_%'
    LOOP
        -- Check if partition is older than retention period
        -- This is a simplified check - production should parse bounds properly
        IF p.partition_name < ('audit_log_events_' || to_char(cutoff_date, 'IYYY_"w"IW')) THEN
            -- Detach partition (keeps data for archival)
            EXECUTE format('ALTER TABLE audit_log_events DETACH PARTITION %I', p.partition_name);
            partition_name := p.partition_name;
            status := 'detached';
            RETURN NEXT;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Scheduled partition maintenance (run daily via pg_cron or external scheduler)
-- =============================================================================
-- This function creates upcoming partitions and identifies old ones for archival

CREATE OR REPLACE FUNCTION maintain_audit_partitions(
    premake_weeks INTEGER DEFAULT 4,
    retention_days INTEGER DEFAULT 30
)
RETURNS TABLE (action TEXT, partition_name TEXT) AS $$
DECLARE
    i INTEGER;
BEGIN
    -- Create future partitions
    FOR i IN 0..premake_weeks LOOP
        action := 'created';
        partition_name := create_audit_log_partition(CURRENT_DATE + (i || ' weeks')::INTERVAL);
        RETURN NEXT;
    END LOOP;

    -- Report partitions ready for archival (but don't detach automatically)
    FOR partition_name IN
        SELECT pt.relname
        FROM pg_class pt
        JOIN pg_inherits i ON i.inhrelid = pt.oid
        JOIN pg_class parent ON i.inhparent = parent.oid
        WHERE parent.relname = 'audit_log_events'
        AND pt.relname < ('audit_log_events_' || to_char(CURRENT_DATE - (retention_days || ' days')::INTERVAL, 'IYYY_"w"IW'))
    LOOP
        action := 'ready_for_archive';
        RETURN NEXT;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Grant permissions
-- =============================================================================
GRANT INSERT ON audit_log_events TO audit_writer;
GRANT SELECT ON audit_log_events TO audit_writer;
GRANT SELECT ON audit_log_events TO audit_reader;

-- Grant execute on maintenance functions to appropriate roles
GRANT EXECUTE ON FUNCTION create_audit_log_partition(DATE) TO audit_writer;
GRANT EXECUTE ON FUNCTION maintain_audit_partitions(INTEGER, INTEGER) TO audit_writer;

-- =============================================================================
-- Comments
-- =============================================================================
COMMENT ON TABLE audit_log_events IS 'Partitioned audit log events (weekly partitions, INSERT-only)';
COMMENT ON FUNCTION create_audit_log_partition(DATE) IS 'Create a weekly partition for the given date';
COMMENT ON FUNCTION maintain_audit_partitions(INTEGER, INTEGER) IS 'Scheduled maintenance: create future partitions, identify old ones for archival';
COMMENT ON FUNCTION archive_old_audit_partitions(INTEGER) IS 'Detach partitions older than retention period for archival to S3';
