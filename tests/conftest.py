"""Pytest configuration ensuring the repository root is importable.

Provides shared fixtures with proper resource management for Podman containers.
Behaviors: behavior_align_storage_layers, behavior_unify_execution_records
"""

from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path
from typing import Generator
from unittest.mock import Mock, MagicMock

import pytest

# Load environment variables from .env file (for OPENAI_API_KEY, etc.)
try:
    from dotenv import load_dotenv
    REPO_ROOT = Path(__file__).resolve().parents[1]
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    REPO_ROOT = Path(__file__).resolve().parents[1]  # Define even if dotenv not available

from guideai.action_contracts import Actor, utc_now_iso
from guideai.behavior_service import (
    ApproveBehaviorRequest,
    BehaviorService,
    CreateBehaviorDraftRequest,
    SearchBehaviorsRequest,
)
from guideai.storage.redis_cache import get_cache

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register custom CLI flags used across the test suite."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Execute tests marked with @pytest.mark.integration that require live infrastructure.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Ensure custom markers are documented to avoid Pytest warnings."""
    config.addinivalue_line(
        "markers",
        "integration: tests that exercise live infrastructure and require --run-integration",
    )


# ============================================================================
# Heavy Dependency Mocking (Prevents Memory Exhaustion)
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def mock_sentence_transformer():
    """Mock SentenceTransformer to prevent loading heavy models in tests.

    Loading the actual model consumes ~500MB+ RAM per instance and takes
    30-60s. With 462 tests, this would exhaust system memory and cause crashes.

    This session-scoped fixture mocks the model globally for all tests.
    """
    # Mock the SentenceTransformer class before any imports
    mock_model = MagicMock()
    mock_model.encode.return_value = [[0.1] * 384]  # Fake embedding vector

    # Patch at module level
    sys.modules['sentence_transformers'] = MagicMock()
    sys.modules['sentence_transformers'].SentenceTransformer = lambda *args, **kwargs: mock_model

    yield mock_model

    # Cleanup
    if 'sentence_transformers' in sys.modules:
        del sys.modules['sentence_transformers']


@pytest.fixture(scope="session", autouse=True)
def mock_faiss():
    """Mock FAISS to prevent actual vector index operations in tests.

    FAISS operations can be memory-intensive with large indexes.
    """
    mock_faiss = MagicMock()
    mock_faiss.IndexFlatL2 = lambda dim: MagicMock()

    sys.modules['faiss'] = mock_faiss

    yield mock_faiss

    if 'faiss' in sys.modules:
        del sys.modules['faiss']


# ============================================================================
# Memory Management
# ============================================================================

@pytest.fixture(autouse=True)
def gc_collect_after_test():
    """Force garbage collection after each test to reduce memory pressure.

    On memory-constrained systems (8GB RAM), this prevents memory accumulation
    across 800+ tests that could lead to swap thrashing or OOM conditions.
    """
    import gc
    yield
    gc.collect()


# ============================================================================
# Database Connection Pool Management
# ============================================================================

# Limit concurrent connections per worker to prevent exhaustion
MAX_CONNECTIONS_PER_SERVICE = 5
CONNECTION_TIMEOUT = 5  # seconds
QUERY_TIMEOUT = 30  # seconds


