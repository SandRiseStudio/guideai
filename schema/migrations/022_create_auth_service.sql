-- Migration: 022_create_auth_service.sql
-- Description: Create tables for internal authentication service
-- Date: 2025-12-03
-- Behavior: behavior_migrate_postgres_schema
--
-- This migration creates the schema for the UserService which handles
-- internal username/password authentication for air-gapped environments.
--
-- Tables:
--   - internal_users: User accounts with bcrypt-hashed passwords
--   - password_reset_tokens: Secure tokens for password reset flow
--   - internal_sessions: JWT session tracking
--
-- Rollback: DROP TABLE IF EXISTS internal_sessions, password_reset_tokens, internal_users CASCADE;

-- =============================================================================
-- INTERNAL USERS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS internal_users (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255),
    hashed_password VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_internal_users_username ON internal_users(username);
CREATE INDEX IF NOT EXISTS idx_internal_users_email ON internal_users(email) WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_internal_users_active ON internal_users(is_active) WHERE is_active = TRUE;

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_internal_users_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_internal_users_updated_at ON internal_users;
CREATE TRIGGER trigger_internal_users_updated_at
    BEFORE UPDATE ON internal_users
    FOR EACH ROW
    EXECUTE FUNCTION update_internal_users_updated_at();

COMMENT ON TABLE internal_users IS 'User accounts for internal username/password authentication';
COMMENT ON COLUMN internal_users.hashed_password IS 'bcrypt-hashed password (cost factor 12)';

-- =============================================================================
-- PASSWORD RESET TOKENS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES internal_users(id) ON DELETE CASCADE,
    token VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ
);

-- Index for token lookup (most common query)
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_token ON password_reset_tokens(token);
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_user_id ON password_reset_tokens(user_id);
-- Index for cleanup of expired tokens
CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_expires ON password_reset_tokens(expires_at)
    WHERE used_at IS NULL;

COMMENT ON TABLE password_reset_tokens IS 'Secure tokens for password reset flow with expiration';

-- =============================================================================
-- INTERNAL SESSIONS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS internal_sessions (
    session_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL REFERENCES internal_users(id) ON DELETE CASCADE,
    username VARCHAR(255) NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    ip_address INET,
    user_agent TEXT
);

-- Index for session lookups
CREATE INDEX IF NOT EXISTS idx_internal_sessions_user_id ON internal_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_internal_sessions_expires ON internal_sessions(expires_at)
    WHERE revoked_at IS NULL;
-- Index for active sessions cleanup
CREATE INDEX IF NOT EXISTS idx_internal_sessions_active ON internal_sessions(user_id, expires_at)
    WHERE revoked_at IS NULL;

COMMENT ON TABLE internal_sessions IS 'JWT session tracking for internal authentication';
COMMENT ON COLUMN internal_sessions.revoked_at IS 'NULL means active, set to timestamp when explicitly logged out';

-- =============================================================================
-- AUDIT FUNCTIONS (Optional - for compliance)
-- =============================================================================

-- Function to clean up expired tokens (can be called periodically)
CREATE OR REPLACE FUNCTION cleanup_expired_auth_tokens()
RETURNS INTEGER AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM password_reset_tokens
    WHERE expires_at < NOW() - INTERVAL '7 days';
    GET DIAGNOSTICS deleted_count = ROW_COUNT;

    DELETE FROM internal_sessions
    WHERE expires_at < NOW() - INTERVAL '30 days'
    AND revoked_at IS NOT NULL;

    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_expired_auth_tokens IS 'Removes expired reset tokens and old revoked sessions';

-- =============================================================================
-- VERIFICATION QUERY
-- =============================================================================

DO $$
BEGIN
    RAISE NOTICE 'Migration 022_create_auth_service.sql completed successfully';
    RAISE NOTICE 'Tables created: internal_users, password_reset_tokens, internal_sessions';
END $$;
