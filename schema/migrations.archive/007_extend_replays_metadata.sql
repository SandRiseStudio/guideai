-- Migration 007: Extend replays table with audit linkage and actor metadata
-- Implements enhanced replay tracking per ACTION_SERVICE_CONTRACT.md updates
-- Created: 2025-10-28
-- Purpose: Add action lists, audit URNs, strategy, actor details, and lifecycle timestamps

-- Add new columns to replays table
ALTER TABLE replays
    ADD COLUMN IF NOT EXISTS action_ids JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS succeeded_action_ids JSONB DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS audit_log_event_id TEXT,
    ADD COLUMN IF NOT EXISTS strategy TEXT DEFAULT 'SEQUENTIAL',
    ADD COLUMN IF NOT EXISTS actor_id TEXT,
    ADD COLUMN IF NOT EXISTS actor_role TEXT,
    ADD COLUMN IF NOT EXISTS actor_surface TEXT,
    ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

-- Add indexes for new columns
CREATE INDEX IF NOT EXISTS idx_replays_action_ids ON replays USING GIN (action_ids);
CREATE INDEX IF NOT EXISTS idx_replays_succeeded_action_ids ON replays USING GIN (succeeded_action_ids);
CREATE INDEX IF NOT EXISTS idx_replays_audit_log_event_id ON replays (audit_log_event_id) WHERE audit_log_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_replays_actor_id ON replays (actor_id) WHERE actor_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_replays_strategy ON replays (strategy);
CREATE INDEX IF NOT EXISTS idx_replays_started_at ON replays (started_at);
CREATE INDEX IF NOT EXISTS idx_replays_completed_at ON replays (completed_at);

-- Update comments for new columns
COMMENT ON COLUMN replays.action_ids IS 'Array of all action_id UUIDs included in this replay job';
COMMENT ON COLUMN replays.succeeded_action_ids IS 'Array of action_id UUIDs that successfully completed replay';
COMMENT ON COLUMN replays.audit_log_event_id IS 'URN linking this replay to audit log events (e.g., urn:guideai:audit:replay:{replay_id})';
COMMENT ON COLUMN replays.strategy IS 'Replay execution strategy (SEQUENTIAL, PARALLEL, etc.)';
COMMENT ON COLUMN replays.actor_id IS 'ID of the actor who initiated the replay';
COMMENT ON COLUMN replays.actor_role IS 'Role of the initiating actor (Strategist, Teacher, Student, etc.)';
COMMENT ON COLUMN replays.actor_surface IS 'Surface from which replay was triggered (cli, api, mcp, web)';
COMMENT ON COLUMN replays.started_at IS 'Timestamp when replay execution began';
COMMENT ON COLUMN replays.completed_at IS 'Timestamp when replay execution finished (NULL if in progress)';

-- Backfill existing rows with reasonable defaults (if any exist)
UPDATE replays
SET
    action_ids = '[]'::jsonb,
    succeeded_action_ids = '[]'::jsonb,
    strategy = 'SEQUENTIAL'
WHERE action_ids IS NULL;
