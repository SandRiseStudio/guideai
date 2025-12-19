-- Migration: 023_create_organizations.sql
-- Description: Create multi-tenant organization tables with Row-Level Security (RLS)
-- Date: 2025-12-04
-- Behavior: behavior_migrate_postgres_schema
--
-- This migration creates the foundation for multi-tenancy in GuideAI using
-- PostgreSQL Row-Level Security (RLS) for tenant isolation.
--
-- Key Design Decisions:
--   1. RLS over schema-per-tenant for simpler operations and single connection pool
--   2. Organizations own projects, memberships, and agents
--   3. Legacy data (pre-multi-tenant) will NOT be migrated - treated as archived
--   4. Org context passed via session variable: SET app.current_org_id = 'xxx'
--
-- Tables:
--   - organizations: Top-level tenant entity with billing and limits
--   - org_memberships: User membership in organizations with roles
--   - projects: Workspaces within organizations
--   - project_memberships: User access to specific projects
--   - agents: First-class AI agent identities
--
-- Rollback: DROP TABLE IF EXISTS agents, project_memberships, projects, org_memberships, organizations CASCADE;

BEGIN;

-- =============================================================================
-- HELPER FUNCTION: Get current org_id from session variable
-- =============================================================================

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
-- ORGANIZATIONS TABLE
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE org_plan AS ENUM ('free', 'starter', 'team', 'enterprise');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE org_status AS ENUM ('active', 'suspended', 'archived', 'pending', 'deleted');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS organizations (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    display_name TEXT,  -- Human-friendly name (distinct from slug)
    plan org_plan NOT NULL DEFAULT 'free',
    status org_status NOT NULL DEFAULT 'pending',

    -- Settings and limits
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    max_projects INT NOT NULL DEFAULT 3,
    max_members INT NOT NULL DEFAULT 5,
    max_agents INT NOT NULL DEFAULT 1,
    monthly_token_budget BIGINT NOT NULL DEFAULT 100000,

    -- Billing (Stripe integration)
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,

    -- Metadata
    created_by VARCHAR(36),  -- user_id who created the org
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_organizations_slug ON organizations(slug);
CREATE INDEX IF NOT EXISTS idx_organizations_status ON organizations(status) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_organizations_plan ON organizations(plan);
CREATE INDEX IF NOT EXISTS idx_organizations_stripe ON organizations(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;

-- Auto-update trigger
CREATE OR REPLACE FUNCTION update_organizations_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_organizations_updated_at ON organizations;
CREATE TRIGGER trigger_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW
    EXECUTE FUNCTION update_organizations_updated_at();

COMMENT ON TABLE organizations IS 'Top-level tenant entity for multi-tenant isolation';
COMMENT ON COLUMN organizations.slug IS 'URL-friendly identifier (e.g., acme-corp)';
COMMENT ON COLUMN organizations.monthly_token_budget IS 'LLM token budget per month based on plan';

-- =============================================================================
-- ORG MEMBERSHIPS TABLE
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE member_role AS ENUM ('owner', 'admin', 'member', 'viewer', 'billing');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS org_memberships (
    membership_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL,  -- References internal_users.id or OAuth user
    role member_role NOT NULL DEFAULT 'member',

    -- Invitation tracking
    invited_by VARCHAR(36),
    invited_at TIMESTAMPTZ,
    accepted_at TIMESTAMPTZ,

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint: one membership per user per org
    CONSTRAINT unique_org_user UNIQUE (org_id, user_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_org_memberships_org ON org_memberships(org_id);
CREATE INDEX IF NOT EXISTS idx_org_memberships_user ON org_memberships(user_id);
CREATE INDEX IF NOT EXISTS idx_org_memberships_role ON org_memberships(role);
CREATE INDEX IF NOT EXISTS idx_org_memberships_active ON org_memberships(org_id, user_id) WHERE is_active = TRUE;

-- Enable RLS
ALTER TABLE org_memberships ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can see memberships in orgs they belong to
CREATE POLICY org_memberships_tenant_isolation ON org_memberships
    FOR ALL
    USING (org_id = current_org_id());

-- Auto-update trigger
CREATE OR REPLACE FUNCTION update_org_memberships_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_org_memberships_updated_at ON org_memberships;
CREATE TRIGGER trigger_org_memberships_updated_at
    BEFORE UPDATE ON org_memberships
    FOR EACH ROW
    EXECUTE FUNCTION update_org_memberships_updated_at();

COMMENT ON TABLE org_memberships IS 'User membership in organizations with RBAC roles';

-- =============================================================================
-- PROJECTS TABLE
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE project_visibility AS ENUM ('private', 'internal', 'public');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS projects (
    project_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT,
    visibility project_visibility NOT NULL DEFAULT 'private',

    -- Settings
    default_branch TEXT DEFAULT 'main',
    settings JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Status
    archived_at TIMESTAMPTZ,

    -- Metadata
    created_by VARCHAR(36),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint: slug unique within org
    CONSTRAINT unique_project_slug_per_org UNIQUE (org_id, slug)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_projects_org ON projects(org_id);
CREATE INDEX IF NOT EXISTS idx_projects_visibility ON projects(visibility);
CREATE INDEX IF NOT EXISTS idx_projects_active ON projects(org_id) WHERE archived_at IS NULL;

-- Enable RLS
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can see projects in their org
CREATE POLICY projects_tenant_isolation ON projects
    FOR ALL
    USING (org_id = current_org_id());

-- Auto-update trigger
CREATE OR REPLACE FUNCTION update_projects_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_projects_updated_at ON projects;
CREATE TRIGGER trigger_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_projects_updated_at();

COMMENT ON TABLE projects IS 'Workspaces within organizations for logical separation';

-- =============================================================================
-- PROJECT MEMBERSHIPS TABLE
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE project_role AS ENUM ('admin', 'maintainer', 'developer', 'viewer', 'owner', 'contributor');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS project_memberships (
    membership_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    project_id VARCHAR(36) NOT NULL REFERENCES projects(project_id) ON DELETE CASCADE,
    user_id VARCHAR(36) NOT NULL,
    role project_role NOT NULL DEFAULT 'developer',

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint: one membership per user per project
    CONSTRAINT unique_project_user UNIQUE (project_id, user_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_project_memberships_project ON project_memberships(project_id);
CREATE INDEX IF NOT EXISTS idx_project_memberships_user ON project_memberships(user_id);

-- Enable RLS
ALTER TABLE project_memberships ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can see project memberships for projects in their org
CREATE POLICY project_memberships_tenant_isolation ON project_memberships
    FOR ALL
    USING (
        project_id IN (SELECT project_id FROM projects WHERE org_id = current_org_id())
    );

COMMENT ON TABLE project_memberships IS 'User access to specific projects (for private visibility)';

-- =============================================================================
-- AGENTS TABLE (First-class AI agent identities)
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE agent_type AS ENUM ('coder', 'reviewer', 'planner', 'tester', 'documenter', 'custom', 'orchestrator', 'specialist');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE agent_status AS ENUM ('active', 'busy', 'paused', 'disabled', 'archived');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS agents (
    agent_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id VARCHAR(36) REFERENCES projects(project_id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    agent_type agent_type NOT NULL DEFAULT 'coder',
    status agent_status NOT NULL DEFAULT 'active',
    config JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Capabilities
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,  -- behavior IDs
    max_concurrent_tasks INT NOT NULL DEFAULT 3,

    -- LLM Configuration
    llm_provider TEXT NOT NULL DEFAULT 'openai',
    llm_model TEXT NOT NULL DEFAULT 'gpt-4o-mini',
    temperature DECIMAL(3,2) NOT NULL DEFAULT 0.7,
    token_budget_per_task INT NOT NULL DEFAULT 50000,

    -- Metrics
    total_tasks_completed INT NOT NULL DEFAULT 0,
    total_tokens_used BIGINT NOT NULL DEFAULT 0,
    average_task_duration_seconds DECIMAL(10,2) DEFAULT 0,

    -- Metadata
    created_by VARCHAR(36),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Unique constraint: agent name unique within org
    CONSTRAINT unique_agent_name_per_org UNIQUE (org_id, name)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_agents_org ON agents(org_id);
CREATE INDEX IF NOT EXISTS idx_agents_type ON agents(agent_type);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_active ON agents(org_id) WHERE status IN ('active', 'busy');

-- Enable RLS
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can see agents in their org
CREATE POLICY agents_tenant_isolation ON agents
    FOR ALL
    USING (org_id = current_org_id());

-- Auto-update trigger
CREATE OR REPLACE FUNCTION update_agents_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_agents_updated_at ON agents;
CREATE TRIGGER trigger_agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW
    EXECUTE FUNCTION update_agents_updated_at();

COMMENT ON TABLE agents IS 'First-class AI agent identities that can be assigned to tasks';
COMMENT ON COLUMN agents.capabilities IS 'Array of behavior IDs this agent can execute';

-- =============================================================================
-- BILLING/SUBSCRIPTION TRACKING
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE subscription_status AS ENUM ('active', 'past_due', 'canceled', 'trialing');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS subscriptions (
    subscription_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    stripe_subscription_id TEXT,  -- NULL for free/internal plans
    stripe_customer_id TEXT,      -- NULL for free/internal plans
    plan org_plan NOT NULL,
    status subscription_status NOT NULL DEFAULT 'active',

    -- Billing cycle (NULL for free plans)
    current_period_start TIMESTAMPTZ,
    current_period_end TIMESTAMPTZ,

    -- Usage tracking
    tokens_used_this_period BIGINT NOT NULL DEFAULT 0,
    runs_this_period INT NOT NULL DEFAULT 0,

    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One active subscription per org
    CONSTRAINT unique_org_subscription UNIQUE (org_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_subscriptions_org ON subscriptions(org_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe ON subscriptions(stripe_subscription_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);

-- Enable RLS
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY subscriptions_tenant_isolation ON subscriptions
    FOR ALL
    USING (org_id = current_org_id());

-- Auto-update trigger
CREATE OR REPLACE FUNCTION update_subscriptions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_subscriptions_updated_at ON subscriptions;
CREATE TRIGGER trigger_subscriptions_updated_at
    BEFORE UPDATE ON subscriptions
    FOR EACH ROW
    EXECUTE FUNCTION update_subscriptions_updated_at();

COMMENT ON TABLE subscriptions IS 'Stripe subscription tracking for billing';

-- =============================================================================
-- USAGE METERING TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS usage_records (
    record_id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- What was used
    resource_type TEXT NOT NULL,  -- 'tokens', 'runs', 'storage_bytes', etc.
    amount BIGINT NOT NULL,

    -- Context
    project_id VARCHAR(36) REFERENCES projects(project_id) ON DELETE SET NULL,
    agent_id VARCHAR(36) REFERENCES agents(agent_id) ON DELETE SET NULL,
    run_id VARCHAR(36),  -- References runs table (will be added in migration 024)

    -- Period
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,

    -- Metadata
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_usage_records_org ON usage_records(org_id);
CREATE INDEX IF NOT EXISTS idx_usage_records_period ON usage_records(org_id, period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_usage_records_type ON usage_records(org_id, resource_type);

-- Enable RLS
ALTER TABLE usage_records ENABLE ROW LEVEL SECURITY;

-- RLS Policy
CREATE POLICY usage_records_tenant_isolation ON usage_records
    FOR ALL
    USING (org_id = current_org_id());

COMMENT ON TABLE usage_records IS 'Metered usage records for billing';

-- =============================================================================
-- GRANT PERMISSIONS (for service role)
-- =============================================================================

-- Note: In production, create a specific service role and grant permissions
-- For now, these tables are accessible to the connection user

COMMIT;
