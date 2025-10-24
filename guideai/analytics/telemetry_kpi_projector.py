"""Project telemetry events into KPI-friendly fact tables.

This module implements a lightweight stand-in for the planned
``telemetry-kpi-projector`` streaming job described in
``docs/analytics/prd_kpi_dashboard_plan.md``.  It ingests telemetry events
emitted by guideAI runtimes and produces four fact collections aligned with the
Snowflake schema:

- ``fact_behavior_usage``
- ``fact_token_savings``
- ``fact_execution_status``
- ``fact_compliance_steps``

Each fact collection is represented as a list of dictionaries so the same code
path can be reused in unit tests, local analytics notebooks, or an eventual
streaming implementation.  The projector also computes roll-up summaries for the
four PRD success metrics (behavior reuse %, token savings %, task completion
rate, and compliance coverage %).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Union

from guideai.telemetry import TelemetryEvent

TelemetryInput = Union[TelemetryEvent, Mapping[str, object]]


@dataclass
class TelemetryProjection:
    """Container for fact collections and aggregate KPI metrics."""

    fact_behavior_usage: List[Dict[str, object]] = field(default_factory=list)
    fact_token_savings: List[Dict[str, object]] = field(default_factory=list)
    fact_execution_status: List[Dict[str, object]] = field(default_factory=list)
    fact_compliance_steps: List[Dict[str, object]] = field(default_factory=list)
    summary: Dict[str, object] = field(default_factory=dict)


@dataclass
class _RunAccumulator:
    """Transient state for a workflow run while projecting events."""

    run_id: str
    template_id: Optional[str] = None
    template_name: Optional[str] = None
    behaviors: Set[str] = field(default_factory=set)
    baseline_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    token_savings_pct: Optional[float] = None
    final_status: Optional[str] = None
    actor_surface: Optional[str] = None
    actor_role: Optional[str] = None
    first_plan_timestamp: Optional[str] = None


class TelemetryKPIProjector:
    """Compute PRD KPI facts from telemetry events."""

    def project(self, events: Iterable[TelemetryInput]) -> TelemetryProjection:
        """Project telemetry events into fact collections.

        Args:
            events: Iterable of telemetry events or raw dictionaries.

        Returns:
            ``TelemetryProjection`` with fact lists and aggregated KPI summary.
        """

        runs: Dict[str, _RunAccumulator] = {}
        compliance_facts: List[Dict[str, object]] = []
        latest_compliance_scores: MutableMapping[str, float] = {}
        terminal_status_counts: Dict[str, int] = {"COMPLETED": 0, "FAILED": 0, "CANCELLED": 0}

        for raw_event in events:
            event = self._coerce_event(raw_event)
            payload = dict(event.payload)
            event_type = event.event_type
            run_id = self._extract_run_id(event, payload)

            if event_type == "plan_created":
                if not run_id:
                    # Skip events that cannot be tied to a run; telemetry
                    # contract guarantees one for plan_created.
                    continue
                accumulator = runs.setdefault(run_id, _RunAccumulator(run_id=run_id))
                accumulator.template_id = payload.get("template_id")
                accumulator.template_name = payload.get("template_name")
                accumulator.behaviors.update(self._normalize_string_list(payload.get("behavior_ids")))
                accumulator.baseline_tokens = self._coerce_int(payload.get("baseline_tokens"))
                accumulator.first_plan_timestamp = event.timestamp
                if event.actor:
                    accumulator.actor_surface = event.actor.get("surface")
                    accumulator.actor_role = event.actor.get("role")

            elif event_type == "execution_update":
                if not run_id:
                    continue
                accumulator = runs.setdefault(run_id, _RunAccumulator(run_id=run_id))
                accumulator.template_id = accumulator.template_id or payload.get("template_id")
                accumulator.behaviors.update(self._normalize_string_list(payload.get("behaviors_cited")))
                accumulator.output_tokens = self._coerce_int(payload.get("output_tokens"))
                token_savings_pct = self._coerce_float(payload.get("token_savings_pct"))
                accumulator.token_savings_pct = token_savings_pct
                status = payload.get("status")
                if isinstance(status, str):
                    accumulator.final_status = status
                    if status in terminal_status_counts:
                        terminal_status_counts[status] += 1
                if event.actor:
                    accumulator.actor_surface = accumulator.actor_surface or event.actor.get("surface")
                    accumulator.actor_role = accumulator.actor_role or event.actor.get("role")

            elif event_type == "compliance_step_recorded":
                coverage = self._coerce_float(payload.get("coverage_score"))
                compliance_fact = {
                    "checklist_id": payload.get("checklist_id"),
                    "step_id": payload.get("step_id"),
                    "status": payload.get("status"),
                    "coverage_score": coverage,
                    "run_id": run_id,
                    "timestamp": event.timestamp,
                }
                compliance_facts.append(compliance_fact)
                checklist_id = payload.get("checklist_id")
                if coverage is not None and isinstance(checklist_id, str):
                    latest_compliance_scores[checklist_id] = coverage

            elif event_type == "behavior_retrieved":
                # Track behavior exposure even if run not yet created; this can
                # feed future attribution logic.
                session_id = event.session_id
                behaviors = self._normalize_string_list(payload.get("behavior_ids"))
                compliance_facts.append({
                    "checklist_id": None,
                    "step_id": None,
                    "status": "BEHAVIOR_RETRIEVAL",
                    "coverage_score": None,
                    "run_id": run_id,
                    "session_id": session_id,
                    "behavior_ids": behaviors,
                    "timestamp": event.timestamp,
                })

        projection = TelemetryProjection()

        for run_id, accumulator in runs.items():
            behaviors_sorted = sorted(accumulator.behaviors)
            projection.fact_behavior_usage.append(
                {
                    "run_id": run_id,
                    "template_id": accumulator.template_id,
                    "template_name": accumulator.template_name,
                    "behavior_ids": behaviors_sorted,
                    "behavior_count": len(behaviors_sorted),
                    "has_behaviors": bool(behaviors_sorted),
                    "baseline_tokens": accumulator.baseline_tokens,
                    "actor_surface": accumulator.actor_surface,
                    "actor_role": accumulator.actor_role,
                    "first_plan_timestamp": accumulator.first_plan_timestamp,
                }
            )

            projection.fact_token_savings.append(
                {
                    "run_id": run_id,
                    "template_id": accumulator.template_id,
                    "output_tokens": accumulator.output_tokens,
                    "baseline_tokens": accumulator.baseline_tokens,
                    "token_savings_pct": accumulator.token_savings_pct,
                }
            )

            projection.fact_execution_status.append(
                {
                    "run_id": run_id,
                    "template_id": accumulator.template_id,
                    "status": accumulator.final_status,
                    "actor_surface": accumulator.actor_surface,
                    "actor_role": accumulator.actor_role,
                }
            )

        projection.fact_compliance_steps = compliance_facts

        total_runs = len(runs)
        runs_with_behaviors = sum(1 for data in runs.values() if data.behaviors)
        token_savings_values: List[float] = [
            data.token_savings_pct for data in runs.values() if data.token_savings_pct is not None
        ]
        terminal_total = sum(terminal_status_counts.values())
        completed_runs = terminal_status_counts["COMPLETED"]
        avg_compliance_score = mean(latest_compliance_scores.values()) if latest_compliance_scores else None
        coverage_pct = round(avg_compliance_score * 100, 2) if avg_compliance_score is not None else None

        projection.summary = {
            "total_runs": total_runs,
            "runs_with_behaviors": runs_with_behaviors,
            "behavior_reuse_pct": self._format_percentage(runs_with_behaviors, total_runs),
            "average_token_savings_pct": self._format_percentage(token_savings_values) if token_savings_values else None,
            "completed_runs": completed_runs,
            "terminal_runs": terminal_total,
            "task_completion_rate_pct": self._format_percentage(completed_runs, terminal_total),
            "average_compliance_coverage_pct": coverage_pct,
        }

        return projection

    @staticmethod
    def _coerce_event(event: TelemetryInput) -> TelemetryEvent:
        if isinstance(event, TelemetryEvent):
            return event
        if not isinstance(event, Mapping):
            raise TypeError(f"Unsupported telemetry input type: {type(event)!r}")
        raw_payload = event.get("payload", {})
        payload: Dict[str, object] = dict(raw_payload) if isinstance(raw_payload, Mapping) else {}
        actor = event.get("actor")
        actor_dict = dict(actor) if isinstance(actor, Mapping) else {}
        run_id = event.get("run_id")
        if run_id is not None:
            run_id = str(run_id)
        action_id = event.get("action_id")
        if action_id is not None:
            action_id = str(action_id)
        session_id = event.get("session_id")
        if session_id is not None:
            session_id = str(session_id)
        return TelemetryEvent(
            event_id=str(event.get("event_id", "")),
            timestamp=str(event.get("timestamp", "")),
            event_type=str(event.get("event_type", "")),
            actor=actor_dict,
            run_id=run_id,
            action_id=action_id,
            session_id=session_id,
            payload=payload,
        )

    @staticmethod
    def _normalize_string_list(value: Optional[object]) -> Set[str]:
        result: Set[str] = set()
        if isinstance(value, str):
            result.add(value)
        elif isinstance(value, Sequence):
            for item in value:
                if isinstance(item, str):
                    result.add(item)
        return result

    @staticmethod
    def _coerce_int(value: Optional[object]) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):  # bool is subclass of int – guard specifically
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Optional[object]) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_run_id(event: TelemetryEvent, payload: Mapping[str, object]) -> Optional[str]:
        if event.run_id:
            return str(event.run_id)
        run_id = payload.get("run_id") or payload.get("related_run_id")
        return str(run_id) if isinstance(run_id, str) and run_id else None

    @staticmethod
    def _format_percentage(numerator_or_values, denominator: Optional[int] = None) -> Optional[float]:
        if isinstance(numerator_or_values, list):
            if not numerator_or_values:
                return None
            return round(mean(numerator_or_values) * 100, 2)
        if denominator is None or denominator == 0:
            return None
        if numerator_or_values is None:
            return None
        return round((numerator_or_values / denominator) * 100, 2)
