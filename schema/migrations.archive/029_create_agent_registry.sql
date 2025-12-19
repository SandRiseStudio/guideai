-- Migration 029: Agent Registry PostgreSQL schema
-- Implements agent registry with versioning, visibility, and multi-tenant support
-- Created: 2025-12-09
-- Purpose: Enable agent discovery, creation, publishing, and version management

-- Enable UUID generation if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Main agents table: core agent definition (similar to behaviors table)
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,          -- agt-<12-hex> format
    name TEXT NOT NULL,                 -- Display name
    slug TEXT NOT NULL,                 -- URL-friendly unique identifier
    description TEXT NOT NULL,          -- Brief summary
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    latest_version TEXT NOT NULL,       -- Current active version
    status TEXT NOT NULL CHECK (status IN ('DRAFT', 'ACTIVE', 'DEPRECATED')),
    visibility TEXT NOT NULL DEFAULT 'PRIVATE' CHECK (visibility IN ('PRIVATE', 'ORGANIZATION', 'PUBLIC')),
    owner_id TEXT NOT NULL,             -- Creator user ID
    org_id TEXT,                        -- Organization ID for RLS
    published_at TIMESTAMPTZ,           -- When made public
    is_builtin BOOLEAN NOT NULL DEFAULT FALSE,  -- True for system agents from playbooks

    -- Unique slug within org context
    UNIQUE (org_id, slug)
);

-- Agent versions table: versioned content and configuration (similar to behavior_versions)
CREATE TABLE IF NOT EXISTS agent_versions (
    agent_id TEXT NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    version TEXT NOT NULL,              -- Semantic version (e.g., 1.0.0)
    mission TEXT NOT NULL,              -- Full mission statement
    role_alignment TEXT NOT NULL CHECK (role_alignment IN ('STRATEGIST', 'TEACHER', 'STUDENT', 'MULTI_ROLE')),
    capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,      -- Capability tags
    default_behaviors JSONB NOT NULL DEFAULT '[]'::jsonb, -- behavior_* IDs referenced
    playbook_content TEXT NOT NULL DEFAULT '',            -- Full markdown playbook
    status TEXT NOT NULL CHECK (status IN ('DRAFT', 'ACTIVE', 'DEPRECATED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by TEXT NOT NULL,           -- User who created this version
    effective_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    effective_to TIMESTAMPTZ,           -- NULL if active
    created_from TEXT,                  -- Previous version this was forked from
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    PRIMARY KEY (agent_id, version)
);

-- Standard indexes for common query patterns
-- Agent discovery queries
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents (status);
CREATE INDEX IF NOT EXISTS idx_agents_visibility ON agents (visibility);
CREATE INDEX IF NOT EXISTS idx_agents_owner_id ON agents (owner_id);
CREATE INDEX IF NOT EXISTS idx_agents_org_id ON agents (org_id) WHERE org_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agents_updated_at ON agents (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_agents_slug ON agents (slug);
CREATE INDEX IF NOT EXISTS idx_agents_tags_gin ON agents USING GIN (tags jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_agents_is_builtin ON agents (is_builtin) WHERE is_builtin = TRUE;

-- Agent version queries
CREATE INDEX IF NOT EXISTS idx_agent_versions_status ON agent_versions (status);
CREATE INDEX IF NOT EXISTS idx_agent_versions_role_alignment ON agent_versions (role_alignment);
CREATE INDEX IF NOT EXISTS idx_agent_versions_effective_from ON agent_versions (effective_from);
CREATE INDEX IF NOT EXISTS idx_agent_versions_capabilities ON agent_versions USING GIN (capabilities);
CREATE INDEX IF NOT EXISTS idx_agent_versions_default_behaviors ON agent_versions USING GIN (default_behaviors);

-- Text search index for agent discovery (name, description, mission)
CREATE INDEX IF NOT EXISTS idx_agents_fulltext ON agents
    USING GIN (to_tsvector('english', name || ' ' || description));

-- Composite index for marketplace queries (public + active agents)
CREATE INDEX IF NOT EXISTS idx_agents_marketplace ON agents (visibility, status, updated_at DESC)
    WHERE visibility = 'PUBLIC' AND status = 'ACTIVE';

-- Row-level security policies for multi-tenant isolation
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_versions ENABLE ROW LEVEL SECURITY;

-- Policy: Users can see their own agents
CREATE POLICY agents_owner_policy ON agents
    FOR ALL
    USING (owner_id = current_setting('app.current_user_id', TRUE));

-- Policy: Users can see org agents if they belong to the org
CREATE POLICY agents_org_policy ON agents
    FOR SELECT
    USING (
        org_id IS NOT NULL
        AND org_id = current_setting('app.current_org_id', TRUE)
        AND visibility IN ('ORGANIZATION', 'PUBLIC')
    );

-- Policy: Users can see public agents
CREATE POLICY agents_public_policy ON agents
    FOR SELECT
    USING (visibility = 'PUBLIC' AND status = 'ACTIVE');

-- Policy: Users can see builtin (system) agents
CREATE POLICY agents_builtin_policy ON agents
    FOR SELECT
    USING (is_builtin = TRUE AND status = 'ACTIVE');

-- Version policies follow parent agent visibility
CREATE POLICY agent_versions_access_policy ON agent_versions
    FOR SELECT
    USING (
        EXISTS (
            SELECT 1 FROM agents a
            WHERE a.agent_id = agent_versions.agent_id
        )
    );

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_agents_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update updated_at
DROP TRIGGER IF EXISTS agents_updated_at_trigger ON agents;
CREATE TRIGGER agents_updated_at_trigger
    BEFORE UPDATE ON agents
    FOR EACH ROW
    EXECUTE FUNCTION update_agents_updated_at();

-- Comments for documentation
COMMENT ON TABLE agents IS 'Core agent definitions with visibility and multi-tenant support';
COMMENT ON TABLE agent_versions IS 'Versioned agent content and configuration';
COMMENT ON COLUMN agents.slug IS 'URL-friendly unique identifier within org context';
COMMENT ON COLUMN agents.is_builtin IS 'True for system agents bootstrapped from playbook files';
COMMENT ON COLUMN agent_versions.playbook_content IS 'Full markdown playbook content';
COMMENT ON COLUMN agent_versions.created_from IS 'Previous version this was forked from for version history';
