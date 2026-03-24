"""Telemetry KPI projector - OSS Stub. Full implementation in guideai-enterprise."""

try:
    from guideai_enterprise.analytics.telemetry_kpi_projector import (
        TelemetryKPIProjector,
        TelemetryProjection,
    )
except ImportError:
    TelemetryKPIProjector = None  # type: ignore[assignment,misc]
    TelemetryProjection = None  # type: ignore[assignment,misc]
