-- Migration: 025_optional_organizations.sql
-- Description: Make organizations optional - support user-owned projects/agents
-- Date: 2025-12-08
-- Behavior: behavior_migrate_postgres_schema
--
-- This migration enables resources (projects, agents) to be either:
--   1. Org-owned: org_id is set (existing behavior)
--   2. User-owned: owner_id is set (new - personal projects without org)
--
-- Key Changes:
--   - Add owner_id column to projects, agents
--   - Make org_id nullable on projects, agents
--   - Add CHECK constraint enforcing XOR (org_id OR owner_id, not both)
--   - Add project_collaborators table for sharing personal projects
--   - Update subscriptions to support user-level billing
--   - Update usage_records to support user-level tracking
--   - Update RLS policies for owner_id access pattern
--
-- Migration Strategy:
--   - Existing data remains org-owned (org_id set, owner_id NULL)
--   - New records can be either org-owned or user-owned
--
-- Rollback: See END of file for rollback commands

BEGIN;

-- =============================================================================
-- HELPER FUNCTION: Get current user_id from session variable
-- =============================================================================

CREATE OR REPLACE FUNCTION current_user_id() RETURNS TEXT AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_user_id', true), '');
EXCEPTION
    WHEN undefined_object THEN
        RETURN NULL;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION current_user_id() IS 'Returns current user_id from session variable for RLS policies on user-owned resources';

-- =============================================================================
-- PROJECTS TABLE: Add owner_id, make org_id nullable
-- =============================================================================

-- Add owner_id column for user-owned projects
ALTER TABLE projects ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36);

-- Make org_id nullable (existing data keeps org_id, new can use either)
ALTER TABLE projects ALTER COLUMN org_id DROP NOT NULL;

-- Add CHECK constraint: exactly one of org_id or owner_id must be set (XOR)
-- This allows existing org-owned data while enabling user-owned projects
ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_ownership_xor;
ALTER TABLE projects ADD CONSTRAINT projects_ownership_xor
    CHECK (
        (org_id IS NOT NULL AND owner_id IS NULL) OR
        (org_id IS NULL AND owner_id IS NOT NULL)
    );

-- Index for owner_id queries
CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id) WHERE owner_id IS NOT NULL;

-- Drop existing RLS policy and create new one supporting both ownership types
DROP POLICY IF EXISTS projects_tenant_isolation ON projects;
CREATE POLICY projects_tenant_isolation ON projects
    FOR ALL
    USING (
        org_id = current_org_id() OR  -- Org-owned: user in org context
        owner_id = current_user_id()   -- User-owned: user owns the project
    );

COMMENT ON COLUMN projects.owner_id IS 'User ID for personal projects (mutually exclusive with org_id)';

-- =============================================================================
-- PROJECT COLLABORATORS TABLE: Share personal projects without orgs
-- =============================================================================

