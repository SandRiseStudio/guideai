"""
MCP Rate Limiter - Request-level rate limiting for MCP tool invocations.

Implements per-client and per-tool throttling with configurable limits to prevent
abuse by automated agents per MCP_SERVER_DESIGN.md §9.

Key Features:
- Token bucket algorithm for smooth rate limiting
- Per-client tracking (based on session_id)
- Per-tool limits for sensitive operations
- Configurable via environment variables
- Metrics and telemetry integration
"""

from __future__ import annotations
import logging
import os
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class RateLimitDecision(str, Enum):
    """Decision from rate limiter."""
    ALLOW = "allow"
    DENY = "deny"
    WARN = "warn"  # Allow but log warning (soft limit)


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit rule."""
    name: str
    max_requests: int  # Maximum requests allowed in window
    window_seconds: int  # Time window for counting requests
    burst_limit: int  # Maximum burst (token bucket capacity)
    refill_rate: float  # Tokens per second
    soft_limit_pct: float = 0.8  # Warn at 80% of limit

    def __post_init__(self):
        if self.max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.burst_limit <= 0:
            raise ValueError("burst_limit must be positive")
        if self.refill_rate <= 0:
            raise ValueError("refill_rate must be positive")


@dataclass
class TokenBucket:
    """Token bucket for smooth rate limiting."""
    tokens: float
    last_update: float  # Unix timestamp
    capacity: int
    refill_rate: float  # Tokens per second

    def consume(self, count: int = 1) -> Tuple[bool, float]:
        """
        Attempt to consume tokens. Returns (success, remaining_tokens).
        Automatically refills based on elapsed time.
        """
        now = time.time()
        elapsed = now - self.last_update

        # Refill tokens based on elapsed time
        self.tokens = min(self.capacity, self.tokens + (elapsed * self.refill_rate))
        self.last_update = now

        if self.tokens >= count:
            self.tokens -= count
            return True, self.tokens
        else:
            return False, self.tokens


@dataclass
class ClientState:
    """Per-client rate limiting state."""
    client_id: str
    global_bucket: TokenBucket
    tool_buckets: Dict[str, TokenBucket] = field(default_factory=dict)
    request_count: int = 0
    first_request_time: float = field(default_factory=time.time)
    last_request_time: float = field(default_factory=time.time)
    violations: int = 0
    warnings: int = 0


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""
    decision: RateLimitDecision
    client_id: str
    tool_name: str
    remaining_tokens: float
    retry_after_seconds: Optional[float] = None
    message: str = ""
    rule_name: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision": self.decision.value,
            "client_id": self.client_id,
            "tool_name": self.tool_name,
            "remaining_tokens": round(self.remaining_tokens, 2),
            "retry_after_seconds": self.retry_after_seconds,
            "message": self.message,
            "rule_name": self.rule_name,
        }


class MCPRateLimiter:
    """
    MCP Server rate limiter with per-client and per-tool throttling.

    Default limits (configurable via environment):
    - Global: 100 requests/minute per client
    - Auth tools: 10 requests/minute
    - Write tools: 30 requests/minute
    - Read tools: 60 requests/minute

    Environment variables:
    - MCP_RATE_LIMIT_ENABLED: Enable/disable (default: true)
    - MCP_RATE_LIMIT_GLOBAL_MAX: Global max requests (default: 100)
    - MCP_RATE_LIMIT_GLOBAL_WINDOW: Window in seconds (default: 60)
    - MCP_RATE_LIMIT_AUTH_MAX: Auth tool max requests (default: 10)
    - MCP_RATE_LIMIT_WRITE_MAX: Write tool max requests (default: 30)
    - MCP_RATE_LIMIT_READ_MAX: Read tool max requests (default: 60)
    """

    # Tool categories for differentiated rate limiting
    AUTH_TOOLS = {
        "auth.deviceLogin",
        "auth.authStatus",
        "auth.refreshToken",
        "auth.logout",
        "auth.ensureGrant",
        "auth.listGrants",
        "auth.revoke",
        "auth.status",
    }

    WRITE_TOOLS = {
        "behaviors.createDraft",
        "behaviors.update",
        "behaviors.approve",
        "workflows.create",
        "workflows.update",
        "workflows.delete",
        "runs.create",
        "runs.updateStatus",
        "actions.create",
        "compliance.recordStep",
        "tasks.create",
        "tasks.updateStatus",
        "amprealize.apply",
        "amprealize.destroy",
        "config.update",
        "reflections.submitTrace",
    }

    # All other tools are considered READ tools

    # High-risk tools that should be more aggressively rate limited
    HIGH_RISK_TOOLS = {
        "auth.deviceLogin",
        "config.update",
        "behaviors.approve",
        "amprealize.destroy",
    }

    def __init__(
        self,
        enabled: Optional[bool] = None,
        global_config: Optional[RateLimitConfig] = None,
        auth_config: Optional[RateLimitConfig] = None,
        write_config: Optional[RateLimitConfig] = None,
        read_config: Optional[RateLimitConfig] = None,
        high_risk_config: Optional[RateLimitConfig] = None,
    ) -> None:
        """Initialize rate limiter with configurable limits."""
        self._enabled = enabled if enabled is not None else self._env_bool("MCP_RATE_LIMIT_ENABLED", True)
        self._lock = Lock()
        self._clients: Dict[str, ClientState] = {}

        # Metrics
        self._metrics = {
            "checks_total": 0,
            "allows_total": 0,
            "denies_total": 0,
            "warnings_total": 0,
            "clients_seen": 0,
        }

        # Configure limits from environment or defaults
        self._global_config = global_config or RateLimitConfig(
            name="global",
            max_requests=self._env_int("MCP_RATE_LIMIT_GLOBAL_MAX", 100),
            window_seconds=self._env_int("MCP_RATE_LIMIT_GLOBAL_WINDOW", 60),
            burst_limit=self._env_int("MCP_RATE_LIMIT_GLOBAL_BURST", 20),
            refill_rate=self._env_float("MCP_RATE_LIMIT_GLOBAL_REFILL", 1.67),  # ~100/min
        )

        self._auth_config = auth_config or RateLimitConfig(
            name="auth",
            max_requests=self._env_int("MCP_RATE_LIMIT_AUTH_MAX", 10),
            window_seconds=60,
            burst_limit=self._env_int("MCP_RATE_LIMIT_AUTH_BURST", 5),
            refill_rate=0.17,  # ~10/min
        )

        self._write_config = write_config or RateLimitConfig(
            name="write",
            max_requests=self._env_int("MCP_RATE_LIMIT_WRITE_MAX", 30),
            window_seconds=60,
            burst_limit=self._env_int("MCP_RATE_LIMIT_WRITE_BURST", 10),
            refill_rate=0.5,  # ~30/min
        )

        self._read_config = read_config or RateLimitConfig(
            name="read",
            max_requests=self._env_int("MCP_RATE_LIMIT_READ_MAX", 60),
            window_seconds=60,
            burst_limit=self._env_int("MCP_RATE_LIMIT_READ_BURST", 15),
            refill_rate=1.0,  # ~60/min
        )

        self._high_risk_config = high_risk_config or RateLimitConfig(
            name="high_risk",
            max_requests=self._env_int("MCP_RATE_LIMIT_HIGH_RISK_MAX", 5),
            window_seconds=60,
            burst_limit=2,
            refill_rate=0.08,  # ~5/min
        )

        logger.info(
            f"MCPRateLimiter initialized: enabled={self._enabled}, "
            f"global={self._global_config.max_requests}/min, "
            f"auth={self._auth_config.max_requests}/min, "
            f"write={self._write_config.max_requests}/min, "
            f"read={self._read_config.max_requests}/min, "
            f"high_risk={self._high_risk_config.max_requests}/min"
        )

    @staticmethod
    def _env_bool(key: str, default: bool) -> bool:
        """Get boolean from environment."""
        val = os.environ.get(key, "").lower()
        if val in ("true", "1", "yes", "on"):
            return True
        elif val in ("false", "0", "no", "off"):
            return False
        return default

    @staticmethod
    def _env_int(key: str, default: int) -> int:
        """Get integer from environment."""
        try:
            return int(os.environ.get(key, str(default)))
        except ValueError:
            return default

    @staticmethod
    def _env_float(key: str, default: float) -> float:
        """Get float from environment."""
        try:
            return float(os.environ.get(key, str(default)))
        except ValueError:
            return default

    def _get_tool_config(self, tool_name: str) -> RateLimitConfig:
        """Get rate limit config for a tool based on its category."""
        if tool_name in self.HIGH_RISK_TOOLS:
            return self._high_risk_config
        elif tool_name in self.AUTH_TOOLS:
            return self._auth_config
        elif tool_name in self.WRITE_TOOLS:
            return self._write_config
        else:
            return self._read_config

    def _get_or_create_client(self, client_id: str) -> ClientState:
        """Get or create client state with proper locking."""
        if client_id not in self._clients:
            now = time.time()
            self._clients[client_id] = ClientState(
                client_id=client_id,
                global_bucket=TokenBucket(
                    tokens=self._global_config.burst_limit,
                    last_update=now,
                    capacity=self._global_config.burst_limit,
                    refill_rate=self._global_config.refill_rate,
                ),
            )
            self._metrics["clients_seen"] += 1
            logger.debug(f"Created rate limit state for client: {client_id}")
        return self._clients[client_id]

    def _get_or_create_tool_bucket(
        self, client_state: ClientState, tool_name: str
    ) -> TokenBucket:
        """Get or create tool-specific bucket."""
        if tool_name not in client_state.tool_buckets:
            config = self._get_tool_config(tool_name)
            now = time.time()
            client_state.tool_buckets[tool_name] = TokenBucket(
                tokens=config.burst_limit,
                last_update=now,
                capacity=config.burst_limit,
                refill_rate=config.refill_rate,
            )
        return client_state.tool_buckets[tool_name]

    def check(self, client_id: str, tool_name: str) -> RateLimitResult:
        """
        Check if a request should be allowed.

        Args:
            client_id: Unique client identifier (session_id, user_id, etc.)
            tool_name: MCP tool being invoked

        Returns:
            RateLimitResult with decision and metadata
        """
        self._metrics["checks_total"] += 1

        # Fast path: rate limiting disabled
        if not self._enabled:
            return RateLimitResult(
                decision=RateLimitDecision.ALLOW,
                client_id=client_id,
                tool_name=tool_name,
                remaining_tokens=float("inf"),
                message="Rate limiting disabled",
            )

        with self._lock:
            client = self._get_or_create_client(client_id)
            tool_config = self._get_tool_config(tool_name)
            tool_bucket = self._get_or_create_tool_bucket(client, tool_name)

            # Check global limit first
            global_ok, global_remaining = client.global_bucket.consume(1)

            if not global_ok:
                self._metrics["denies_total"] += 1
                client.violations += 1
                retry_after = (1.0 - global_remaining) / self._global_config.refill_rate

                logger.warning(
                    f"Rate limit DENIED: client={client_id}, tool={tool_name}, "
                    f"rule=global, remaining={global_remaining:.2f}"
                )

                return RateLimitResult(
                    decision=RateLimitDecision.DENY,
                    client_id=client_id,
                    tool_name=tool_name,
                    remaining_tokens=global_remaining,
                    retry_after_seconds=max(1.0, retry_after),
                    message=f"Global rate limit exceeded. Retry after {retry_after:.1f}s",
                    rule_name="global",
                )

            # Check tool-specific limit
            tool_ok, tool_remaining = tool_bucket.consume(1)

            if not tool_ok:
                # Refund global token since tool limit blocked
                client.global_bucket.tokens = min(
                    client.global_bucket.capacity,
                    client.global_bucket.tokens + 1
                )

                self._metrics["denies_total"] += 1
                client.violations += 1
                retry_after = (1.0 - tool_remaining) / tool_config.refill_rate

                logger.warning(
                    f"Rate limit DENIED: client={client_id}, tool={tool_name}, "
                    f"rule={tool_config.name}, remaining={tool_remaining:.2f}"
                )

                return RateLimitResult(
                    decision=RateLimitDecision.DENY,
                    client_id=client_id,
                    tool_name=tool_name,
                    remaining_tokens=tool_remaining,
                    retry_after_seconds=max(1.0, retry_after),
                    message=f"Tool rate limit exceeded for {tool_config.name}. Retry after {retry_after:.1f}s",
                    rule_name=tool_config.name,
                )

            # Check for soft limit warning (only if soft limits are enabled)
            global_pct = client.global_bucket.tokens / client.global_bucket.capacity
            tool_pct = tool_bucket.tokens / tool_bucket.capacity

            # Warning triggers when remaining percentage drops below (1 - soft_limit_pct)
            # e.g., soft_limit_pct=0.8 means warn when 80% consumed (20% remaining)
            # soft_limit_pct=0.0 disables warnings
            global_warn = self._global_config.soft_limit_pct > 0 and global_pct < (1 - self._global_config.soft_limit_pct)
            tool_warn = tool_config.soft_limit_pct > 0 and tool_pct < (1 - tool_config.soft_limit_pct)

            if global_warn or tool_warn:
                self._metrics["warnings_total"] += 1
                client.warnings += 1

                logger.info(
                    f"Rate limit WARNING: client={client_id}, tool={tool_name}, "
                    f"global_remaining={global_remaining:.2f}, tool_remaining={tool_remaining:.2f}"
                )

                return RateLimitResult(
                    decision=RateLimitDecision.WARN,
                    client_id=client_id,
                    tool_name=tool_name,
                    remaining_tokens=min(global_remaining, tool_remaining),
                    message="Approaching rate limit",
                    rule_name=tool_config.name if tool_pct < global_pct else "global",
                )

            # All checks passed
            self._metrics["allows_total"] += 1
            client.request_count += 1
            client.last_request_time = time.time()

            return RateLimitResult(
                decision=RateLimitDecision.ALLOW,
                client_id=client_id,
                tool_name=tool_name,
                remaining_tokens=min(global_remaining, tool_remaining),
            )

    def get_client_status(self, client_id: str) -> Optional[Dict[str, Any]]:
        """Get current rate limit status for a client."""
        with self._lock:
            if client_id not in self._clients:
                return None

            client = self._clients[client_id]
            now = time.time()

            # Calculate current token levels
            global_tokens = min(
                client.global_bucket.capacity,
                client.global_bucket.tokens +
                (now - client.global_bucket.last_update) * client.global_bucket.refill_rate
            )

            tool_status = {}
            for tool_name, bucket in client.tool_buckets.items():
                tokens = min(
                    bucket.capacity,
                    bucket.tokens + (now - bucket.last_update) * bucket.refill_rate
                )
                tool_status[tool_name] = {
                    "tokens": round(tokens, 2),
                    "capacity": bucket.capacity,
                    "pct_remaining": round(tokens / bucket.capacity * 100, 1),
                }

            return {
                "client_id": client_id,
                "global": {
                    "tokens": round(global_tokens, 2),
                    "capacity": client.global_bucket.capacity,
                    "pct_remaining": round(global_tokens / client.global_bucket.capacity * 100, 1),
                },
                "tools": tool_status,
                "stats": {
                    "request_count": client.request_count,
                    "violations": client.violations,
                    "warnings": client.warnings,
                    "first_request": datetime.fromtimestamp(client.first_request_time).isoformat(),
                    "last_request": datetime.fromtimestamp(client.last_request_time).isoformat(),
                },
            }

    def get_metrics(self) -> Dict[str, Any]:
        """Get rate limiter metrics for monitoring."""
        with self._lock:
            return {
                **self._metrics,
                "active_clients": len(self._clients),
                "enabled": self._enabled,
                "config": {
                    "global": {
                        "max_requests": self._global_config.max_requests,
                        "window_seconds": self._global_config.window_seconds,
                        "burst_limit": self._global_config.burst_limit,
                    },
                    "auth": {
                        "max_requests": self._auth_config.max_requests,
                        "burst_limit": self._auth_config.burst_limit,
                    },
                    "write": {
                        "max_requests": self._write_config.max_requests,
                        "burst_limit": self._write_config.burst_limit,
                    },
                    "read": {
                        "max_requests": self._read_config.max_requests,
                        "burst_limit": self._read_config.burst_limit,
                    },
                    "high_risk": {
                        "max_requests": self._high_risk_config.max_requests,
                        "burst_limit": self._high_risk_config.burst_limit,
                    },
                },
            }

    def reset_client(self, client_id: str) -> bool:
        """Reset rate limit state for a client (admin operation)."""
        with self._lock:
            if client_id in self._clients:
                del self._clients[client_id]
                logger.info(f"Reset rate limit state for client: {client_id}")
                return True
            return False

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable rate limiting."""
        self._enabled = enabled
        logger.info(f"Rate limiting {'enabled' if enabled else 'disabled'}")

    def cleanup_stale_clients(self, max_age_seconds: int = 3600) -> int:
        """Remove clients that haven't made requests in max_age_seconds."""
        now = time.time()
        removed = 0

        with self._lock:
            stale_clients = [
                client_id for client_id, state in self._clients.items()
                if now - state.last_request_time > max_age_seconds
            ]

            for client_id in stale_clients:
                del self._clients[client_id]
                removed += 1

        if removed > 0:
            logger.info(f"Cleaned up {removed} stale rate limit clients")

        return removed
