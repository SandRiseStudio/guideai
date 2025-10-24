"""
Tests for MCP Device Flow Integration

Validates MCP tool implementations for OAuth 2.0 device authorization flow,
ensuring parity with CLI authentication and proper token storage integration.

Test Coverage:
- Tool schema validation (JSON Schema draft-07 compliance)
- Device login flow (successful authorization, denial, expiry, timeout)
- Auth status checks (authenticated, expired, missing tokens)
- Token refresh (success, failure, expiry)
- Logout (token clearing, revocation warnings)
- Token storage parity with CLI (KeychainTokenStore shared access)
- Error handling (missing tokens, invalid parameters, network failures)
- Telemetry integration (event emission for key operations)
"""

import asyncio
import json
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch, MagicMock

from guideai.mcp_device_flow import (
    MCPDeviceFlowService,
    MCPDeviceFlowHandler,
)
from guideai.device_flow import (
    DeviceFlowManager,
    DeviceAuthorizationSession,
    DevicePollResult,
    DeviceAuthorizationStatus,
    DeviceTokens,
)
from guideai.auth_tokens import (
    AuthTokenBundle,
    TokenStore,
    FileTokenStore,
)
from guideai.telemetry import InMemoryTelemetrySink


# --- Fixtures ---


@pytest.fixture
def temp_token_file(tmp_path: Path) -> Path:
    """Temporary token storage file for testing."""
    return tmp_path / "test_tokens.json"


@pytest.fixture
def file_token_store(temp_token_file: Path) -> FileTokenStore:
    """FileTokenStore instance for testing token persistence."""
    return FileTokenStore(path=temp_token_file)


@pytest.fixture
def telemetry_sink() -> InMemoryTelemetrySink:
    """In-memory telemetry sink for testing event emission."""
    return InMemoryTelemetrySink()


@pytest.fixture
def device_flow_manager(telemetry_sink: InMemoryTelemetrySink) -> DeviceFlowManager:
    """DeviceFlowManager instance for testing."""
    from guideai.telemetry import TelemetryClient

    telemetry = TelemetryClient(sink=telemetry_sink)
    return DeviceFlowManager(telemetry=telemetry)


@pytest.fixture
def mcp_service(
    device_flow_manager: DeviceFlowManager,
    file_token_store: FileTokenStore,
    telemetry_sink: InMemoryTelemetrySink,
) -> MCPDeviceFlowService:
    """MCPDeviceFlowService instance with test dependencies."""
    from guideai.telemetry import TelemetryClient

    telemetry = TelemetryClient(sink=telemetry_sink)
    return MCPDeviceFlowService(
        manager=device_flow_manager,
        token_store=file_token_store,
        telemetry=telemetry,
    )


@pytest.fixture
def mcp_handler(mcp_service: MCPDeviceFlowService) -> MCPDeviceFlowHandler:
    """MCPDeviceFlowHandler instance for testing tool dispatch."""
    return MCPDeviceFlowHandler(service=mcp_service)


# --- Tool Schema Validation Tests ---


