-- Migration: 026_user_management_invitations.sql
-- Description: Create invitation system tables for user management
-- Date: 2025-12-05
-- Behavior: behavior_migrate_postgres_schema
-- Epic: 13.2.4 User Management (invite flow, role assignment)
--
-- This migration creates the invitation system for the multi-tenant
-- organization feature. Invitations allow org admins to invite users
-- to join their organization with specified roles.
--
-- Key Design Decisions:
--   1. Pre-registration required: Users must have an account to accept
--   2. Token-based: Secure random tokens for invitation URLs
--   3. Expiration: Default 7 days with configurable per-invitation
--   4. Multi-channel: Track notification channel used (email, slack, sms, copy_link)
--   5. Audit trail: Full history of invitation lifecycle
--
-- Tables:
--   - org_invitations: Pending and historical invitations
--   - invitation_events: Audit log for invitation state changes
--
-- Rollback: DROP TABLE IF EXISTS invitation_events, org_invitations CASCADE;

BEGIN;

-- =============================================================================
-- ORG INVITATIONS TABLE
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE invitation_status AS ENUM (
        'pending',      -- Awaiting acceptance
        'accepted',     -- User accepted invitation
        'expired',      -- Past expiration date
        'revoked',      -- Admin revoked invitation
        'declined'      -- User declined invitation
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE invitation_channel AS ENUM (
        'email',
        'slack',
        'sms',
        'copy_link',
        'multi_channel'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS org_invitations (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    org_id VARCHAR(36) NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Token for URL (e.g., /invitations/{token}/accept)
    token VARCHAR(64) NOT NULL UNIQUE,

    -- Invitee information
    invitee_email TEXT NOT NULL,
    invitee_name TEXT,
    invitee_phone TEXT,           -- For SMS notifications
    invitee_slack_id TEXT,        -- For Slack notifications

    -- Role to assign upon acceptance
    role member_role NOT NULL DEFAULT 'member',

    -- Invitation details
    message TEXT,                  -- Custom message from inviter
    notification_channel invitation_channel NOT NULL DEFAULT 'email',

    -- Status tracking
    status invitation_status NOT NULL DEFAULT 'pending',

    -- Expiration
    expires_at TIMESTAMPTZ NOT NULL,

    -- Who sent the invitation
    invited_by VARCHAR(36) NOT NULL,  -- user_id of inviter

    -- If accepted, which user accepted
    accepted_by VARCHAR(36),      -- user_id of acceptor
    accepted_at TIMESTAMPTZ,

    -- Notification tracking
    notification_sent_at TIMESTAMPTZ,
    notification_provider TEXT,   -- e.g., 'smtp', 'sendgrid', 'slack_webhook'
    notification_message_id TEXT, -- Provider's message ID for tracking

    -- Metadata
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_org_invitations_org ON org_invitations(org_id);
CREATE INDEX IF NOT EXISTS idx_org_invitations_token ON org_invitations(token);
CREATE INDEX IF NOT EXISTS idx_org_invitations_email ON org_invitations(invitee_email);
CREATE INDEX IF NOT EXISTS idx_org_invitations_status ON org_invitations(status);
CREATE INDEX IF NOT EXISTS idx_org_invitations_pending ON org_invitations(org_id, status)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_org_invitations_expires ON org_invitations(expires_at)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_org_invitations_invited_by ON org_invitations(invited_by);

-- Enable RLS
ALTER TABLE org_invitations ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can see invitations for orgs they belong to
CREATE POLICY org_invitations_tenant_isolation ON org_invitations
    FOR ALL
    USING (org_id = current_org_id());

-- Public read policy for token-based access (for acceptance flow)
-- This allows unauthenticated lookup by token
CREATE POLICY org_invitations_public_token_lookup ON org_invitations
    FOR SELECT
    USING (current_org_id() IS NULL AND token IS NOT NULL);

-- Auto-update trigger
CREATE OR REPLACE FUNCTION update_org_invitations_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_org_invitations_updated_at ON org_invitations;
CREATE TRIGGER trigger_org_invitations_updated_at
    BEFORE UPDATE ON org_invitations
    FOR EACH ROW
    EXECUTE FUNCTION update_org_invitations_updated_at();

COMMENT ON TABLE org_invitations IS 'Pending and historical organization invitations';
COMMENT ON COLUMN org_invitations.token IS 'Secure random token for invitation URL';
COMMENT ON COLUMN org_invitations.role IS 'Role to assign when invitation is accepted';
COMMENT ON COLUMN org_invitations.expires_at IS 'Invitation expiration (default 7 days from creation)';
COMMENT ON COLUMN org_invitations.notification_channel IS 'Channel used to deliver invitation';

-- =============================================================================
-- INVITATION EVENTS TABLE (Audit Log)
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE invitation_event_type AS ENUM (
        'created',           -- Invitation created
        'notification_sent', -- Notification delivered
        'notification_failed', -- Notification delivery failed
        'viewed',            -- Invitation page accessed
        'accepted',          -- User accepted
        'declined',          -- User declined
        'expired',           -- System marked as expired
        'revoked',           -- Admin revoked
        'resent'             -- Invitation resent
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS invitation_events (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::TEXT,
    invitation_id VARCHAR(36) NOT NULL REFERENCES org_invitations(id) ON DELETE CASCADE,
    event_type invitation_event_type NOT NULL,

    -- Actor who triggered the event
    actor_id VARCHAR(36),         -- user_id or null for system events
    actor_type TEXT NOT NULL DEFAULT 'user', -- 'user', 'system', 'api'

    -- Event details
    details JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- For notification events
    notification_channel invitation_channel,
    notification_provider TEXT,
    notification_success BOOLEAN,
    notification_error TEXT,

    -- Metadata
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_invitation_events_invitation ON invitation_events(invitation_id);
CREATE INDEX IF NOT EXISTS idx_invitation_events_type ON invitation_events(event_type);
CREATE INDEX IF NOT EXISTS idx_invitation_events_created ON invitation_events(invitation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_invitation_events_actor ON invitation_events(actor_id)
    WHERE actor_id IS NOT NULL;

-- Enable RLS (events inherit access from invitation)
ALTER TABLE invitation_events ENABLE ROW LEVEL SECURITY;

CREATE POLICY invitation_events_tenant_isolation ON invitation_events
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM org_invitations
            WHERE org_invitations.id = invitation_events.invitation_id
            AND org_invitations.org_id = current_org_id()
        )
    );

COMMENT ON TABLE invitation_events IS 'Audit log for invitation lifecycle events';
COMMENT ON COLUMN invitation_events.actor_type IS 'Type of actor: user, system, or api';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to generate secure random token
CREATE OR REPLACE FUNCTION generate_invitation_token() RETURNS TEXT AS $$
DECLARE
    token TEXT;
BEGIN
    -- Generate 32 bytes of random data, encode as base64url
    token := encode(gen_random_bytes(32), 'base64');
    -- Make URL-safe: replace + with -, / with _, remove padding
    token := replace(replace(replace(token, '+', '-'), '/', '_'), '=', '');
    RETURN token;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION generate_invitation_token() IS 'Generate secure random token for invitation URLs';

-- Function to create invitation with default expiration
CREATE OR REPLACE FUNCTION create_invitation(
    p_org_id VARCHAR(36),
    p_invitee_email TEXT,
    p_role member_role,
    p_invited_by VARCHAR(36),
    p_channel invitation_channel DEFAULT 'email',
    p_expires_days INT DEFAULT 7,
    p_invitee_name TEXT DEFAULT NULL,
    p_message TEXT DEFAULT NULL
) RETURNS org_invitations AS $$
DECLARE
    v_invitation org_invitations;
    v_token TEXT;
BEGIN
    -- Generate unique token
    v_token := generate_invitation_token();

    -- Insert invitation
    INSERT INTO org_invitations (
        org_id, token, invitee_email, invitee_name, role,
        message, notification_channel, invited_by, expires_at
    ) VALUES (
        p_org_id, v_token, p_invitee_email, p_invitee_name, p_role,
        p_message, p_channel, p_invited_by, NOW() + (p_expires_days || ' days')::INTERVAL
    ) RETURNING * INTO v_invitation;

    -- Record creation event
    INSERT INTO invitation_events (invitation_id, event_type, actor_id, details)
    VALUES (
        v_invitation.id,
        'created',
        p_invited_by,
        jsonb_build_object(
            'role', p_role::TEXT,
            'channel', p_channel::TEXT,
            'expires_days', p_expires_days
        )
    );

    RETURN v_invitation;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_invitation IS 'Create a new organization invitation with audit logging';

-- Function to accept invitation
CREATE OR REPLACE FUNCTION accept_invitation(
    p_token TEXT,
    p_user_id VARCHAR(36),
    p_ip_address INET DEFAULT NULL,
    p_user_agent TEXT DEFAULT NULL
) RETURNS TABLE (
    success BOOLEAN,
    invitation_id VARCHAR(36),
    org_id VARCHAR(36),
    role member_role,
    error_message TEXT
) AS $$
DECLARE
    v_invitation org_invitations;
    v_membership_id VARCHAR(36);
BEGIN
    -- Look up invitation by token
    SELECT * INTO v_invitation
    FROM org_invitations
    WHERE org_invitations.token = p_token
    FOR UPDATE;

    -- Check if found
    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE, NULL::VARCHAR(36), NULL::VARCHAR(36),
            NULL::member_role, 'Invitation not found'::TEXT;
        RETURN;
    END IF;

    -- Check status
    IF v_invitation.status != 'pending' THEN
        RETURN QUERY SELECT FALSE, v_invitation.id, v_invitation.org_id,
            v_invitation.role, ('Invitation is ' || v_invitation.status::TEXT)::TEXT;
        RETURN;
    END IF;

    -- Check expiration
    IF v_invitation.expires_at < NOW() THEN
        -- Mark as expired
        UPDATE org_invitations SET status = 'expired' WHERE id = v_invitation.id;
        INSERT INTO invitation_events (invitation_id, event_type, actor_id, actor_type)
        VALUES (v_invitation.id, 'expired', NULL, 'system');

        RETURN QUERY SELECT FALSE, v_invitation.id, v_invitation.org_id,
            v_invitation.role, 'Invitation has expired'::TEXT;
        RETURN;
    END IF;

    -- Create org membership
    INSERT INTO org_memberships (org_id, user_id, role, invited_by, invited_at, accepted_at)
    VALUES (v_invitation.org_id, p_user_id, v_invitation.role,
            v_invitation.invited_by, v_invitation.created_at, NOW())
    ON CONFLICT (org_id, user_id) DO UPDATE
    SET role = EXCLUDED.role, updated_at = NOW()
    RETURNING membership_id INTO v_membership_id;

    -- Update invitation status
    UPDATE org_invitations
    SET status = 'accepted', accepted_by = p_user_id, accepted_at = NOW()
    WHERE id = v_invitation.id;

    -- Record acceptance event
    INSERT INTO invitation_events (
        invitation_id, event_type, actor_id, details, ip_address, user_agent
    ) VALUES (
        v_invitation.id, 'accepted', p_user_id,
        jsonb_build_object('membership_id', v_membership_id),
        p_ip_address, p_user_agent
    );

    RETURN QUERY SELECT TRUE, v_invitation.id, v_invitation.org_id,
        v_invitation.role, NULL::TEXT;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION accept_invitation IS 'Accept an invitation and create org membership';

-- Function to revoke invitation
CREATE OR REPLACE FUNCTION revoke_invitation(
    p_invitation_id VARCHAR(36),
    p_revoked_by VARCHAR(36),
    p_reason TEXT DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_updated BOOLEAN;
BEGIN
    UPDATE org_invitations
    SET status = 'revoked'
    WHERE id = p_invitation_id AND status = 'pending'
    RETURNING TRUE INTO v_updated;

    IF v_updated THEN
        INSERT INTO invitation_events (invitation_id, event_type, actor_id, details)
        VALUES (p_invitation_id, 'revoked', p_revoked_by,
                jsonb_build_object('reason', COALESCE(p_reason, 'No reason provided')));
        RETURN TRUE;
    END IF;

    RETURN FALSE;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION revoke_invitation IS 'Revoke a pending invitation';

-- Function to mark expired invitations (for batch job)
CREATE OR REPLACE FUNCTION expire_invitations() RETURNS INT AS $$
DECLARE
    v_count INT;
BEGIN
    WITH expired AS (
        UPDATE org_invitations
        SET status = 'expired'
        WHERE status = 'pending' AND expires_at < NOW()
        RETURNING id
    )
    SELECT COUNT(*) INTO v_count FROM expired;

    -- Record events for expired invitations (bulk insert)
    INSERT INTO invitation_events (invitation_id, event_type, actor_type, details)
    SELECT id, 'expired', 'system', '{}'::jsonb
    FROM org_invitations
    WHERE status = 'expired'
    AND id NOT IN (
        SELECT invitation_id FROM invitation_events
        WHERE event_type = 'expired'
    );

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION expire_invitations IS 'Mark all expired pending invitations as expired';

-- =============================================================================
-- VIEWS
-- =============================================================================

-- View for pending invitations with org details
CREATE OR REPLACE VIEW pending_invitations_view AS
SELECT
    i.id,
    i.org_id,
    o.name AS org_name,
    o.slug AS org_slug,
    i.token,
    i.invitee_email,
    i.invitee_name,
    i.role,
    i.message,
    i.notification_channel,
    i.invited_by,
    i.expires_at,
    i.created_at,
    EXTRACT(EPOCH FROM (i.expires_at - NOW())) / 3600 AS hours_until_expiry
FROM org_invitations i
JOIN organizations o ON o.id = i.org_id
WHERE i.status = 'pending' AND i.expires_at > NOW();

COMMENT ON VIEW pending_invitations_view IS 'Active pending invitations with organization details';

-- View for invitation history with events
CREATE OR REPLACE VIEW invitation_history_view AS
SELECT
    i.id AS invitation_id,
    i.org_id,
    i.invitee_email,
    i.role,
    i.status,
    i.created_at,
    i.accepted_at,
    e.event_type AS last_event_type,
    e.created_at AS last_event_at,
    e.details AS last_event_details
FROM org_invitations i
LEFT JOIN LATERAL (
    SELECT * FROM invitation_events
    WHERE invitation_id = i.id
    ORDER BY created_at DESC
    LIMIT 1
) e ON TRUE
ORDER BY i.created_at DESC;

COMMENT ON VIEW invitation_history_view IS 'Invitation history with most recent event';

COMMIT;
