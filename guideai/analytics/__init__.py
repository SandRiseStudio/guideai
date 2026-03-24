"""Analytics utilities — OSS Stub.

The KPI projector and analytics warehouse have moved to guideai-enterprise.
Install guideai-enterprise[analytics] for advanced analytics features.
"""

try:
    from guideai_enterprise.analytics.telemetry_kpi_projector import (
        TelemetryKPIProjector,
        TelemetryProjection,
    )
except ImportError:
    TelemetryKPIProjector = None  # type: ignore[assignment,misc]
    TelemetryProjection = None  # type: ignore[assignment,misc]

__all__ = ["TelemetryKPIProjector", "TelemetryProjection"]
