-- Migration 004: ActionService PostgreSQL schema
-- Implements ACTION_SERVICE_CONTRACT.md and REPRODUCIBILITY_STRATEGY.md requirements
-- Created: 2025-10-27
-- Purpose: WORM audit storage for all platform actions with replay tracking

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Actions table: stores immutable action records for CLI/API/MCP/Web parity
CREATE TABLE IF NOT EXISTS actions (
    action_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Actor details (embedded from Actor dataclass)
    actor_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    actor_surface TEXT NOT NULL CHECK (actor_surface IN ('cli', 'api', 'mcp', 'web')),

    -- Action content
    artifact_path TEXT NOT NULL,
    summary TEXT NOT NULL,
    behaviors_cited JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Linkage and audit (TEXT to support flexible ID formats)
    related_run_id TEXT,
    audit_log_event_id TEXT,
    checksum TEXT NOT NULL,

    -- Replay tracking
    replay_status TEXT NOT NULL DEFAULT 'NOT_STARTED' CHECK (replay_status IN ('NOT_STARTED', 'IN_PROGRESS', 'SUCCEEDED', 'FAILED')),

    -- Timestamps for WORM compliance
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- GIN indexes for JSONB columns (behavior/metadata search)
CREATE INDEX IF NOT EXISTS idx_actions_behaviors_cited ON actions USING GIN (behaviors_cited);
CREATE INDEX IF NOT EXISTS idx_actions_metadata ON actions USING GIN (metadata);

-- Standard indexes for common queries
CREATE INDEX IF NOT EXISTS idx_actions_timestamp ON actions (timestamp);
CREATE INDEX IF NOT EXISTS idx_actions_related_run_id ON actions (related_run_id) WHERE related_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_actions_actor_id ON actions (actor_id);
CREATE INDEX IF NOT EXISTS idx_actions_replay_status ON actions (replay_status);

-- Replays table: tracks replay job status and progress
CREATE TABLE IF NOT EXISTS replays (
    replay_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'IN_PROGRESS', 'SUCCEEDED', 'FAILED')),
    progress FLOAT NOT NULL DEFAULT 0.0 CHECK (progress >= 0.0 AND progress <= 1.0),
    logs JSONB NOT NULL DEFAULT '[]'::jsonb,
    failed_action_ids JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- Audit trail
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for replay status queries
CREATE INDEX IF NOT EXISTS idx_replays_status ON replays (status);
CREATE INDEX IF NOT EXISTS idx_replays_created_at ON replays (created_at);

-- Trigger to update updated_at timestamps automatically
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS update_actions_updated_at ON actions;
CREATE TRIGGER update_actions_updated_at
    BEFORE UPDATE ON actions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_replays_updated_at ON replays;
CREATE TRIGGER update_replays_updated_at
    BEFORE UPDATE ON replays
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Comments for documentation
COMMENT ON TABLE actions IS 'Immutable action records for platform reproducibility (WORM storage)';
COMMENT ON TABLE replays IS 'Replay job tracking with progress and failure details';
COMMENT ON COLUMN actions.behaviors_cited IS 'Array of behavior names referenced during action execution';
COMMENT ON COLUMN actions.metadata IS 'Arbitrary key-value pairs for extensibility';
COMMENT ON COLUMN actions.checksum IS 'SHA-256 hash of artifact_path + summary + behaviors_cited for integrity validation';
COMMENT ON COLUMN actions.replay_status IS 'Current replay state for this action';
COMMENT ON COLUMN replays.logs IS 'Array of log messages from replay execution';
COMMENT ON COLUMN replays.failed_action_ids IS 'Array of action_id UUIDs that failed during replay';