CREATE TABLE IF NOT EXISTS project_collaborators (
    collaborator_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL,  -- The collaborator
    role project_role NOT NULL DEFAULT 'contributor',

    -- Invitation tracking
    invited_by VARCHAR(36) NOT NULL,  -- User who sent the invite
    invited_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_at TIMESTAMPTZ,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint: one invitation per user per project
    CONSTRAINT unique_project_collaborator UNIQUE (project_id, user_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_project_collaborators_project ON project_collaborators(project_id);
CREATE INDEX IF NOT EXISTS idx_project_collaborators_user ON project_collaborators(user_id);
CREATE INDEX IF NOT EXISTS idx_project_collaborators_pending ON project_collaborators(user_id) WHERE accepted_at IS NULL;

-- Enable RLS
ALTER TABLE project_collaborators ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can see collaborations for projects they own or are part of
CREATE POLICY project_collaborators_access ON project_collaborators
    FOR ALL
    USING (
        -- Project owner can manage collaborators
        project_id IN (SELECT project_id FROM projects WHERE owner_id = current_user_id())
        OR
        -- Collaborator can see their own membership
        user_id = current_user_id()
    );

-- Auto-update trigger
CREATE OR REPLACE FUNCTION update_project_collaborators_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_project_collaborators_updated_at ON project_collaborators;
CREATE TRIGGER trigger_project_collaborators_updated_at
    BEFORE UPDATE ON project_collaborators
    FOR EACH ROW
    EXECUTE FUNCTION update_project_collaborators_updated_at();

COMMENT ON TABLE project_collaborators IS 'Collaborators on user-owned projects (personal project sharing without orgs)';

-- Update projects RLS to include collaborators
DROP POLICY IF EXISTS projects_tenant_isolation ON projects;
CREATE POLICY projects_tenant_isolation ON projects
    FOR ALL
    USING (
        org_id = current_org_id() OR  -- Org-owned: user in org context
        owner_id = current_user_id() OR  -- User-owned: user owns the project
        project_id IN (  -- User is a collaborator on this project
            SELECT project_id FROM project_collaborators
            WHERE user_id = current_user_id() AND accepted_at IS NOT NULL
        )
    );

-- =============================================================================
-- AGENTS TABLE: Add owner_id, make org_id nullable
-- =============================================================================

-- Add owner_id column for user-owned agents
ALTER TABLE agents ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36);

-- Make org_id nullable
ALTER TABLE agents ALTER COLUMN org_id DROP NOT NULL;

-- Add CHECK constraint: exactly one of org_id or owner_id must be set (XOR)
ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_ownership_xor;
ALTER TABLE agents ADD CONSTRAINT agents_ownership_xor
    CHECK (
        (org_id IS NOT NULL AND owner_id IS NULL) OR
        (org_id IS NULL AND owner_id IS NOT NULL)
    );

-- Index for owner_id queries
CREATE INDEX IF NOT EXISTS idx_agents_owner ON agents(owner_id) WHERE owner_id IS NOT NULL;

-- Drop existing RLS policy and create new one supporting both ownership types
DROP POLICY IF EXISTS agents_tenant_isolation ON agents;
CREATE POLICY agents_tenant_isolation ON agents
    FOR ALL
    USING (
        org_id = current_org_id() OR  -- Org-owned: user in org context
        owner_id = current_user_id()   -- User-owned: user owns the agent
    );

COMMENT ON COLUMN agents.owner_id IS 'User ID for personal agents (mutually exclusive with org_id)';

-- =============================================================================
-- SUBSCRIPTIONS TABLE: Support user-level subscriptions
-- =============================================================================

-- Add user_id column for user-level subscriptions
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS user_id VARCHAR(36);

-- Make org_id nullable
ALTER TABLE subscriptions ALTER COLUMN org_id DROP NOT NULL;

-- Add CHECK constraint: exactly one of org_id or user_id must be set (XOR)
ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS subscriptions_owner_xor;
ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_owner_xor
    CHECK (
        (org_id IS NOT NULL AND user_id IS NULL) OR
        (org_id IS NULL AND user_id IS NOT NULL)
    );

-- Update unique constraint to allow both org and user subscriptions
ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS unique_org_subscription;
-- One subscription per org OR per user
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_unique_org ON subscriptions(org_id) WHERE org_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_unique_user ON subscriptions(user_id) WHERE user_id IS NOT NULL;

-- Index for user queries
CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id) WHERE user_id IS NOT NULL;

-- Drop existing RLS policy and create new one
DROP POLICY IF EXISTS subscriptions_tenant_isolation ON subscriptions;
CREATE POLICY subscriptions_tenant_isolation ON subscriptions
    FOR ALL
    USING (
        org_id = current_org_id() OR  -- Org subscription in org context
        user_id = current_user_id()   -- User's personal subscription
    );

COMMENT ON COLUMN subscriptions.user_id IS 'User ID for personal subscriptions (mutually exclusive with org_id)';

-- =============================================================================
-- USAGE_RECORDS TABLE: Support user-level usage tracking
-- =============================================================================

-- Add user_id column for user-level usage
ALTER TABLE usage_records ADD COLUMN IF NOT EXISTS user_id VARCHAR(36);

-- Make org_id nullable
ALTER TABLE usage_records ALTER COLUMN org_id DROP NOT NULL;

-- Add CHECK constraint: at least one must be set
-- Note: Unlike others, usage CAN have both (user working in org context)
ALTER TABLE usage_records DROP CONSTRAINT IF EXISTS usage_records_owner_check;
ALTER TABLE usage_records ADD CONSTRAINT usage_records_owner_check
    CHECK (org_id IS NOT NULL OR user_id IS NOT NULL);

-- Index for user queries
CREATE INDEX IF NOT EXISTS idx_usage_records_user ON usage_records(user_id) WHERE user_id IS NOT NULL;