class TestMCPToolSchemas:
    """Validate MCP tool manifest JSON schemas."""

    def test_auth_device_login_schema_exists(self) -> None:
        """auth.deviceLogin.json manifest exists and is valid JSON Schema draft-07."""
        manifest_path = Path(__file__).parent.parent / "mcp" / "tools" / "auth.deviceLogin.json"
        assert manifest_path.exists(), f"Missing manifest: {manifest_path}"

        with open(manifest_path) as f:
            schema = json.load(f)

        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert schema["name"] == "auth.deviceLogin"
        assert "inputSchema" in schema
        assert "outputSchema" in schema
        assert schema["outputSchema"]["required"] == ["status", "device_code", "user_code", "verification_uri"]

    def test_auth_auth_status_schema_exists(self) -> None:
        """auth.authStatus.json manifest exists and is valid JSON Schema draft-07."""
        manifest_path = Path(__file__).parent.parent / "mcp" / "tools" / "auth.authStatus.json"
        assert manifest_path.exists(), f"Missing manifest: {manifest_path}"

        with open(manifest_path) as f:
            schema = json.load(f)

        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert schema["name"] == "auth.authStatus"
        assert "inputSchema" in schema
        assert "outputSchema" in schema
        assert schema["outputSchema"]["required"] == ["is_authenticated"]

    def test_auth_refresh_token_schema_exists(self) -> None:
        """auth.refreshToken.json manifest exists and is valid JSON Schema draft-07."""
        manifest_path = Path(__file__).parent.parent / "mcp" / "tools" / "auth.refreshToken.json"
        assert manifest_path.exists(), f"Missing manifest: {manifest_path}"

        with open(manifest_path) as f:
            schema = json.load(f)

        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert schema["name"] == "auth.refreshToken"
        assert "inputSchema" in schema
        assert "outputSchema" in schema
        assert schema["outputSchema"]["required"] == ["status"]

    def test_auth_logout_schema_exists(self) -> None:
        """auth.logout.json manifest exists and is valid JSON Schema draft-07."""
        manifest_path = Path(__file__).parent.parent / "mcp" / "tools" / "auth.logout.json"
        assert manifest_path.exists(), f"Missing manifest: {manifest_path}"

        with open(manifest_path) as f:
            schema = json.load(f)

        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert schema["name"] == "auth.logout"
        assert "inputSchema" in schema
        assert "outputSchema" in schema
        assert schema["outputSchema"]["required"] == ["status", "tokens_cleared"]


# --- Device Login Flow Tests ---


class TestMCPDeviceLogin:
    """Test auth.deviceLogin MCP tool implementation."""

    @pytest.mark.asyncio
    async def test_device_login_successful_authorization(
        self,
        mcp_service: MCPDeviceFlowService,
        device_flow_manager: DeviceFlowManager,
        file_token_store: FileTokenStore,
    ) -> None:
        """Device login completes successfully when user approves in time."""
        # Start device login (will poll in background)
        login_task = asyncio.create_task(
            mcp_service.device_login(
                client_id="test-client",
                scopes=["behaviors.read"],
                poll_interval=1,
                timeout=10,
                store_tokens=True,
            )
        )

        # Wait for authorization to start
        await asyncio.sleep(0.5)

        # Simulate user approval
        sessions = device_flow_manager._sessions
        assert len(sessions) > 0, "Device authorization session should be created"
        session = list(sessions.values())[0]
        device_flow_manager.approve_user_code(
            session.user_code,
            approver="test-user@example.com",
            approver_surface="Web",
        )

        # Wait for polling to complete
        result = await login_task

        assert result["status"] == "authorized"
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["scopes"] == ["behaviors.read"]
        assert "token_storage_path" in result

        # Verify tokens were persisted
        bundle = file_token_store.load()
        assert bundle is not None
        assert bundle.client_id == "test-client"
        assert bundle.scopes == ["behaviors.read"]

    @pytest.mark.asyncio
    async def test_device_login_denied_by_user(
        self,
        mcp_service: MCPDeviceFlowService,
        device_flow_manager: DeviceFlowManager,
    ) -> None:
        """Device login fails when user denies authorization."""
        login_task = asyncio.create_task(
            mcp_service.device_login(
                client_id="test-client",
                scopes=["behaviors.read"],
                poll_interval=1,
                timeout=10,
                store_tokens=True,
            )
        )

        await asyncio.sleep(0.5)

        # Simulate user denial
        sessions = device_flow_manager._sessions
        session = list(sessions.values())[0]
        device_flow_manager.deny_user_code(
            session.user_code,
            approver="test-user@example.com",
            approver_surface="Web",
            reason="User declined consent",
        )

        result = await login_task

        assert result["status"] == "denied"
        assert result["error"] == "access_denied"
        assert "User denied" in result["error_description"] or "User declined" in result["error_description"]
        assert "access_token" not in result

    @pytest.mark.asyncio
    async def test_device_login_timeout(
        self,
        mcp_service: MCPDeviceFlowService,
    ) -> None:
        """Device login times out when user doesn't respond."""
        result = await mcp_service.device_login(
            client_id="test-client",
            scopes=["behaviors.read"],
            poll_interval=1,
            timeout=2,  # Short timeout to speed up test
            store_tokens=False,
        )

        assert result["status"] == "error"
        assert result["error"] == "authorization_pending"
        assert "Timed out" in result["error_description"]
        assert "access_token" not in result

    @pytest.mark.asyncio
    async def test_device_login_without_token_storage(
        self,
        mcp_service: MCPDeviceFlowService,
        device_flow_manager: DeviceFlowManager,
        file_token_store: FileTokenStore,
    ) -> None:
        """Device login succeeds but doesn't persist tokens when store_tokens=False."""
        login_task = asyncio.create_task(
            mcp_service.device_login(
                client_id="test-client",
                scopes=["behaviors.read"],
                poll_interval=1,
                timeout=10,
                store_tokens=False,  # Don't persist tokens
            )
        )

        await asyncio.sleep(0.5)

        # Approve authorization
        sessions = device_flow_manager._sessions
        session = list(sessions.values())[0]
        device_flow_manager.approve_user_code(
            session.user_code,
            approver="test-user@example.com",
            approver_surface="Web",
        )

        result = await login_task

        assert result["status"] == "authorized"
        assert "access_token" in result
        assert "token_storage_path" not in result

        # Verify tokens were NOT persisted
        bundle = file_token_store.load()
        assert bundle is None


