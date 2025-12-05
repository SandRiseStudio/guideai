"""
OAuth provider implementations for GuideAI multi-provider authentication.

Supports:
- GitHub OAuth (device flow)
- GitLab OAuth (device flow)
- Bitbucket OAuth (device flow)
- Google OAuth (device flow)
- Internal auth (username/password)
"""

from .base import (
    OAuthProvider,
    DeviceCodeResponse,
    TokenResponse,
    UserInfo,
    AuthorizationPendingError,
    SlowDownError,
    ExpiredTokenError,
    AccessDeniedError,
    InvalidTokenError,
    InvalidCredentialsError,
    OAuthError,
)
from .github import GitHubOAuthProvider
from .google import GoogleOAuthProvider
from .internal import InternalAuthProvider
from .registry import ProviderRegistry

__all__ = [
    "OAuthProvider",
    "DeviceCodeResponse",
    "TokenResponse",
    "UserInfo",
    "AuthorizationPendingError",
    "SlowDownError",
    "ExpiredTokenError",
    "AccessDeniedError",
    "InvalidTokenError",
    "InvalidCredentialsError",
    "OAuthError",
    "GitHubOAuthProvider",
    "GoogleOAuthProvider",
    "InternalAuthProvider",
    "ProviderRegistry",
]