def wait_for_port(host: str, port: int, timeout: float = 10.0, interval: float = 0.5) -> bool:
    """Return True when a TCP port is reachable before the timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=interval):
                return True
        except OSError:
            time.sleep(interval)
    return False


def get_postgres_dsn(service_name: str) -> str | None:
    """Build PostgreSQL DSN from environment variables.

    Supports both full DSN or individual components.
    Priority: GUIDEAI_{SERVICE}_PG_DSN > individual components

    Args:
        service_name: Service identifier (e.g., 'BEHAVIOR', 'RUN', 'WORKFLOW')

    Returns:
        Full PostgreSQL connection string or None if not configured
    """
    # Check for full DSN first
    dsn_var = f"GUIDEAI_{service_name}_PG_DSN"
    if dsn := os.environ.get(dsn_var):
        return dsn

    # Build from components
    host = os.environ.get(f"GUIDEAI_PG_HOST_{service_name}")
    port = os.environ.get(f"GUIDEAI_PG_PORT_{service_name}")
    user = os.environ.get(f"GUIDEAI_PG_USER_{service_name}")
    password = os.environ.get(f"GUIDEAI_PG_PASS_{service_name}")
    dbname = os.environ.get(f"GUIDEAI_PG_DB_{service_name}", f"guideai_{service_name.lower()}_test")

    if not all([host, port, user, password]):
        return None

    return (
        f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
        f"?connect_timeout={CONNECTION_TIMEOUT}"
        f"&options=-c%20statement_timeout={QUERY_TIMEOUT}s"
    )


def check_redis_available() -> bool:
    """Check if Redis is accessible for testing."""
    try:
        import redis
        host = os.environ.get("REDIS_HOST", "localhost")
        port = int(os.environ.get("REDIS_PORT", "6379"))
        password = os.environ.get("REDIS_PASSWORD")

        client = redis.Redis(
            host=host,
            port=port,
            password=password,
            socket_connect_timeout=CONNECTION_TIMEOUT,
            socket_timeout=CONNECTION_TIMEOUT,
            decode_responses=True,
        )
        client.ping()
        client.close()
        return True
    except Exception:
        return False


# ============================================================================
# Resource Management Fixtures
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def check_test_environment(request):
    """Validate test environment before running any tests.

    Ensures Podman containers are running and accessible.
    Fails fast if critical infrastructure is missing.

    Skips check for tests marked with 'unit' or 'load' marker, or tests in tests/load/ or tests/smoke/.
    """
    # Skip infrastructure check for unit tests, load tests, and smoke tests
    marker_expr = request.config.getoption("-m", default="")
    if marker_expr in ("unit", "load", "smoke"):
        return

    # Skip for any tests in tests/load/ or tests/smoke/ directory (they have their own infrastructure requirements)
    import pathlib
    for arg in request.config.args:
        if "tests/load/" in str(arg) or "/load/" in str(arg):
            return
        if "tests/smoke/" in str(arg) or "/smoke/" in str(arg):
            return

    mode = os.getenv("GUIDEAI_TEST_INFRA_MODE", "legacy")

    # Define expected connection details based on env vars or defaults
    # Note: These defaults match the legacy docker-compose.test.yml ports
    # In Amprealize mode, these should be set by the orchestrator
    pg_host = os.getenv("GUIDEAI_PG_HOST_BEHAVIOR", "localhost")
    pg_port = int(os.getenv("GUIDEAI_PG_PORT_BEHAVIOR", "6433"))
    redis_host = os.getenv("REDIS_HOST", "localhost")
    redis_port = int(os.getenv("REDIS_PORT", "6479"))

    if mode == "amprealize":
        print(f"\n[Fixture] Mode: amprealize. Verifying connectivity...")

        # We check one Postgres service as a proxy for all
        if not wait_for_port(pg_host, pg_port, timeout=15):
             pytest.fail(f"Infrastructure Error: Could not connect to Postgres at {pg_host}:{pg_port}. "
                         "In 'amprealize' mode, the orchestrator must provision resources before tests run.")

        if not wait_for_port(redis_host, redis_port, timeout=15):
             pytest.fail(f"Infrastructure Error: Could not connect to Redis at {redis_host}:{redis_port}.")

        print("[Fixture] Connectivity verified.")
        return

    missing_services = []

    # Check PostgreSQL services
    for service in ["BEHAVIOR", "WORKFLOW", "ACTION", "RUN", "COMPLIANCE"]:
        if not get_postgres_dsn(service):
            missing_services.append(f"PostgreSQL ({service})")

    # Check Redis
    if not check_redis_available():
        missing_services.append("Redis")

    if missing_services:
        pytest.exit(
            f"Test infrastructure not available: {', '.join(missing_services)}\n"
            f"Start containers with: podman-compose -f docker-compose.test.yml up -d",
            returncode=1
        )


@pytest.fixture(autouse=True)
def isolate_test_resources():
    """Ensure each test has isolated resources.

    Adds small delay between tests to allow connection cleanup.
    Prevents connection pool exhaustion from rapid test execution.
    """
    yield
    # Brief pause to allow connections to close properly
    time.sleep(0.05)


# ============================================================================
# PostgreSQL Service Fixtures
# ============================================================================

@pytest.fixture(scope="session")
def postgres_dsn_behavior(request) -> str:
    """PostgreSQL DSN for BehaviorService."""
    marker_expr = request.config.getoption("-m", default="")
    if marker_expr == "unit":
        return "postgresql://mock:mock@localhost:5432/mock"

    # Skip for load tests which mock services
    for arg in request.config.args:
        if "tests/load/" in str(arg) or "/load/" in str(arg):
             return "postgresql://mock:mock@localhost:5432/mock"

    dsn = get_postgres_dsn("BEHAVIOR")
    if not dsn:
        pytest.skip("BehaviorService PostgreSQL not configured")
    return dsn


@pytest.fixture(scope="session")
def postgres_dsn_workflow() -> str:
    """PostgreSQL DSN for WorkflowService."""
    dsn = get_postgres_dsn("WORKFLOW")
    if not dsn:
        pytest.skip("WorkflowService PostgreSQL not configured")
    return dsn


@pytest.fixture(scope="session")
def postgres_dsn_action() -> str:
    """PostgreSQL DSN for ActionService."""
    dsn = get_postgres_dsn("ACTION")
    if not dsn:
        pytest.skip("ActionService PostgreSQL not configured")
    return dsn


@pytest.fixture(scope="session")
def postgres_dsn_run() -> str:
    """PostgreSQL DSN for RunService."""
    dsn = get_postgres_dsn("RUN")
    if not dsn:
        pytest.skip("RunService PostgreSQL not configured")
    return dsn


@pytest.fixture(scope="session")
def postgres_dsn_compliance() -> str:
    """PostgreSQL DSN for ComplianceService."""
    dsn = get_postgres_dsn("COMPLIANCE")
    if not dsn:
        pytest.skip("ComplianceService PostgreSQL not configured")
    return dsn


@pytest.fixture(scope="session")
def postgres_dsn_auth() -> str:
    """PostgreSQL DSN for Auth."""
    dsn = get_postgres_dsn("AUTH")
    if not dsn:
        pytest.skip("Auth PostgreSQL not configured")
    return dsn


# ============================================================================
# Helper Functions
# ============================================================================

def _is_smoke_test_run(request_or_config) -> bool:
    """Detect if this test run is for smoke tests (which have their own infrastructure)."""
    # Get config from either request or config object
    config = getattr(request_or_config, 'config', request_or_config)

    # Check marker expression
    marker_expr = config.getoption("-m", default="")
    if marker_expr == "smoke":
        return True

    # Check test file paths
    for arg in config.args:
        if "tests/smoke/" in str(arg) or "/smoke/" in str(arg) or "smoke" in str(arg):
            return True

    return False


def _is_load_test_run(request_or_config) -> bool:
    """Detect if this test run is for load tests (which have minimal infrastructure)."""
    config = getattr(request_or_config, 'config', request_or_config)

    # Check marker expression
    marker_expr = config.getoption("-m", default="")
    if marker_expr == "load":
        return True

    # Check test file paths
    for arg in config.args:
        if "tests/load/" in str(arg) or "/load/" in str(arg):
            return True

    return False


def _is_minimal_infrastructure_run(request_or_config) -> bool:
    """Detect if this test run uses minimal infrastructure (skip full schema init)."""
    return _is_smoke_test_run(request_or_config) or _is_load_test_run(request_or_config)


# ============================================================================
# Database Schema Initialization
# ============================================================================

@pytest.fixture(scope="session", autouse=True)
def initialize_test_schemas(request):
    """Run migrations for all PostgreSQL databases once per test session.

    This ensures schemas exist before any tests run. Skips services
    that aren't configured (e.g., when only testing local SQLite).
    Skips entirely for smoke/load tests which have their own infrastructure.
    """
    # Skip for smoke/load tests - they have minimal infrastructure requirements
    if _is_minimal_infrastructure_run(request):
        return
    import subprocess

    migrations = [
        ("BEHAVIOR", "scripts/run_postgres_behavior_migration.py"),
        ("WORKFLOW", "scripts/run_postgres_workflow_migration.py"),
        ("ACTION", "scripts/run_postgres_action_migration.py"),
        ("RUN", "scripts/run_postgres_run_migration.py"),
        ("COMPLIANCE", "scripts/run_postgres_compliance_migration.py"),
        ("AUTH", "scripts/run_postgres_auth_migration.py"),
    ]

    for service_name, script_path in migrations:
        # Build simple DSN without query parameters for migration script
        host = os.environ.get(f"GUIDEAI_PG_HOST_{service_name}")
        port = os.environ.get(f"GUIDEAI_PG_PORT_{service_name}")
        user = os.environ.get(f"GUIDEAI_PG_USER_{service_name}")
        password = os.environ.get(f"GUIDEAI_PG_PASS_{service_name}")
        dbname = os.environ.get(f"GUIDEAI_PG_DB_{service_name}")

        if not all([host, port, user, password, dbname]):
            continue  # Service not configured, skip

        dsn = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"

        script = REPO_ROOT / script_path
        if not script.exists():
            continue  # Migration script doesn't exist yet

        try:
            # Set DSN env var for migration script to discover
            env = os.environ.copy()
            env[f"GUIDEAI_{service_name}_PG_DSN"] = dsn

            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
                env=env,
            )
        except subprocess.CalledProcessError as e:
            # Only fail if it's not an "already exists" error
            if "already exists" not in e.stderr.lower():
                pytest.exit(
                    f"Failed to initialize {service_name} schema:\n{e.stderr}",
                    returncode=1
                )


@pytest.fixture(scope="session", autouse=True)
def seed_launch_behavior(request) -> None:
    """Ensure at least one approved launch behavior exists for API parity tests."""
    marker_expr = request.config.getoption("-m", default="")
    if marker_expr == "unit":
        return

    # Skip for smoke/load tests - they have their own infrastructure
    if _is_minimal_infrastructure_run(request):
        return

    # Get DSN - skip if not configured
    postgres_dsn_behavior = get_postgres_dsn("BEHAVIOR")
    if not postgres_dsn_behavior:
        return

    if "mock" in postgres_dsn_behavior:
        return

    service = BehaviorService(dsn=postgres_dsn_behavior)
    probe = SearchBehaviorsRequest(query="launch", status="APPROVED", limit=1)
    existing = service.search_behaviors(probe)
    if existing:
        try:
            get_cache().invalidate_service("retriever")
        except Exception:
            pass
        return

    actor = Actor(id="tests", role="ENGINEER", surface="tests")
    draft = service.create_behavior_draft(
        CreateBehaviorDraftRequest(
            name="behavior_launch_plan_seed",
            description="Seed behavior that teaches GuideAI how to plan a launch.",
            instruction=(
                "Outline launch goals, dependencies, comms, and validation steps. "
                "Keep the plan concise and reference reusable playbooks."
            ),
            role_focus="STRATEGIST",
            trigger_keywords=["launch", "plan", "strategy"],
            tags=["launch", "plan", "strategy"],
            metadata={
                "citation_label": "Launch Playbook",
                "seed": "tests",
            },
        ),
        actor,
    )

    service.approve_behavior(
        ApproveBehaviorRequest(
            behavior_id=draft.behavior_id,
            version=draft.version,
            effective_from=utc_now_iso(),
        ),
        actor,
    )

    try:
        cache = get_cache()
        cache.invalidate_service("behavior")
        cache.invalidate_service("retriever")
    except Exception:
        pass


# ============================================================================
# Redis Fixtures
# ============================================================================

@pytest.fixture
def redis_client() -> Generator:
    """Provide Redis client with proper cleanup."""
    if not check_redis_available():
        pytest.skip("Redis not available")

    import redis

    host = os.environ.get("REDIS_HOST", "localhost")
    port = int(os.environ.get("REDIS_PORT", "6379"))

    client = redis.Redis(
        host=host,
        port=port,
        socket_connect_timeout=CONNECTION_TIMEOUT,
        socket_timeout=CONNECTION_TIMEOUT,
        decode_responses=True,
    )

    try:
        yield client
    finally:
        # Clean up test keys
        try:
            for key in client.scan_iter("test:*"):
                client.delete(key)
        except Exception:
            pass
        finally:
            client.close()