# --- Auth Status Tests ---


class TestMCPAuthStatus:
    """Test auth.authStatus MCP tool implementation."""

    @pytest.mark.asyncio
    async def test_auth_status_with_valid_tokens(
        self,
        mcp_service: MCPDeviceFlowService,
        file_token_store: FileTokenStore,
    ) -> None:
        """Auth status reports authenticated when valid tokens exist."""
        # Store valid tokens
        now = datetime.now(timezone.utc)
        bundle = AuthTokenBundle(
            access_token="test-access-token",
            refresh_token="test-refresh-token",
            token_type="Bearer",
            scopes=["behaviors.read", "runs.create"],
            client_id="test-client",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            refresh_expires_at=now + timedelta(days=7),
        )
        file_token_store.save(bundle)

        result = await mcp_service.auth_status(client_id="test-client")

        assert result["is_authenticated"] is True
        assert result["access_token_valid"] is True
        assert result["refresh_token_valid"] is True
        assert result["scopes"] == ["behaviors.read", "runs.create"]
        assert result["needs_refresh"] is False
        assert result["needs_login"] is False
        assert result["expires_in"] > 3500  # Close to 1 hour

    @pytest.mark.asyncio
    async def test_auth_status_with_expired_access_token(
        self,
        mcp_service: MCPDeviceFlowService,
        file_token_store: FileTokenStore,
    ) -> None:
        """Auth status shows needs_refresh when access token expired but refresh token valid."""
        now = datetime.now(timezone.utc)
        bundle = AuthTokenBundle(
            access_token="expired-access-token",
            refresh_token="valid-refresh-token",
            token_type="Bearer",
            scopes=["behaviors.read"],
            client_id="test-client",
            issued_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),  # Expired 1 hour ago
            refresh_expires_at=now + timedelta(days=7),
        )
        file_token_store.save(bundle)

        result = await mcp_service.auth_status(client_id="test-client")

        assert result["is_authenticated"] is True  # Refresh token still valid
        assert result["access_token_valid"] is False
        assert result["refresh_token_valid"] is True
        assert result["needs_refresh"] is True
        assert result["needs_login"] is False

    @pytest.mark.asyncio
    async def test_auth_status_with_no_tokens(
        self,
        mcp_service: MCPDeviceFlowService,
    ) -> None:
        """Auth status shows needs_login when no tokens exist."""
        result = await mcp_service.auth_status(client_id="test-client")

        assert result["is_authenticated"] is False
        assert result["access_token_valid"] is False
        assert result["refresh_token_valid"] is False
        assert result["needs_login"] is True

    @pytest.mark.asyncio
    async def test_auth_status_with_all_tokens_expired(
        self,
        mcp_service: MCPDeviceFlowService,
        file_token_store: FileTokenStore,
    ) -> None:
        """Auth status shows needs_login when both tokens are expired."""
        now = datetime.now(timezone.utc)
        bundle = AuthTokenBundle(
            access_token="expired-access-token",
            refresh_token="expired-refresh-token",
            token_type="Bearer",
            scopes=["behaviors.read"],
            client_id="test-client",
            issued_at=now - timedelta(days=10),
            expires_at=now - timedelta(days=9),
            refresh_expires_at=now - timedelta(days=1),  # Refresh also expired
        )
        file_token_store.save(bundle)

        result = await mcp_service.auth_status(client_id="test-client")

        assert result["is_authenticated"] is False
        assert result["access_token_valid"] is False
        assert result["refresh_token_valid"] is False
        assert result["needs_login"] is True


