-- Migration: 024_add_org_id_to_core_tables.sql
-- Description: Add org_id column and RLS policies to core service tables
-- Date: 2025-12-04
-- Behavior: behavior_migrate_postgres_schema
--
-- This migration adds multi-tenant support to existing core tables:
--   - behaviors, behavior_versions
--   - runs, run_steps
--   - actions, replays
--   - workflow_templates, workflow_runs
--   - checklists, compliance_policies
--
-- IMPORTANT: Legacy data (pre-multi-tenant) is NOT migrated.
-- Existing rows without org_id will have NULL org_id and will be excluded
-- from RLS queries. This data is considered archived/legacy.
--
-- RLS Strategy:
--   - org_id column is NULLABLE to preserve legacy data
--   - RLS policies require org_id = current_org_id() OR org_id IS NULL for read
--   - New inserts MUST have org_id (enforced by application layer)
--
-- Rollback steps documented at bottom of file

BEGIN;

-- =============================================================================
-- BEHAVIORS TABLE
-- =============================================================================

ALTER TABLE behaviors
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(org_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_behaviors_org ON behaviors(org_id) WHERE org_id IS NOT NULL;

-- Enable RLS
ALTER TABLE behaviors ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Access behaviors in current org OR legacy data (NULL org_id)
CREATE POLICY behaviors_tenant_isolation ON behaviors
    FOR ALL
    USING (
        org_id = current_org_id()
        OR org_id IS NULL  -- Legacy data readable by all (archived)
    );

COMMENT ON COLUMN behaviors.org_id IS 'Organization ID for multi-tenant isolation. NULL = legacy/archived data.';

-- =============================================================================
-- BEHAVIOR_VERSIONS TABLE
-- =============================================================================

-- behavior_versions inherits org_id from parent via JOIN, no need to duplicate
-- But for RLS to work efficiently, we add the column

ALTER TABLE behavior_versions
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(org_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_behavior_versions_org ON behavior_versions(org_id) WHERE org_id IS NOT NULL;

-- Enable RLS
ALTER TABLE behavior_versions ENABLE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY behavior_versions_tenant_isolation ON behavior_versions
    FOR ALL
    USING (
        org_id = current_org_id()
        OR org_id IS NULL
    );

-- =============================================================================
-- RUNS TABLE
-- =============================================================================

ALTER TABLE runs
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(org_id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS project_id VARCHAR(36) REFERENCES projects(project_id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS agent_id VARCHAR(36) REFERENCES agents(agent_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_runs_org ON runs(org_id) WHERE org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_runs_project ON runs(project_id) WHERE project_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_runs_agent ON runs(agent_id) WHERE agent_id IS NOT NULL;

-- Enable RLS
ALTER TABLE runs ENABLE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY runs_tenant_isolation ON runs
    FOR ALL
    USING (
        org_id = current_org_id()
        OR org_id IS NULL
    );

COMMENT ON COLUMN runs.project_id IS 'Optional project scope for the run';
COMMENT ON COLUMN runs.agent_id IS 'Agent that executed this run (if agent-driven)';

-- =============================================================================
-- RUN_STEPS TABLE
-- =============================================================================

ALTER TABLE run_steps
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(org_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_run_steps_org ON run_steps(org_id) WHERE org_id IS NOT NULL;

-- Enable RLS
ALTER TABLE run_steps ENABLE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY run_steps_tenant_isolation ON run_steps
    FOR ALL
    USING (
        org_id = current_org_id()
        OR org_id IS NULL
    );

-- =============================================================================
-- ACTIONS TABLE
-- =============================================================================

ALTER TABLE actions
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(org_id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS project_id VARCHAR(36) REFERENCES projects(project_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_actions_org ON actions(org_id) WHERE org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_actions_project ON actions(project_id) WHERE project_id IS NOT NULL;

-- Enable RLS
ALTER TABLE actions ENABLE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY actions_tenant_isolation ON actions
    FOR ALL
    USING (
        org_id = current_org_id()
        OR org_id IS NULL
    );

-- =============================================================================
-- REPLAYS TABLE
-- =============================================================================

ALTER TABLE replays
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(org_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_replays_org ON replays(org_id) WHERE org_id IS NOT NULL;

-- Enable RLS
ALTER TABLE replays ENABLE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY replays_tenant_isolation ON replays
    FOR ALL
    USING (
        org_id = current_org_id()
        OR org_id IS NULL
    );

-- =============================================================================
-- WORKFLOW_TEMPLATES TABLE
-- =============================================================================

ALTER TABLE workflow_templates
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(org_id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS project_id VARCHAR(36) REFERENCES projects(project_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_workflow_templates_org ON workflow_templates(org_id) WHERE org_id IS NOT NULL;

-- Enable RLS
ALTER TABLE workflow_templates ENABLE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY workflow_templates_tenant_isolation ON workflow_templates
    FOR ALL
    USING (
        org_id = current_org_id()
        OR org_id IS NULL
    );

-- =============================================================================
-- WORKFLOW_RUNS TABLE
-- =============================================================================

ALTER TABLE workflow_runs
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(org_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_workflow_runs_org ON workflow_runs(org_id) WHERE org_id IS NOT NULL;

-- Enable RLS
ALTER TABLE workflow_runs ENABLE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY workflow_runs_tenant_isolation ON workflow_runs
    FOR ALL
    USING (
        org_id = current_org_id()
        OR org_id IS NULL
    );

-- =============================================================================
-- CHECKLISTS TABLE
-- =============================================================================

ALTER TABLE checklists
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(org_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_checklists_org ON checklists(org_id) WHERE org_id IS NOT NULL;

-- Enable RLS
ALTER TABLE checklists ENABLE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY checklists_tenant_isolation ON checklists
    FOR ALL
    USING (
        org_id = current_org_id()
        OR org_id IS NULL
    );

-- =============================================================================
-- COMPLIANCE_POLICIES TABLE
-- =============================================================================

ALTER TABLE compliance_policies
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36) REFERENCES organizations(org_id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_compliance_policies_org ON compliance_policies(org_id) WHERE org_id IS NOT NULL;

-- Enable RLS
ALTER TABLE compliance_policies ENABLE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY compliance_policies_tenant_isolation ON compliance_policies
    FOR ALL
    USING (
        org_id = current_org_id()
        OR org_id IS NULL
    );

-- =============================================================================
-- TELEMETRY_EVENTS TABLE
-- =============================================================================

ALTER TABLE telemetry_events
    ADD COLUMN IF NOT EXISTS org_id VARCHAR(36);  -- No FK to avoid cross-schema issues with TimescaleDB

CREATE INDEX IF NOT EXISTS idx_telemetry_events_org ON telemetry_events(org_id) WHERE org_id IS NOT NULL;

-- Note: RLS on hypertables requires careful handling - enable only if needed
-- For now, telemetry filtering is done at application layer

-- =============================================================================
-- AUDIT_LOG_EVENTS TABLE (if exists)
-- =============================================================================

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'audit_log_events') THEN
        ALTER TABLE audit_log_events
            ADD COLUMN IF NOT EXISTS org_id VARCHAR(36);

        CREATE INDEX IF NOT EXISTS idx_audit_log_events_org ON audit_log_events(org_id) WHERE org_id IS NOT NULL;
    END IF;
END $$;

-- =============================================================================
-- UPDATE current_org_id() TO HANDLE SUPERUSER BYPASS
-- =============================================================================

CREATE OR REPLACE FUNCTION current_org_id() RETURNS TEXT AS $$
BEGIN
    -- Superusers can bypass RLS, but we still want to track context
    RETURN NULLIF(current_setting('app.current_org_id', true), '');
EXCEPTION
    WHEN undefined_object THEN
        RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

-- =============================================================================
-- HELPER FUNCTION: Set current org context (for use in application)
-- =============================================================================

CREATE OR REPLACE FUNCTION set_current_org(p_org_id TEXT) RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.current_org_id', COALESCE(p_org_id, ''), false);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION set_current_org(TEXT) IS 'Sets the current org context for RLS policies. Call at start of each request.';

-- =============================================================================
-- HELPER FUNCTION: Clear org context
-- =============================================================================

CREATE OR REPLACE FUNCTION clear_current_org() RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.current_org_id', '', false);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION clear_current_org() IS 'Clears the current org context';

COMMIT;

-- =============================================================================
-- ROLLBACK INSTRUCTIONS
-- =============================================================================
-- To rollback this migration, run these commands in order:
--
-- DROP POLICY IF EXISTS behaviors_tenant_isolation ON behaviors;
-- DROP POLICY IF EXISTS behavior_versions_tenant_isolation ON behavior_versions;
-- DROP POLICY IF EXISTS runs_tenant_isolation ON runs;
-- DROP POLICY IF EXISTS run_steps_tenant_isolation ON run_steps;
-- DROP POLICY IF EXISTS actions_tenant_isolation ON actions;
-- DROP POLICY IF EXISTS replays_tenant_isolation ON replays;
-- DROP POLICY IF EXISTS workflow_templates_tenant_isolation ON workflow_templates;
-- DROP POLICY IF EXISTS workflow_runs_tenant_isolation ON workflow_runs;
-- DROP POLICY IF EXISTS checklists_tenant_isolation ON checklists;
-- DROP POLICY IF EXISTS compliance_policies_tenant_isolation ON compliance_policies;
--
-- ALTER TABLE behaviors DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE behavior_versions DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE runs DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE run_steps DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE actions DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE replays DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE workflow_templates DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE workflow_runs DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE checklists DISABLE ROW LEVEL SECURITY;
-- ALTER TABLE compliance_policies DISABLE ROW LEVEL SECURITY;
--
-- ALTER TABLE behaviors DROP COLUMN IF EXISTS org_id;
-- ... (repeat for all tables)
