"""Telemetry KPI projector - OSS Stub. Full implementation in guideai-enterprise."""

try:
    from guideai_enterprise.analytics.telemetry_kpi_projector import (
        TelemetryKPIProjector,
        TelemetryProjection,
    )
except ImportError:
    from dataclasses import dataclass, field
    from typing import Any, Dict, List

    @dataclass
    class TelemetryProjection:  # type: ignore[no-redef]
        """No-op telemetry projection for OSS."""
        summary: Dict[str, Any] = field(default_factory=dict)
        fact_behavior_usage: List[Dict[str, Any]] = field(default_factory=list)
        fact_token_savings: List[Dict[str, Any]] = field(default_factory=list)
        fact_execution_status: List[Dict[str, Any]] = field(default_factory=list)
        fact_compliance_steps: List[Dict[str, Any]] = field(default_factory=list)

    class TelemetryKPIProjector:  # type: ignore[no-redef]
        """No-op telemetry KPI projector for OSS."""
        def project(self, events: Any = None, **kwargs: Any) -> TelemetryProjection:
            return TelemetryProjection()
