-- Migration: 024_add_org_id_to_behavior_tables.sql
-- Description: Add org_id column and RLS policies to behavior service tables
-- Date: 2025-12-04
-- Behavior: behavior_migrate_postgres_schema
--
-- This migration adds multi-tenant support to the behavior service tables:
--   - behaviors
--   - behavior_versions
--
-- IMPORTANT: Legacy data (pre-multi-tenant) is NOT migrated.
-- Existing rows without org_id will have NULL org_id and will be excluded
-- from RLS queries. This data is considered archived/legacy.
--
-- NOTE: org_id does NOT have FK to organizations table because organizations
-- live in a separate database. Referential integrity is maintained at the
-- application layer via OrganizationService.
--
-- RLS Strategy:
--   - org_id column is NULLABLE to preserve legacy data
--   - RLS policies require org_id = current_org_id() OR org_id IS NULL for read
--   - New inserts MUST have org_id (enforced by application layer)
--
-- Rollback steps documented at bottom of file

BEGIN;

-- =============================================================================
-- HELPER FUNCTION: Get current org_id from session variable
-- =============================================================================
-- This function is also defined in migration 023 for the orchestrator database.
-- We define it here as well because the behavior database is separate and needs
-- its own copy of the function for RLS policies to work.

CREATE OR REPLACE FUNCTION current_org_id() RETURNS TEXT AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_org_id', true), '');
EXCEPTION
    WHEN undefined_object THEN
        RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION current_org_id() IS 'Returns current tenant org_id from session variable for RLS policies';

-- =============================================================================
-- BEHAVIORS TABLE
-- =============================================================================

-- Add org_id column (no FK - cross-database reference)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'behaviors' AND column_name = 'org_id'
    ) THEN
        ALTER TABLE behaviors ADD COLUMN org_id VARCHAR(36);
    END IF;
END $$;

-- Create index for efficient filtering
CREATE INDEX IF NOT EXISTS idx_behaviors_org ON behaviors(org_id) WHERE org_id IS NOT NULL;

-- Enable RLS
ALTER TABLE behaviors ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Access behaviors in current org OR legacy data (NULL org_id)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'behaviors' AND policyname = 'behaviors_tenant_isolation'
    ) THEN
        CREATE POLICY behaviors_tenant_isolation ON behaviors
            FOR ALL
            USING (
                org_id = current_org_id()
                OR org_id IS NULL  -- Legacy data readable by all (archived)
            );
    END IF;
END $$;

COMMENT ON COLUMN behaviors.org_id IS 'Organization ID for multi-tenant isolation. NULL = legacy/archived data.';

-- =============================================================================
-- BEHAVIOR_VERSIONS TABLE
-- =============================================================================

-- Add org_id column (no FK - cross-database reference)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'behavior_versions' AND column_name = 'org_id'
    ) THEN
        ALTER TABLE behavior_versions ADD COLUMN org_id VARCHAR(36);
    END IF;
END $$;

-- Create index
CREATE INDEX IF NOT EXISTS idx_behavior_versions_org ON behavior_versions(org_id) WHERE org_id IS NOT NULL;

-- Enable RLS
ALTER TABLE behavior_versions ENABLE ROW LEVEL SECURITY;

-- RLS Policy
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'behavior_versions' AND policyname = 'behavior_versions_tenant_isolation'
    ) THEN
        CREATE POLICY behavior_versions_tenant_isolation ON behavior_versions
            FOR ALL
            USING (
                org_id = current_org_id()
                OR org_id IS NULL
            );
    END IF;
END $$;

COMMENT ON COLUMN behavior_versions.org_id IS 'Organization ID for multi-tenant isolation. NULL = legacy/archived data.';

-- =============================================================================
-- BEHAVIOR_EMBEDDINGS TABLE (if exists)
-- =============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'behavior_embeddings') THEN
        -- Add org_id column
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'behavior_embeddings' AND column_name = 'org_id'
        ) THEN
            ALTER TABLE behavior_embeddings ADD COLUMN org_id VARCHAR(36);
        END IF;

        -- Create index
        CREATE INDEX IF NOT EXISTS idx_behavior_embeddings_org
            ON behavior_embeddings(org_id) WHERE org_id IS NOT NULL;

        -- Enable RLS
        ALTER TABLE behavior_embeddings ENABLE ROW LEVEL SECURITY;

        -- RLS Policy
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE tablename = 'behavior_embeddings' AND policyname = 'behavior_embeddings_tenant_isolation'
        ) THEN
            CREATE POLICY behavior_embeddings_tenant_isolation ON behavior_embeddings
                FOR ALL
                USING (
                    org_id = current_org_id()
                    OR org_id IS NULL
                );
        END IF;
    END IF;
END $$;

-- =============================================================================
-- BEHAVIOR_EFFECTIVENESS TABLE (if exists)
-- =============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'behavior_effectiveness') THEN
        -- Add org_id column
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'behavior_effectiveness' AND column_name = 'org_id'
        ) THEN
            ALTER TABLE behavior_effectiveness ADD COLUMN org_id VARCHAR(36);
        END IF;

        -- Create index
        CREATE INDEX IF NOT EXISTS idx_behavior_effectiveness_org
            ON behavior_effectiveness(org_id) WHERE org_id IS NOT NULL;

        -- Enable RLS
        ALTER TABLE behavior_effectiveness ENABLE ROW LEVEL SECURITY;

        -- RLS Policy
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
            WHERE tablename = 'behavior_effectiveness' AND policyname = 'behavior_effectiveness_tenant_isolation'
        ) THEN
            CREATE POLICY behavior_effectiveness_tenant_isolation ON behavior_effectiveness
                FOR ALL
                USING (
                    org_id = current_org_id()
                    OR org_id IS NULL
                );
        END IF;
    END IF;
END $$;

COMMIT;

-- =============================================================================
-- ROLLBACK INSTRUCTIONS
-- =============================================================================
-- To rollback this migration:
--
-- DROP POLICY IF EXISTS behaviors_tenant_isolation ON behaviors;
-- DROP POLICY IF EXISTS behavior_versions_tenant_isolation ON behavior_versions;
-- DROP POLICY IF EXISTS behavior_embeddings_tenant_isolation ON behavior_embeddings;
-- DROP POLICY IF EXISTS behavior_effectiveness_tenant_isolation ON behavior_effectiveness;
--
-- ALTER TABLE behaviors DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE behavior_versions DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE behavior_embeddings DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE behavior_effectiveness DISABLE ROW LEVEL SECURITY;
--
-- DROP INDEX IF EXISTS idx_behaviors_org;
-- DROP INDEX IF EXISTS idx_behavior_versions_org;
-- DROP INDEX IF EXISTS idx_behavior_embeddings_org;
-- DROP INDEX IF EXISTS idx_behavior_effectiveness_org;
--
-- ALTER TABLE behaviors DROP COLUMN IF EXISTS org_id;
-- ALTER TABLE behavior_versions DROP COLUMN IF EXISTS org_id;
-- ALTER TABLE behavior_embeddings DROP COLUMN IF EXISTS org_id;
-- ALTER TABLE behavior_effectiveness DROP COLUMN IF EXISTS org_id;
