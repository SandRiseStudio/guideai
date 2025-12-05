"""Shared helpers for Postgres DSN resolution and overrides.

Applies behavior_externalize_configuration by ensuring all services honor
GUIDEAI_PG_HOST_* and GUIDEAI_PG_PORT_* overrides even when full DSNs are
predefined via environment variables. This allows Podman/Docker containers to
connect to host databases without mutating every DSN string manually.
"""

from __future__ import annotations

import os
from typing import Optional
from urllib.parse import urlparse, urlunparse, quote


def _component_env(service: str, suffix: str) -> Optional[str]:
    """Fetch a GUIDEAI_PG_{suffix}_{service} environment variable."""

    key = f"GUIDEAI_PG_{suffix}_{service.upper()}"
    return os.getenv(key)


def apply_host_overrides(dsn: Optional[str], service: str) -> Optional[str]:
    """Rewrite DSN host/port when GUIDEAI_PG_HOST/PORT overrides are present.

    Args:
        dsn: Original DSN string or None.
        service: Service identifier suffix (e.g., "BEHAVIOR").

    Returns:
        DSN string with host/port overrides applied if configured.
    """

    if not dsn:
        return dsn

    override_host = _component_env(service, "HOST")
    override_port = _component_env(service, "PORT")
    if not override_host and not override_port:
        return dsn

    parsed = urlparse(dsn)
    hostname = override_host or (parsed.hostname or "")
    port = override_port or (str(parsed.port) if parsed.port else "")

    # Reconstruct credentials with proper encoding.
    auth = ""
    if parsed.username:
        auth = quote(parsed.username, safe="")
        if parsed.password is not None:
            auth += f":{quote(parsed.password, safe='')}"
        auth += "@"

    host_display = hostname
    if ":" in hostname and not hostname.startswith("["):
        host_display = f"[{hostname}]"

    netloc = auth + host_display
    if port:
        netloc += f":{port}"

    rebuilt = parsed._replace(netloc=netloc)
    return urlunparse(rebuilt)


def build_dsn_from_components(service: str) -> Optional[str]:
    """Construct a DSN purely from GUIDEAI_PG_* components if available."""

    host = _component_env(service, "HOST")
    port = _component_env(service, "PORT")
    user = _component_env(service, "USER")
    password = _component_env(service, "PASS")
    dbname = _component_env(service, "DB") or f"guideai_{service.lower()}"

    if not all([host, port, user, password]):
        return None

    auth = quote(user, safe="")
    auth += f":{quote(password, safe='')}" if password else ""
    netloc = f"{auth}@{host}:{port}"

    params = _component_env(service, "PARAMS")
    query = params if params and params.startswith("?") else (f"?{params}" if params else "")
    return f"postgresql://{netloc}/{dbname}{query}"


def resolve_postgres_dsn(
    *,
    service: str,
    explicit_dsn: Optional[str],
    env_var: str,
    default_dsn: str,
) -> str:
    """Resolve and normalize DSNs for services with layered fallbacks."""

    candidate = explicit_dsn or os.getenv(env_var) or build_dsn_from_components(service) or default_dsn
    return apply_host_overrides(candidate, service)