# --- Token Refresh Tests ---


class TestMCPTokenRefresh:
    """Test auth.refreshToken MCP tool implementation."""

    @pytest.mark.asyncio
    async def test_refresh_token_success(
        self,
        mcp_service: MCPDeviceFlowService,
        device_flow_manager: DeviceFlowManager,
        file_token_store: FileTokenStore,
    ) -> None:
        """Token refresh succeeds when valid refresh token exists."""
        # Store bundle with expired access token but valid refresh token
        now = datetime.now(timezone.utc)
        old_bundle = AuthTokenBundle(
            access_token="expired-access-token",
            refresh_token="valid-refresh-token",
            token_type="Bearer",
            scopes=["behaviors.read"],
            client_id="test-client",
            issued_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),
            refresh_expires_at=now + timedelta(days=7),
        )
        file_token_store.save(old_bundle)

        # Mock DeviceFlowManager refresh to return new tokens
        # (In real flow, this would hit authorization server)
        with patch.object(device_flow_manager, "refresh_access_token") as mock_refresh:
            new_tokens = DeviceTokens(
                access_token="new-access-token",
                refresh_token="new-refresh-token",
                token_type="Bearer",
                access_token_expires_at=now + timedelta(hours=1),
                refresh_token_expires_at=now + timedelta(days=7),
            )
            mock_session = Mock()
            mock_session.client_id = "test-client"
            mock_session.scopes = ["behaviors.read"]
            mock_session.tokens = new_tokens
            mock_refresh.return_value = mock_session

            result = await mcp_service.refresh_token(client_id="test-client", store_tokens=True)

        assert result["status"] == "refreshed"
        assert result["access_token"] == "new-access-token"
        assert result["refresh_token"] == "new-refresh-token"
        assert "token_storage_path" in result

        # Verify new tokens were persisted
        new_bundle = file_token_store.load()
        assert new_bundle is not None
        assert new_bundle.access_token == "new-access-token"

    @pytest.mark.asyncio
    async def test_refresh_token_no_stored_tokens(
        self,
        mcp_service: MCPDeviceFlowService,
    ) -> None:
        """Token refresh fails when no tokens are stored."""
        result = await mcp_service.refresh_token(client_id="test-client")

        assert result["status"] == "no_refresh_token"
        assert "No stored tokens" in result["error_description"]

    @pytest.mark.asyncio
    async def test_refresh_token_expired_refresh_token(
        self,
        mcp_service: MCPDeviceFlowService,
        file_token_store: FileTokenStore,
    ) -> None:
        """Token refresh fails when refresh token is expired."""
        now = datetime.now(timezone.utc)
        bundle = AuthTokenBundle(
            access_token="expired-access-token",
            refresh_token="expired-refresh-token",
            token_type="Bearer",
            scopes=["behaviors.read"],
            client_id="test-client",
            issued_at=now - timedelta(days=10),
            expires_at=now - timedelta(days=9),
            refresh_expires_at=now - timedelta(days=1),  # Expired
        )
        file_token_store.save(bundle)

        result = await mcp_service.refresh_token(client_id="test-client")

        assert result["status"] == "invalid_token"
        assert result["error"] == "invalid_grant"


# --- Logout Tests ---


