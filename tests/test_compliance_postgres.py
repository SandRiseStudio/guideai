"""PostgreSQL backend tests for ComplianceService.

Tests the PostgresComplianceService implementation to ensure:
- Checklist CRUD operations work correctly
- Step recording with coverage recalculation functions properly
- Validation operations return correct results
- JSONB fields are handled correctly
- Filters work as expected
"""

from __future__ import annotations

import os

try:
    import psycopg2  # type: ignore[import-not-found]
except ImportError:
    psycopg2 = None
import pytest

from guideai.action_contracts import Actor
from guideai.compliance_service_postgres import (
    ChecklistNotFoundError,
    PostgresComplianceService,
)


TEST_ACTOR = Actor(id="test-user", role="engineer", surface="cli")
NONEXISTENT_CHECKLIST_ID = "00000000-0000-0000-0000-000000000001"


def _truncate_compliance_tables(dsn: str) -> None:
    """Remove all data from compliance tables to ensure test isolation."""
    if psycopg2 is None:
        pytest.skip("psycopg2 not available")
    conn = psycopg2.connect(dsn)
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("TRUNCATE checklist_steps, checklists RESTART IDENTITY CASCADE;")
    finally:
        conn.close()


@pytest.fixture
def postgres_dsn():
    """Discover PostgreSQL DSN from environment."""
    dsn = os.environ.get("GUIDEAI_COMPLIANCE_PG_DSN")
    if not dsn:
        pytest.skip("GUIDEAI_COMPLIANCE_PG_DSN not set")
    yield dsn


@pytest.fixture
def service(postgres_dsn):
    """Create a fresh PostgresComplianceService for each test."""
    _truncate_compliance_tables(postgres_dsn)
    svc = PostgresComplianceService(dsn=postgres_dsn)
    yield svc


def test_create_checklist(service):
    """Should create a checklist with all fields."""
    checklist = service.create_checklist(
        title="PRD Compliance",
        description="Ensure PRD complete",
        template_id="template-001",
        milestone="Priority 1.2",
        compliance_category=["documentation", "requirements"],
    )

    assert checklist.title == "PRD Compliance"
    assert checklist.description == "Ensure PRD complete"
    assert checklist.template_id == "template-001"
    assert checklist.milestone == "Priority 1.2"
    assert checklist.compliance_category == ["documentation", "requirements"]
    assert checklist.coverage_score == 0.0
    assert checklist.completed_at is None
    assert len(checklist.steps) == 0


def test_get_checklist(service):
    """Should retrieve checklist with steps."""
    checklist = service.create_checklist(
        title="Test Checklist",
        description="Test",
        milestone="M1",
        compliance_category=["test"],
    )

    service.record_step(
        checklist_id=checklist.checklist_id,
        title="Step 1",
        status="COMPLETED",
        actor=TEST_ACTOR,
        evidence={"url": "https://example.com"},
        behaviors_cited=["behavior-001"],
    )

    retrieved = service.get_checklist(checklist.checklist_id)

    assert retrieved.title == "Test Checklist"
    assert len(retrieved.steps) == 1
    assert retrieved.steps[0].title == "Step 1"
    assert retrieved.steps[0].status == "COMPLETED"
    assert retrieved.steps[0].evidence == {"url": "https://example.com"}
    assert retrieved.steps[0].behaviors_cited == ["behavior-001"]


def test_get_checklist_not_found(service):
    """Should raise ChecklistNotFoundError for missing checklist."""
    with pytest.raises(ChecklistNotFoundError):
        service.get_checklist(NONEXISTENT_CHECKLIST_ID)


def test_list_checklists(service):
    """Should list all checklists."""
    service.create_checklist(title="Checklist 1", description="", milestone="M1")
    service.create_checklist(title="Checklist 2", description="", milestone="M2")
    service.create_checklist(title="Checklist 3", description="", milestone="M1")

    all_checklists = service.list_checklists()
    assert len(all_checklists) == 3


def test_list_checklists_filter_milestone(service):
    """Should filter checklists by milestone."""
    service.create_checklist(title="M1 Checklist", description="", milestone="M1")
    service.create_checklist(title="M2 Checklist", description="", milestone="M2")

    m1_checklists = service.list_checklists(milestone="M1")
    assert len(m1_checklists) == 1
    assert m1_checklists[0].milestone == "M1"


def test_list_checklists_filter_category(service):
    """Should filter checklists by compliance category."""
    service.create_checklist(
        title="Doc Checklist",
        description="",
        compliance_category=["documentation"],
    )
    service.create_checklist(
        title="Security Checklist",
        description="",
        compliance_category=["security"],
    )

    doc_checklists = service.list_checklists(compliance_category=["documentation"])
    assert len(doc_checklists) == 1
    assert "documentation" in doc_checklists[0].compliance_category


