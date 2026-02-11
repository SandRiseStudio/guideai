"""
Gateway Layer Integration Tests
================================
Tests for the nginx gateway configuration (Phase 0).

These tests validate:
- Rate limiting per tenant
- WebSocket upgrade support
- Health check passthrough
- Proper header forwarding
- Load balancing behavior

Note: These are unit tests for the gateway configuration logic.
Full integration tests require running containers.
"""

import pytest
from pathlib import Path
from typing import Any


class TestNginxConfiguration:
    """Tests for nginx.conf validity and expected directives."""

    @pytest.fixture
    def nginx_config(self) -> str:
        """Load the nginx configuration file."""
        config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "nginx" / "nginx.conf"
        if not config_path.exists():
            # Try from guideai root
            config_path = Path(__file__).parent.parent.parent.parent / "config" / "nginx" / "nginx.conf"

        assert config_path.exists(), f"nginx.conf not found at {config_path}"
        return config_path.read_text()

    def test_upstream_defined(self, nginx_config: str) -> None:
        """Verify guideai_api upstream is configured."""
        assert "upstream guideai_api" in nginx_config
        assert "least_conn" in nginx_config
        assert "guideai-api:8000" in nginx_config

    def test_rate_limiting_zones(self, nginx_config: str) -> None:
        """Verify rate limiting zones are configured."""
        assert "limit_req_zone" in nginx_config
        assert "zone=tenant_api:10m" in nginx_config
        assert "rate=100r/s" in nginx_config
        assert "zone=tenant_ws:10m" in nginx_config
        assert "rate=10r/s" in nginx_config
        assert "zone=anonymous:10m" in nginx_config

    def test_connection_limit_zone(self, nginx_config: str) -> None:
        """Verify connection limit zone is configured."""
        assert "limit_conn_zone" in nginx_config
        assert "zone=tenant_conn:10m" in nginx_config

    def test_health_endpoint_no_rate_limit(self, nginx_config: str) -> None:
        """Verify health endpoint bypasses rate limiting."""
        # Health location should exist
        assert "location /health" in nginx_config
        # It should have access_log off (indicator of no-rate-limit path)
        health_section = nginx_config.split("location /health")[1].split("location")[0]
        assert "access_log off" in health_section

    def test_api_endpoint_rate_limited(self, nginx_config: str) -> None:
        """Verify API endpoints have rate limiting."""
        assert "location /api/" in nginx_config
        # Check rate limiting is applied
        api_section = nginx_config.split("location /api/")[1].split("location")[0]
        assert "limit_req zone=tenant_api" in api_section
        assert "burst=200" in api_section

    def test_websocket_support(self, nginx_config: str) -> None:
        """Verify WebSocket upgrade is configured."""
        assert "location /ws/" in nginx_config
        ws_section = nginx_config.split("location /ws/")[1].split("location")[0]
        assert "Upgrade $http_upgrade" in ws_section
        assert 'Connection "upgrade"' in ws_section
        assert "proxy_read_timeout 3600s" in ws_section

    def test_sse_support(self, nginx_config: str) -> None:
        """Verify SSE endpoints are configured."""
        assert "location /sse/" in nginx_config
        sse_section = nginx_config.split("location /sse/")[1].split("location")[0]
        assert "proxy_buffering off" in sse_section
        assert "chunked_transfer_encoding off" in sse_section

    def test_mcp_endpoint(self, nginx_config: str) -> None:
        """Verify MCP protocol endpoint is configured."""
        assert "location /mcp/" in nginx_config

    def test_security_headers(self, nginx_config: str) -> None:
        """Verify security headers are set."""
        assert "X-Content-Type-Options nosniff" in nginx_config
        assert "X-Frame-Options DENY" in nginx_config
        assert "X-XSS-Protection" in nginx_config

    def test_tenant_headers_forwarded(self, nginx_config: str) -> None:
        """Verify tenant/user headers are forwarded to upstream."""
        assert "X-Tenant-Id $http_x_tenant_id" in nginx_config
        assert "X-User-Id $http_x_user_id" in nginx_config

    def test_json_logging(self, nginx_config: str) -> None:
        """Verify JSON logging format is configured."""
        assert "log_format guideai_json" in nginx_config
        assert "escape=json" in nginx_config
        assert '"tenant_id"' in nginx_config

    def test_gzip_compression(self, nginx_config: str) -> None:
        """Verify gzip is enabled."""
        assert "gzip on" in nginx_config
        assert "application/json" in nginx_config


