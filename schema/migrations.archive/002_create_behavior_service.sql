-- guideAI BehaviorService PostgreSQL schema
-- Creates tables and indexes required to operate BehaviorService on Postgres.

BEGIN;

CREATE TABLE IF NOT EXISTS behaviors (
    behavior_id UUID PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    latest_version TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS behavior_versions (
    behavior_id UUID NOT NULL REFERENCES behaviors(behavior_id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    instruction TEXT NOT NULL,
    role_focus TEXT NOT NULL,
    status TEXT NOT NULL,
    trigger_keywords JSONB NOT NULL DEFAULT '[]'::jsonb,
    examples JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    effective_from TIMESTAMPTZ NOT NULL,
    effective_to TIMESTAMPTZ,
    created_by TEXT NOT NULL,
    approval_action_id TEXT,
    embedding_checksum TEXT,
    embedding BYTEA,
    PRIMARY KEY (behavior_id, version)
);

CREATE INDEX IF NOT EXISTS idx_behaviors_status ON behaviors (status);
CREATE INDEX IF NOT EXISTS idx_behaviors_updated_at ON behaviors (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_behaviors_tags_gin ON behaviors USING GIN (tags jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_behavior_versions_status ON behavior_versions (status);
CREATE INDEX IF NOT EXISTS idx_behavior_versions_role_focus ON behavior_versions (role_focus);
CREATE INDEX IF NOT EXISTS idx_behavior_versions_effective_from ON behavior_versions (effective_from);

COMMIT;