def test_list_checklists_filter_status_completed(service):
    """Should filter checklists by COMPLETED status."""
    c1 = service.create_checklist(title="Active", description="")
    c2 = service.create_checklist(title="Completed", description="")

    # Complete c2 by adding a terminal step
    service.record_step(
        checklist_id=c2.checklist_id,
        title="Final Step",
        status="COMPLETED",
        actor=TEST_ACTOR,
    )

    completed = service.list_checklists(status_filter="COMPLETED")
    assert len(completed) == 1
    assert completed[0].completed_at is not None


def test_list_checklists_filter_status_active(service):
    """Should filter checklists by ACTIVE status."""
    c1 = service.create_checklist(title="Active", description="")
    c2 = service.create_checklist(title="Completed", description="")

    service.record_step(
        checklist_id=c2.checklist_id,
        title="Step",
        status="COMPLETED",
        actor=TEST_ACTOR,
    )

    active = service.list_checklists(status_filter="ACTIVE")
    assert len(active) == 1
    assert active[0].completed_at is None


def test_record_step(service):
    """Should record a step with all fields."""
    checklist = service.create_checklist(title="Test", description="")

    step = service.record_step(
        checklist_id=checklist.checklist_id,
        title="Step 1",
        status="IN_PROGRESS",
        actor=TEST_ACTOR,
        evidence={"file": "test.py"},
        behaviors_cited=["behavior-001"],
        related_run_id="run-123",
    )

    assert step.title == "Step 1"
    assert step.status == "IN_PROGRESS"
    assert step.evidence == {"file": "test.py"}
    assert step.behaviors_cited == ["behavior-001"]
    assert step.related_run_id == "run-123"


def test_record_step_coverage_calculation(service):
    """Should calculate coverage correctly."""
    checklist = service.create_checklist(title="Test", description="")

    # 2 terminal out of 3 total = 0.666...
    service.record_step(checklist_id=checklist.checklist_id, title="Step 1", status="COMPLETED", actor=TEST_ACTOR)
    service.record_step(checklist_id=checklist.checklist_id, title="Step 2", status="FAILED", actor=TEST_ACTOR)
    service.record_step(checklist_id=checklist.checklist_id, title="Step 3", status="PENDING", actor=TEST_ACTOR)

    retrieved = service.get_checklist(checklist.checklist_id)
    assert abs(retrieved.coverage_score - 0.6666) < 0.01


def test_record_step_auto_completion(service):
    """Should auto-complete checklist when all steps terminal."""
    checklist = service.create_checklist(title="Test", description="")

    service.record_step(checklist_id=checklist.checklist_id, title="Step 1", status="COMPLETED", actor=TEST_ACTOR)
    service.record_step(checklist_id=checklist.checklist_id, title="Step 2", status="COMPLETED", actor=TEST_ACTOR)

    retrieved = service.get_checklist(checklist.checklist_id)
    assert retrieved.completed_at is not None
    assert retrieved.coverage_score == 1.0


def test_validate_checklist(service):
    """Should validate checklist and return correct results."""
    checklist = service.create_checklist(title="Test", description="")

    service.record_step(checklist_id=checklist.checklist_id, title="Completed", status="COMPLETED", actor=TEST_ACTOR)
    service.record_step(checklist_id=checklist.checklist_id, title="Failed", status="FAILED", actor=TEST_ACTOR)
    service.record_step(checklist_id=checklist.checklist_id, title="Pending", status="PENDING", actor=TEST_ACTOR)
    service.record_step(checklist_id=checklist.checklist_id, title="Skipped", status="SKIPPED", actor=TEST_ACTOR)

    result = service.validate_checklist(checklist.checklist_id)

    assert result["valid"] is False
    assert abs(result["coverage_score"] - 0.75) < 0.01  # 3 terminal / 4 total
    assert result["missing_steps"] == ["Pending"]
    assert result["failed_steps"] == ["Failed"]
    assert result["warnings"] == ["Skipped"]


def test_validate_checklist_all_completed(service):
    """Should return valid=True when all steps COMPLETED."""
    checklist = service.create_checklist(title="Test", description="")

    service.record_step(checklist_id=checklist.checklist_id, title="Step 1", status="COMPLETED", actor=TEST_ACTOR)
    service.record_step(checklist_id=checklist.checklist_id, title="Step 2", status="COMPLETED", actor=TEST_ACTOR)

    result = service.validate_checklist(checklist.checklist_id)

    assert result["valid"] is True
    assert result["coverage_score"] == 1.0
    assert result["missing_steps"] == []
    assert result["failed_steps"] == []
    assert result["warnings"] == []


def test_validate_checklist_not_found(service):
    """Should raise ChecklistNotFoundError when validating missing checklist."""
    with pytest.raises(ChecklistNotFoundError):
        service.validate_checklist(NONEXISTENT_CHECKLIST_ID)
