-- Migration: 028_add_agent_idle_status.sql
-- Description: Add 'idle' status to agent_status enum and create status transition tracking
-- Date: 2025-12-09
-- Feature: 13.4.3 - Agent status tracking (Active/Busy/Idle/Paused/Disabled)
-- Behavior: behavior_migrate_postgres_schema
--
-- This migration:
--   1. Adds 'idle' value to agent_status enum (existing enum already has active, busy, paused, disabled, archived)
--   2. Creates agent_status_transitions table for audit trail
--   3. Creates agent_status_changed event function for real-time notifications
--
-- Rollback:
--   DROP TABLE IF EXISTS agent_status_transitions CASCADE;
--   DROP FUNCTION IF EXISTS notify_agent_status_change() CASCADE;
--   -- Note: PostgreSQL does not support removing enum values directly

BEGIN;

-- =============================================================================
-- ADD 'idle' TO agent_status ENUM
-- =============================================================================
-- Note: PostgreSQL 10+ supports ADD VALUE without needing to recreate the type
-- The idempotent check handles re-runs safely

DO $$
BEGIN
    -- Check if 'idle' already exists in the enum
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum
        WHERE enumtypid = 'agent_status'::regtype
        AND enumlabel = 'idle'
    ) THEN
        ALTER TYPE agent_status ADD VALUE 'idle' AFTER 'busy';
    END IF;
EXCEPTION
    WHEN duplicate_object THEN NULL;
    WHEN undefined_object THEN
        -- enum type doesn't exist yet, will be created by 023
        NULL;
END $$;

-- =============================================================================
-- AGENT STATUS TRANSITIONS TABLE (Audit Trail)
-- =============================================================================
-- Records all status changes for compliance and analytics

CREATE TABLE IF NOT EXISTS agent_status_transitions (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    agent_id VARCHAR(36) NOT NULL REFERENCES agents(agent_id) ON DELETE CASCADE,
    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Status change details
    from_status agent_status NOT NULL,
    to_status agent_status NOT NULL,
    reason TEXT,  -- Optional reason for the transition (e.g., "task_assigned", "task_completed", "manual_pause")

    -- Context
    triggered_by VARCHAR(36),  -- user_id or "system" for automatic transitions
    trigger_type VARCHAR(50) NOT NULL DEFAULT 'manual',  -- 'manual', 'task_start', 'task_complete', 'scheduled', 'api'
    task_id VARCHAR(36),  -- Optional reference to task that caused the transition

    -- Metadata for extensibility
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Timestamp
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_agent_status_transitions_agent
    ON agent_status_transitions(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_status_transitions_org
    ON agent_status_transitions(org_id);
CREATE INDEX IF NOT EXISTS idx_agent_status_transitions_created
    ON agent_status_transitions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_status_transitions_trigger_type
    ON agent_status_transitions(trigger_type);

-- Enable RLS
ALTER TABLE agent_status_transitions ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can see transitions in their org
CREATE POLICY agent_status_transitions_tenant_isolation ON agent_status_transitions
    FOR ALL
    USING (org_id = current_org_id());

COMMENT ON TABLE agent_status_transitions IS 'Audit trail of all agent status changes for compliance and analytics';
COMMENT ON COLUMN agent_status_transitions.trigger_type IS 'What triggered the transition: manual, task_start, task_complete, scheduled, api';
COMMENT ON COLUMN agent_status_transitions.reason IS 'Human-readable reason for the status change';

-- =============================================================================
-- NOTIFY FUNCTION FOR REAL-TIME STATUS UPDATES
-- =============================================================================
-- Publishes status changes to a PostgreSQL notification channel for SSE/WebSocket

CREATE OR REPLACE FUNCTION notify_agent_status_change()
RETURNS TRIGGER AS $$
DECLARE
    payload JSONB;
BEGIN
    -- Only notify on actual status changes
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        payload := jsonb_build_object(
            'event', 'agent_status_changed',
            'agent_id', NEW.agent_id,
            'org_id', NEW.org_id,
            'from_status', OLD.status::TEXT,
            'to_status', NEW.status::TEXT,
            'timestamp', NOW()::TEXT
        );

        -- Notify on the 'agent_events' channel
        PERFORM pg_notify('agent_events', payload::TEXT);
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create trigger on agents table for status change notifications
DROP TRIGGER IF EXISTS trigger_agent_status_notify ON agents;
CREATE TRIGGER trigger_agent_status_notify
    AFTER UPDATE OF status ON agents
    FOR EACH ROW
    EXECUTE FUNCTION notify_agent_status_change();

COMMENT ON FUNCTION notify_agent_status_change() IS 'Publishes agent status changes to pg_notify for real-time updates';

-- =============================================================================
-- HELPER FUNCTION: Validate Status Transition
-- =============================================================================
-- Returns TRUE if the transition is allowed, FALSE otherwise

CREATE OR REPLACE FUNCTION is_valid_agent_status_transition(
    current_status agent_status,
    new_status agent_status
) RETURNS BOOLEAN AS $$
BEGIN
    -- Same status is always valid (no-op)
    IF current_status = new_status THEN
        RETURN TRUE;
    END IF;

    -- Transition rules based on AgentStatus docstring
    CASE current_status
        WHEN 'active' THEN
            RETURN new_status IN ('busy', 'idle', 'paused', 'disabled', 'archived');
        WHEN 'busy' THEN
            -- Cannot go directly from busy to disabled/archived (must pause first)
            RETURN new_status IN ('active', 'idle', 'paused');
        WHEN 'idle' THEN
            RETURN new_status IN ('active', 'busy', 'paused', 'disabled', 'archived');
        WHEN 'paused' THEN
            RETURN new_status IN ('active', 'disabled', 'archived');
        WHEN 'disabled' THEN
            RETURN new_status IN ('active', 'archived');
        WHEN 'archived' THEN
            -- Archived agents can only be restored (via separate restore_agent function)
            RETURN FALSE;
        ELSE
            RETURN FALSE;
    END CASE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION is_valid_agent_status_transition(agent_status, agent_status) IS
    'Validates if a status transition is allowed based on the state machine rules';

-- =============================================================================
-- ADD last_status_change COLUMN TO agents TABLE
-- =============================================================================
-- Tracks when the status was last changed for reporting

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'agents' AND column_name = 'last_status_change'
    ) THEN
        ALTER TABLE agents ADD COLUMN last_status_change TIMESTAMPTZ DEFAULT NOW();
    END IF;
END $$;

-- Update last_status_change when status changes
CREATE OR REPLACE FUNCTION update_agent_last_status_change()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.status IS DISTINCT FROM NEW.status THEN
        NEW.last_status_change = NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_agent_last_status_change ON agents;
CREATE TRIGGER trigger_agent_last_status_change
    BEFORE UPDATE OF status ON agents
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_last_status_change();

COMMIT;
