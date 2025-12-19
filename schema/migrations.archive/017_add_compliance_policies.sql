-- Migration 017: Add compliance policies table for ComplianceService CLI parity
-- Supports global, org-scoped, and project-scoped policies
-- Created: 2025-11-24
-- Purpose: Enable `guideai compliance policies list/create/get` CLI commands

-- Enable UUID generation (should already exist from earlier migrations)
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Compliance policies table: stores policy definitions with scope hierarchy
CREATE TABLE IF NOT EXISTS compliance_policies (
    policy_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Identity
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '1.0.0',

    -- Scope: global (NULL/NULL), org-scoped (org_id set), or project-scoped (both set)
    org_id TEXT,
    project_id TEXT,

    -- Policy definition
    policy_type TEXT NOT NULL CHECK (policy_type IN ('AUDIT', 'SECURITY', 'COMPLIANCE', 'GOVERNANCE', 'CUSTOM')),
    enforcement_level TEXT NOT NULL DEFAULT 'ADVISORY' CHECK (enforcement_level IN ('ADVISORY', 'WARNING', 'BLOCKING')),

    -- Rules: array of rule definitions with conditions and actions
    rules JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Required behaviors that must be cited for compliance
    required_behaviors JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Categories this policy applies to (SOC2, GDPR, Internal, etc.)
    compliance_categories JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT true,

    -- Audit fields
    created_by_id TEXT NOT NULL,
    created_by_role TEXT NOT NULL,
    created_by_surface TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Unique name per scope (allow same name in different orgs/projects)
    UNIQUE NULLS NOT DISTINCT (name, org_id, project_id)
);

-- Standard indexes for common queries
CREATE INDEX IF NOT EXISTS idx_compliance_policies_scope ON compliance_policies (org_id, project_id);
CREATE INDEX IF NOT EXISTS idx_compliance_policies_type ON compliance_policies (policy_type);
CREATE INDEX IF NOT EXISTS idx_compliance_policies_enforcement ON compliance_policies (enforcement_level);
CREATE INDEX IF NOT EXISTS idx_compliance_policies_active ON compliance_policies (is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_compliance_policies_created_at ON compliance_policies (created_at);

-- GIN indexes for JSONB querying
CREATE INDEX IF NOT EXISTS idx_compliance_policies_rules ON compliance_policies USING GIN (rules);
CREATE INDEX IF NOT EXISTS idx_compliance_policies_behaviors ON compliance_policies USING GIN (required_behaviors);
CREATE INDEX IF NOT EXISTS idx_compliance_policies_categories ON compliance_policies USING GIN (compliance_categories);

-- Trigger to update updated_at automatically
CREATE OR REPLACE FUNCTION update_compliance_policies_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_compliance_policies_updated_at ON compliance_policies;
CREATE TRIGGER trigger_compliance_policies_updated_at
    BEFORE UPDATE ON compliance_policies
    FOR EACH ROW
    EXECUTE FUNCTION update_compliance_policies_updated_at();

-- Add comments for documentation
COMMENT ON TABLE compliance_policies IS 'Compliance policy definitions with scope hierarchy (global/org/project)';
COMMENT ON COLUMN compliance_policies.org_id IS 'NULL for global policies, set for org/project-scoped policies';
COMMENT ON COLUMN compliance_policies.project_id IS 'NULL for global/org policies, set for project-scoped policies';
COMMENT ON COLUMN compliance_policies.enforcement_level IS 'ADVISORY=informational, WARNING=non-blocking alert, BLOCKING=prevents action';
COMMENT ON COLUMN compliance_policies.rules IS 'Array of {condition, action, message} rule definitions';
COMMENT ON COLUMN compliance_policies.required_behaviors IS 'Behavior IDs that must be cited for compliance with this policy';