-- Drop existing RLS policy and create new one
DROP POLICY IF EXISTS usage_records_tenant_isolation ON usage_records;
CREATE POLICY usage_records_tenant_isolation ON usage_records
    FOR ALL
    USING (
        org_id = current_org_id() OR  -- Org usage in org context
        user_id = current_user_id()   -- User's personal usage
    );

COMMENT ON COLUMN usage_records.user_id IS 'User ID for usage tracking (can coexist with org_id)';

-- =============================================================================
-- UPDATE PROJECT_MEMBERSHIPS RLS for collaborator access
-- =============================================================================

DROP POLICY IF EXISTS project_memberships_tenant_isolation ON project_memberships;
CREATE POLICY project_memberships_tenant_isolation ON project_memberships
    FOR ALL
    USING (
        -- Org project memberships (existing)
        project_id IN (SELECT project_id FROM projects WHERE org_id = current_org_id())
        OR
        -- User-owned project memberships (new)
        project_id IN (SELECT project_id FROM projects WHERE owner_id = current_user_id())
        OR
        -- User is a collaborator
        project_id IN (
            SELECT project_id FROM project_collaborators
            WHERE user_id = current_user_id() AND accepted_at IS NOT NULL
        )
    );

-- =============================================================================
-- BILLING RESOLUTION VIEW (for subscription priority logic)
-- =============================================================================

-- View to help resolve which subscription to use for a user
CREATE OR REPLACE VIEW user_billing_context AS
SELECT
    u.user_id,
    -- User's own subscription (for personal projects)
    us.subscription_id AS user_subscription_id,
    us.plan AS user_plan,
    us.status AS user_status,
    -- Check if user has any org memberships
    EXISTS(
        SELECT 1 FROM org_memberships om
        WHERE om.user_id = u.user_id AND om.is_active = TRUE
    ) AS has_org_membership
FROM (SELECT DISTINCT user_id FROM org_memberships) u
LEFT JOIN subscriptions us ON us.user_id = u.user_id;

COMMENT ON VIEW user_billing_context IS 'Helper view for resolving user billing context (org vs personal subscription)';

-- =============================================================================
-- GRANT PERMISSIONS
-- =============================================================================

-- Note: Grant permissions as needed for your database roles
-- GRANT SELECT, INSERT, UPDATE, DELETE ON project_collaborators TO your_service_role;

COMMIT;

-- =============================================================================
-- ROLLBACK COMMANDS (run manually if needed)
-- =============================================================================
-- DROP VIEW IF EXISTS user_billing_context;
-- DROP TRIGGER IF EXISTS trigger_project_collaborators_updated_at ON project_collaborators;
-- DROP FUNCTION IF EXISTS update_project_collaborators_updated_at();
-- DROP TABLE IF EXISTS project_collaborators;
--
-- ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_ownership_xor;
-- ALTER TABLE projects DROP COLUMN IF EXISTS owner_id;
-- ALTER TABLE projects ALTER COLUMN org_id SET NOT NULL;
-- DROP INDEX IF EXISTS idx_projects_owner;
--
-- ALTER TABLE agents DROP CONSTRAINT IF EXISTS agents_ownership_xor;
-- ALTER TABLE agents DROP COLUMN IF EXISTS owner_id;
-- ALTER TABLE agents ALTER COLUMN org_id SET NOT NULL;
-- DROP INDEX IF EXISTS idx_agents_owner;
--
-- ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS subscriptions_owner_xor;
-- ALTER TABLE subscriptions DROP COLUMN IF EXISTS user_id;
-- ALTER TABLE subscriptions ALTER COLUMN org_id SET NOT NULL;
-- DROP INDEX IF EXISTS idx_subscriptions_unique_org;
-- DROP INDEX IF EXISTS idx_subscriptions_unique_user;
-- DROP INDEX IF EXISTS idx_subscriptions_user;
--
-- ALTER TABLE usage_records DROP CONSTRAINT IF EXISTS usage_records_owner_check;
-- ALTER TABLE usage_records DROP COLUMN IF EXISTS user_id;
-- ALTER TABLE usage_records ALTER COLUMN org_id SET NOT NULL;
-- DROP INDEX IF EXISTS idx_usage_records_user;
--
-- DROP FUNCTION IF EXISTS current_user_id();
