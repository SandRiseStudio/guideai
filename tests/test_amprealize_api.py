import os
import sys
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient
from datetime import datetime

# Mark entire module as unit tests (no infrastructure required)
pytestmark = pytest.mark.unit

# Dummy DSNs used only for tests in this module - applied via fixture
_DUMMY_DSNS = {
    "GUIDEAI_COMPLIANCE_PG_DSN": "postgresql://test:test@localhost:5432/test",
    "GUIDEAI_ACTION_PG_DSN": "postgresql://test:test@localhost:5432/test",
    "GUIDEAI_BEHAVIOR_PG_DSN": "postgresql://test:test@localhost:5432/test",
    "GUIDEAI_WORKFLOW_PG_DSN": "postgresql://test:test@localhost:5432/test",
    "GUIDEAI_RUN_PG_DSN": "postgresql://test:test@localhost:5432/test",
}


@pytest.fixture(autouse=True)
def isolate_env_and_mocks():
    """Isolate environment and module mocks to this test file only.

    This prevents polluting the global environment for other tests.
    """
    # Mock PostgresPool to avoid connection attempts
    mock_pool_module = MagicMock()
    mock_pool_module.PostgresPool = MagicMock()

    with patch.dict(sys.modules, {"guideai.storage.postgres_pool": mock_pool_module}):
        with patch.dict(os.environ, _DUMMY_DSNS):
            yield


# Import create_app inside a function to avoid module-level side effects
def _get_create_app():
    from guideai.api import create_app
    return create_app


# These types are safe to import at module level (no side effects)
from guideai.amprealize import (
    PlanResponse, ApplyResponse, StatusResponse, DestroyResponse,
    EnvironmentEstimates, HealthCheck, TelemetryData
)

@pytest.fixture
def mock_container():
    with patch("guideai.api._ServiceContainer") as MockContainer:
        container_instance = MockContainer.return_value
        # Setup default mocks for all services to avoid attribute errors
        container_instance.action_service = MagicMock()
        container_instance.behavior_service = MagicMock()
        container_instance.compliance_service = MagicMock()
        container_instance.workflow_service = MagicMock()
        container_instance.run_service = MagicMock()
        container_instance.metrics_service = MagicMock()
        container_instance.bci_service = MagicMock()
        container_instance.reflection_service = MagicMock()
        container_instance.task_assignment_service = MagicMock()
        container_instance.agent_auth_service = MagicMock()
        container_instance.amprealize_adapter = MagicMock()
        yield container_instance

@pytest.fixture
def client(mock_container):
    # Create a new app instance which will use the mocked _ServiceContainer
    # Import inside fixture to ensure env vars are already mocked
    create_app = _get_create_app()
    app = create_app()
    return TestClient(app)


def test_plan_endpoint(client, mock_container):
    # Setup mock response
    mock_container.amprealize_adapter.plan.return_value = PlanResponse(
        plan_id="plan-123",
        amp_run_id="run-123",
        signed_manifest={"kind": "Deployment"},
        environment_estimates=EnvironmentEstimates(
            cost_estimate=1.5,
            memory_footprint_mb=512,
            region="us-east-1",
            expected_boot_duration_s=10
        )
    )

    # API requires actor_id and actor_role query params
    response = client.post(
        "/v1/amprealize/plan?actor_id=test-user&actor_role=engineer",
        json={
            "blueprint_id": "bp-123",
            "environment": "development",
            "compliance_tier": "high"
        }
    )

    assert response.status_code == 202
    data = response.json()
    assert data["plan_id"] == "plan-123"
    assert data["amp_run_id"] == "run-123"
    mock_container.amprealize_adapter.plan.assert_called_once()


def test_apply_endpoint(client, mock_container):
    mock_container.amprealize_adapter.apply.return_value = ApplyResponse(
        amp_run_id="run-123",  # Required field
        environment_outputs={"url": "https://api.example.com"},
        action_id="action-123"
    )

    # API requires actor_id and actor_role query params
    response = client.post(
        "/v1/amprealize/apply?actor_id=test-user&actor_role=engineer",
        json={
            "plan_id": "plan-123",
            "watch": False
        }
    )

    assert response.status_code == 202
    data = response.json()
    assert data["action_id"] == "action-123"
    mock_container.amprealize_adapter.apply.assert_called_once()


def test_status_endpoint(client, mock_container):
    mock_container.amprealize_adapter.status.return_value = StatusResponse(
        amp_run_id="run-123",
        phase="running",
        progress_pct=100,
        checks=[
            HealthCheck(name="api", status="healthy", last_probe=datetime.now())
        ],
        telemetry=TelemetryData(token_savings_pct=0.3, behavior_reuse_pct=0.7)
    )

    response = client.get("/v1/amprealize/status/run-123")

    assert response.status_code == 200
    data = response.json()
    assert data["phase"] == "running"
    assert data["amp_run_id"] == "run-123"
    mock_container.amprealize_adapter.status.assert_called_once_with("run-123")


def test_destroy_endpoint(client, mock_container):
    mock_container.amprealize_adapter.destroy.return_value = DestroyResponse(
        teardown_report=["Stopped container", "Removed volume"],
        action_id="action-456"
    )

    # API requires actor_id and actor_role query params
    response = client.post(
        "/v1/amprealize/destroy?actor_id=test-user&actor_role=engineer",
        json={
            "amp_run_id": "run-123",
            "reason": "Test complete"
        }
    )

    assert response.status_code == 202
    data = response.json()
    assert len(data["teardown_report"]) == 2
    assert data["action_id"] == "action-456"
    mock_container.amprealize_adapter.destroy.assert_called_once()