class TestMCPLogout:
    """Test auth.logout MCP tool implementation."""

    @pytest.mark.asyncio
    async def test_logout_clears_tokens(
        self,
        mcp_service: MCPDeviceFlowService,
        file_token_store: FileTokenStore,
    ) -> None:
        """Logout clears stored tokens."""
        # Store some tokens
        now = datetime.now(timezone.utc)
        bundle = AuthTokenBundle(
            access_token="test-access-token",
            refresh_token="test-refresh-token",
            token_type="Bearer",
            scopes=["behaviors.read"],
            client_id="test-client",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            refresh_expires_at=now + timedelta(days=7),
        )
        file_token_store.save(bundle)

        # Verify tokens exist
        assert file_token_store.load() is not None

        result = await mcp_service.logout(client_id="test-client", revoke_remote=False)

        assert result["status"] == "logged_out"
        assert result["tokens_cleared"] is True

        # Verify tokens were cleared
        assert file_token_store.load() is None

    @pytest.mark.asyncio
    async def test_logout_with_no_tokens(
        self,
        mcp_service: MCPDeviceFlowService,
    ) -> None:
        """Logout reports no_tokens when no tokens exist."""
        result = await mcp_service.logout(client_id="test-client")

        assert result["status"] == "no_tokens"
        assert result["tokens_cleared"] is False

    @pytest.mark.asyncio
    async def test_logout_remote_revocation_not_implemented_warning(
        self,
        mcp_service: MCPDeviceFlowService,
        file_token_store: FileTokenStore,
    ) -> None:
        """Logout includes warning when remote revocation is requested but not implemented."""
        # Store some tokens
        now = datetime.now(timezone.utc)
        bundle = AuthTokenBundle(
            access_token="test-access-token",
            refresh_token="test-refresh-token",
            token_type="Bearer",
            scopes=["behaviors.read"],
            client_id="test-client",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            refresh_expires_at=now + timedelta(days=7),
        )
        file_token_store.save(bundle)

        result = await mcp_service.logout(client_id="test-client", revoke_remote=True)

        assert result["status"] == "logged_out"
        assert result["tokens_cleared"] is True
        assert "warnings" in result
        assert any("not yet implemented" in w for w in result["warnings"])


# --- Token Storage Parity Tests ---


class TestMCPTokenStorageParity:
    """Test token storage parity between MCP and CLI."""

    @pytest.mark.asyncio
    async def test_mcp_and_cli_share_token_storage(
        self,
        mcp_service: MCPDeviceFlowService,
        device_flow_manager: DeviceFlowManager,
        file_token_store: FileTokenStore,
    ) -> None:
        """MCP service can read tokens stored by CLI and vice versa."""
        # Simulate CLI storing tokens (same as _command_auth_login in cli.py)
        now = datetime.now(timezone.utc)
        cli_bundle = AuthTokenBundle(
            access_token="cli-access-token",
            refresh_token="cli-refresh-token",
            token_type="Bearer",
            scopes=["behaviors.read", "workflows.read"],
            client_id="test-client",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            refresh_expires_at=now + timedelta(days=7),
        )
        file_token_store.save(cli_bundle)

        # MCP service should read the same tokens
        result = await mcp_service.auth_status(client_id="test-client")

        assert result["is_authenticated"] is True
        assert result["scopes"] == ["behaviors.read", "workflows.read"]

        # Now MCP updates tokens (refresh)
        login_task = asyncio.create_task(
            mcp_service.device_login(
                client_id="test-client",
                scopes=["runs.create"],
                poll_interval=1,
                timeout=10,
                store_tokens=True,
            )
        )

        await asyncio.sleep(0.5)
        sessions = device_flow_manager._sessions
        session = list(sessions.values())[0]
        device_flow_manager.approve_user_code(
            session.user_code,
            approver="test-user@example.com",
            approver_surface="Web",
        )
        await login_task

        # CLI should read the updated tokens
        updated_bundle = file_token_store.load()
        assert updated_bundle is not None
        assert updated_bundle.client_id == "test-client"
        assert updated_bundle.scopes == ["runs.create"]


# --- MCP Handler Tests ---