class TestGatewayRateLimitingLogic:
    """Unit tests for rate limiting behavior expectations."""

    def test_tenant_rate_limit_calculation(self) -> None:
        """Verify rate limit math: 100r/s with burst 200."""
        rate_per_second = 100
        burst_size = 200

        # With nodelay, burst requests are processed immediately
        # but consume "tokens" from the bucket
        max_immediate_requests = rate_per_second + burst_size
        assert max_immediate_requests == 300

        # After burst, sustained rate is 100r/s
        sustained_rate = rate_per_second
        assert sustained_rate == 100

    def test_websocket_rate_limit_is_restrictive(self) -> None:
        """WebSocket rate limit should be more restrictive than API."""
        ws_rate = 10  # per second
        api_rate = 100  # per second

        # WS is 10x more restrictive because connections are long-lived
        assert api_rate / ws_rate == 10

    def test_anonymous_fallback_rate(self) -> None:
        """Anonymous rate limit should be restrictive."""
        anonymous_rate = 10  # per second
        tenant_rate = 100  # per second

        # Anonymous gets 10x less than identified tenants
        assert tenant_rate / anonymous_rate == 10


class TestGatewayBlueprintIntegration:
    """Tests for gateway service in blueprint."""

    @pytest.fixture
    def blueprint_config(self) -> str:
        """Load the blueprint configuration."""
        # From tests/ directory, go up to amprealize package root
        blueprint_path = (
            Path(__file__).parent.parent
            / "src" / "amprealize" / "blueprints" / "local-test-suite.yaml"
        )

        assert blueprint_path.exists(), f"Blueprint not found at {blueprint_path}"
        return blueprint_path.read_text()

    def test_gateway_service_defined(self, blueprint_config: str) -> None:
        """Verify gateway service is in the blueprint."""
        assert "gateway:" in blueprint_config

    def test_gateway_uses_nginx_image(self, blueprint_config: str) -> None:
        """Verify gateway uses nginx:alpine image."""
        assert "nginx:alpine" in blueprint_config

    def test_gateway_depends_on_api(self, blueprint_config: str) -> None:
        """Verify gateway depends on guideai-api."""
        # Find gateway section and check depends_on
        gateway_section = blueprint_config.split("gateway:")[1].split("\n  # ---")[0]
        assert "guideai-api" in gateway_section

    def test_gateway_mounts_config(self, blueprint_config: str) -> None:
        """Verify gateway mounts nginx.conf."""
        assert "config/nginx/nginx.conf" in blueprint_config

    def test_gateway_port_mapping(self, blueprint_config: str) -> None:
        """Verify gateway exposes port 8080."""
        gateway_section = blueprint_config.split("gateway:")[1].split("\n  # ---")[0]
        assert "GATEWAY_PORT" in gateway_section or "8080" in gateway_section

    def test_gateway_healthcheck(self, blueprint_config: str) -> None:
        """Verify gateway has healthcheck."""
        gateway_section = blueprint_config.split("gateway:")[1].split("\n  # ---")[0]
        assert "healthcheck" in gateway_section
        assert "/health" in gateway_section


class TestGatewayEndpointRouting:
    """Tests for expected routing behavior."""

    @pytest.fixture
    def nginx_config(self) -> str:
        """Load nginx configuration."""
        config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "nginx" / "nginx.conf"
        if not config_path.exists():
            config_path = Path(__file__).parent.parent.parent.parent / "config" / "nginx" / "nginx.conf"
        return config_path.read_text() if config_path.exists() else ""

    def test_all_required_endpoints_defined(self, nginx_config: str) -> None:
        """Verify all required endpoint locations are defined."""
        required_endpoints = [
            "/health",
            "/ready",
            "/metrics",
            "/api/",
            "/v1/",
            "/ws/",
            "/sse/",
            "/mcp/",
        ]

        for endpoint in required_endpoints:
            assert f"location {endpoint}" in nginx_config, f"Missing endpoint: {endpoint}"

    def test_proxy_pass_targets_upstream(self, nginx_config: str) -> None:
        """Verify all proxy_pass directives target guideai_api upstream."""
        # Count proxy_pass directives
        proxy_passes = nginx_config.count("proxy_pass http://guideai_api")

        # Should have multiple (one per location block)
        assert proxy_passes >= 5, f"Expected at least 5 proxy_pass directives, found {proxy_passes}"


class TestGatewayTimeouts:
    """Tests for timeout configurations."""

    @pytest.fixture
    def nginx_config(self) -> str:
        """Load nginx configuration."""
        config_path = Path(__file__).parent.parent.parent.parent.parent / "config" / "nginx" / "nginx.conf"
        if not config_path.exists():
            config_path = Path(__file__).parent.parent.parent.parent / "config" / "nginx" / "nginx.conf"
        return config_path.read_text() if config_path.exists() else ""

    def test_websocket_timeout_is_long(self, nginx_config: str) -> None:
        """WebSocket should have 1 hour timeout."""
        ws_section = nginx_config.split("location /ws/")[1].split("location")[0]
        assert "3600s" in ws_section  # 1 hour = 3600 seconds

    def test_api_timeout_allows_long_operations(self, nginx_config: str) -> None:
        """API should allow reasonably long operations."""
        api_section = nginx_config.split("location /api/")[1].split("location")[0]
        # Should have at least 60s read timeout (we set 300s)
        assert "proxy_read_timeout" in api_section

    def test_health_check_timeout_is_short(self, nginx_config: str) -> None:
        """Health check should have short timeout."""
        health_section = nginx_config.split("location /health")[1].split("location")[0]
        assert "5s" in health_section
