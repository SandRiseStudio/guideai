"""
Data models for internal authentication.

These models support username/password authentication for local/air-gapped
environments where OAuth providers are unavailable.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class User:
    """Internal user account for username/password authentication."""

    id: str  # UUID
    username: str  # Unique username
    email: str  # Email address (optional for air-gapped)
    hashed_password: str  # bcrypt hashed password
    created_at: datetime
    updated_at: datetime
    is_active: bool = True
    is_admin: bool = False

    def to_dict(self) -> dict:
        """Convert to dictionary (safe for serialization, excludes password)."""
        return {
            "id": self.id,
            "username": self.username,
            "email": self.email,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "is_active": self.is_active,
            "is_admin": self.is_admin,
        }


@dataclass
class PasswordResetToken:
    """Token for password reset flow."""

    id: str  # UUID
    user_id: str  # User this token is for
    token: str  # Random secure token
    created_at: datetime
    expires_at: datetime
    used_at: Optional[datetime] = None

    @property
    def is_valid(self) -> bool:
        """Check if token is still valid.

        Handles both timezone-aware (PostgreSQL) and naive datetimes.
        """
        now = datetime.now(timezone.utc)
        expires_at = self.expires_at
        # Handle naive datetime from older code or tests
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return (
            self.used_at is None
            and expires_at > now
        )

    def to_dict(self) -> dict:
        """Convert to dictionary (safe for serialization, excludes token)."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "used_at": self.used_at.isoformat() if self.used_at else None,
            "is_valid": self.is_valid,
        }


@dataclass
class InternalSession:
    """Session information for internal auth (replaces device flow session)."""

    session_id: str  # UUID
    user_id: str
    username: str
    access_token: str  # JWT token
    refresh_token: str  # JWT refresh token
    created_at: datetime
    expires_at: datetime

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "username": self.username,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass
class FederatedIdentity:
    """Represents an OAuth identity linked to an internal user."""

    id: Optional[str] = None  # UUID
    user_id: Optional[str] = None  # Internal user ID this identity is linked to
    provider: Optional[str] = None  # OAuth provider (e.g., 'google', 'github')
    provider_user_id: Optional[str] = None  # User ID from the OAuth provider
    provider_email: Optional[str] = None  # Email from the OAuth provider
    provider_username: Optional[str] = None  # Username from the OAuth provider
    provider_display_name: Optional[str] = None  # Display name from the OAuth provider
    provider_avatar_url: Optional[str] = None  # Avatar URL from the OAuth provider
    access_token_encrypted: Optional[str] = None  # Encrypted OAuth access token
    refresh_token_encrypted: Optional[str] = None  # Encrypted OAuth refresh token
    token_expires_at: Optional[datetime] = None  # When the OAuth token expires
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "provider": self.provider,
            "provider_user_id": self.provider_user_id,
            "provider_email": self.provider_email,
            "provider_username": self.provider_username,
            "provider_display_name": self.provider_display_name,
            "provider_avatar_url": self.provider_avatar_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# SQL Schema for reference (supports both SQLite and Postgres)
USERS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS internal_users (
    id VARCHAR(36) PRIMARY KEY,
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255),
    hashed_password VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_admin BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_users_username ON internal_users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON internal_users(email);
"""

PASSWORD_RESET_TOKENS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    token VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES internal_users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reset_tokens_token ON password_reset_tokens(token);
CREATE INDEX IF NOT EXISTS idx_reset_tokens_user_id ON password_reset_tokens(user_id);
"""

INTERNAL_SESSIONS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS internal_sessions (
    session_id VARCHAR(36) PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    username VARCHAR(255) NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    FOREIGN KEY (user_id) REFERENCES internal_users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON internal_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON internal_sessions(expires_at);
"""