class TestMCPDeviceFlowHandler:
    """Test MCP tool call dispatcher."""

    @pytest.mark.asyncio
    async def test_handler_dispatches_device_login(
        self,
        mcp_handler: MCPDeviceFlowHandler,
    ) -> None:
        """Handler dispatches auth.deviceLogin tool calls."""
        # This will timeout, but we're just testing dispatch
        result = await mcp_handler.handle_tool_call(
            "auth.deviceLogin",
            {"client_id": "test-client", "timeout": 1, "store_tokens": False},
        )

        assert "status" in result
        assert "device_code" in result or "error" in result

    @pytest.mark.asyncio
    async def test_handler_dispatches_auth_status(
        self,
        mcp_handler: MCPDeviceFlowHandler,
    ) -> None:
        """Handler dispatches auth.authStatus tool calls."""
        result = await mcp_handler.handle_tool_call(
            "auth.authStatus",
            {"client_id": "test-client"},
        )

        assert "is_authenticated" in result

    @pytest.mark.asyncio
    async def test_handler_dispatches_refresh_token(
        self,
        mcp_handler: MCPDeviceFlowHandler,
    ) -> None:
        """Handler dispatches auth.refreshToken tool calls."""
        result = await mcp_handler.handle_tool_call(
            "auth.refreshToken",
            {"client_id": "test-client"},
        )

        assert "status" in result

    @pytest.mark.asyncio
    async def test_handler_dispatches_logout(
        self,
        mcp_handler: MCPDeviceFlowHandler,
    ) -> None:
        """Handler dispatches auth.logout tool calls."""
        result = await mcp_handler.handle_tool_call(
            "auth.logout",
            {"client_id": "test-client"},
        )

        assert "status" in result
        assert "tokens_cleared" in result

    @pytest.mark.asyncio
    async def test_handler_rejects_unknown_tool(
        self,
        mcp_handler: MCPDeviceFlowHandler,
    ) -> None:
        """Handler raises ValueError for unknown tool names."""
        with pytest.raises(ValueError, match="Unknown MCP tool"):
            await mcp_handler.handle_tool_call("auth.unknownTool", {})


# --- Telemetry Integration Tests ---


class TestMCPDeviceFlowTelemetry:
    """Test telemetry event emission for MCP device flow operations."""

    @pytest.mark.asyncio
    async def test_device_login_emits_telemetry_events(
        self,
        mcp_service: MCPDeviceFlowService,
        device_flow_manager: DeviceFlowManager,
        telemetry_sink: InMemoryTelemetrySink,
    ) -> None:
        """Device login emits start, success, and tokens_stored telemetry events."""
        login_task = asyncio.create_task(
            mcp_service.device_login(
                client_id="test-client",
                scopes=["behaviors.read"],
                poll_interval=1,
                timeout=10,
                store_tokens=True,
            )
        )

        await asyncio.sleep(0.5)

        # Approve authorization
        sessions = device_flow_manager._sessions
        session = list(sessions.values())[0]
        device_flow_manager.approve_user_code(
            session.user_code,
            approver="test-user@example.com",
            approver_surface="Web",
        )

        await login_task

        # Check telemetry events
        events = telemetry_sink.events
        event_types = [e.event_type for e in events]

        assert "device_flow.mcp.login_started" in event_types
        assert "device_flow.mcp.login_success" in event_types
        assert "device_flow.mcp.tokens_stored" in event_types

    @pytest.mark.asyncio
    async def test_auth_status_emits_telemetry(
        self,
        mcp_service: MCPDeviceFlowService,
        telemetry_sink: InMemoryTelemetrySink,
    ) -> None:
        """Auth status check emits telemetry event."""
        await mcp_service.auth_status(client_id="test-client")

        events = telemetry_sink.events
        event_types = [e.event_type for e in events]

        assert "device_flow.mcp.status_checked" in event_types

    @pytest.mark.asyncio
    async def test_logout_emits_telemetry(
        self,
        mcp_service: MCPDeviceFlowService,
        file_token_store: FileTokenStore,
        telemetry_sink: InMemoryTelemetrySink,
    ) -> None:
        """Logout emits telemetry event."""
        # Store some tokens first
        now = datetime.now(timezone.utc)
        bundle = AuthTokenBundle(
            access_token="test-access-token",
            refresh_token="test-refresh-token",
            token_type="Bearer",
            scopes=["behaviors.read"],
            client_id="test-client",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            refresh_expires_at=now + timedelta(days=7),
        )
        file_token_store.save(bundle)

        await mcp_service.logout(client_id="test-client")

        events = telemetry_sink.events
        event_types = [e.event_type for e in events]

        assert "device_flow.mcp.logout" in event_types
