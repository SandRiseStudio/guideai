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
from uuid import uuid4

from guideai.telemetry import TelemetryEvent

TelemetryInput = Union[TelemetryEvent, Mapping[str, object]]


@dataclass
class TelemetryProjection:
    """Container for fact collections and aggregate KPI metrics."""

    fact_behavior_usage: List[Dict[str, object]] = field(default_factory=list)
    fact_token_savings: List[Dict[str, object]] = field(default_factory=list)
    fact_execution_status: List[Dict[str, object]] = field(default_factory=list)
    fact_compliance_steps: List[Dict[str, object]] = field(default_factory=list)
    fact_resource_usage: List[Dict[str, object]] = field(default_factory=list)
    fact_cost_allocation: List[Dict[str, object]] = field(default_factory=list)
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
    estimated_cost_usd: Optional[float] = None
    compliance_events: int = 0


_SERVICE_COST_MODEL: Dict[str, Dict[str, float]] = {
    "BehaviorService": {"cost_per_1k_tokens": 0.06, "cost_per_api_call": 0.0001},
    "ActionService": {"cost_per_1k_tokens": 0.06, "cost_per_api_call": 0.00015},
    "ComplianceService": {"cost_per_1k_tokens": 0.03, "cost_per_api_call": 0.00005},
    "RunService": {"cost_per_1k_tokens": 0.03, "cost_per_api_call": 0.00005},
}

_DEFAULT_TIMESTAMP = "1970-01-01T00:00:00Z"


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
                estimated_cost = self._coerce_float(payload.get("estimated_cost_usd"))
                if estimated_cost is not None:
                    accumulator.estimated_cost_usd = estimated_cost
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
                if run_id:
                    accumulator = runs.setdefault(run_id, _RunAccumulator(run_id=run_id))
                    accumulator.compliance_events += 1

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

            resource_usage_facts = self._create_resource_usage_facts(accumulator)
            projection.fact_resource_usage.extend(resource_usage_facts)
            cost_allocation = self._create_cost_allocation_fact(accumulator, resource_usage_facts)
            if cost_allocation:
                projection.fact_cost_allocation.append(cost_allocation)

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

        cost_runs = len(projection.fact_cost_allocation)
        total_cost = sum(
            self._coerce_float(fact.get("total_cost_usd")) or 0.0 for fact in projection.fact_cost_allocation
        )
        total_savings = sum(
            self._coerce_float(fact.get("savings_vs_baseline_usd")) or 0.0
            for fact in projection.fact_cost_allocation
        )
        avg_cost = (total_cost / cost_runs) if cost_runs else None
        avg_savings = (total_savings / cost_runs) if cost_runs else None
        roi_ratio = (total_savings / total_cost) if total_cost else None

        projection.summary.update(
            {
                "total_cost_usd": round(total_cost, 6) if total_cost else 0.0,
                "average_cost_per_run_usd": round(avg_cost, 6) if avg_cost is not None else None,
                "total_savings_vs_baseline_usd": round(total_savings, 6) if total_savings else 0.0,
                "average_savings_vs_baseline_usd": round(avg_savings, 6) if avg_savings is not None else None,
                "roi_ratio": round(roi_ratio, 4) if roi_ratio is not None else None,
            }
        )

        return projection

    def _create_resource_usage_facts(self, accumulator: _RunAccumulator) -> List[Dict[str, object]]:
        facts: List[Dict[str, object]] = []
        baseline_tokens = accumulator.baseline_tokens or accumulator.output_tokens or 0
        output_tokens = accumulator.output_tokens or accumulator.baseline_tokens or 0
        behavior_tokens = self._estimate_behavior_tokens(baseline_tokens, len(accumulator.behaviors))
        behavior_api_calls = max(1, len(accumulator.behaviors))

        behavior_fact = self._build_usage_record(
            run_id=accumulator.run_id,
            service_name="BehaviorService",
            operation_name="retrieve_behaviors",
            token_count=behavior_tokens,
            api_calls=behavior_api_calls,
            execution_time_ms=max(100, behavior_tokens // 2 + behavior_api_calls * 20),
            timestamp=accumulator.first_plan_timestamp or _DEFAULT_TIMESTAMP,
        )
        if behavior_fact:
            facts.append(behavior_fact)

        action_tokens = output_tokens
        action_fact = self._build_usage_record(
            run_id=accumulator.run_id,
            service_name="ActionService",
            operation_name="execute_action",
            token_count=action_tokens,
            api_calls=max(1, behavior_api_calls + 1),
            execution_time_ms=max(250, action_tokens // 2 + 100),
            timestamp=accumulator.first_plan_timestamp or _DEFAULT_TIMESTAMP,
        )
        if action_fact:
            facts.append(action_fact)

        run_overhead_tokens = self._estimate_runservice_tokens(baseline_tokens)
        run_service_fact = self._build_usage_record(
            run_id=accumulator.run_id,
            service_name="RunService",
            operation_name="orchestrate_run",
            token_count=run_overhead_tokens,
            api_calls=1,
            execution_time_ms=200,
            timestamp=accumulator.first_plan_timestamp or _DEFAULT_TIMESTAMP,
        )
        if run_service_fact:
            facts.append(run_service_fact)

        if accumulator.compliance_events:
            compliance_tokens = accumulator.compliance_events * 50
            compliance_fact = self._build_usage_record(
                run_id=accumulator.run_id,
                service_name="ComplianceService",
                operation_name="record_step",
                token_count=compliance_tokens,
                api_calls=accumulator.compliance_events,
                execution_time_ms=max(120, compliance_tokens),
                timestamp=accumulator.first_plan_timestamp or _DEFAULT_TIMESTAMP,
            )
            if compliance_fact:
                facts.append(compliance_fact)

        return facts

    def _create_cost_allocation_fact(
        self,
        accumulator: _RunAccumulator,
        resource_usage_facts: List[Dict[str, object]],
    ) -> Optional[Dict[str, object]]:
        if not resource_usage_facts:
            return None

        service_costs: Dict[str, float] = {}
        for fact in resource_usage_facts:
            service_name = fact.get("service_name")
            if not isinstance(service_name, str):
                continue
            cost_value = self._coerce_float(fact.get("estimated_cost_usd"))
            if not service_name or cost_value is None:
                continue
            service_costs[service_name] = round(service_costs.get(service_name, 0.0) + cost_value, 6)

        if not service_costs:
            return None

        total_cost = round(sum(service_costs.values()), 6)
        if accumulator.estimated_cost_usd is not None and total_cost > 0:
            scale = accumulator.estimated_cost_usd / total_cost
            service_costs = {svc: round(cost * scale, 6) for svc, cost in service_costs.items()}
            total_cost = round(accumulator.estimated_cost_usd, 6)

        savings = self._calculate_savings(accumulator.baseline_tokens, accumulator.output_tokens)

        return {
            "run_id": accumulator.run_id,
            "template_id": accumulator.template_id,
            "service_costs": service_costs,
            "total_cost_usd": total_cost,
            "savings_vs_baseline_usd": savings,
            "timestamp": accumulator.first_plan_timestamp or _DEFAULT_TIMESTAMP,
        }

    def _build_usage_record(
        self,
        *,
        run_id: str,
        service_name: str,
        operation_name: str,
        token_count: int,
        api_calls: int,
        execution_time_ms: int,
        timestamp: Optional[str],
    ) -> Optional[Dict[str, object]]:
        if token_count <= 0 and api_calls <= 0:
            return None

        cost = self._calculate_service_cost(service_name, token_count, api_calls)
        usage_id = f"{run_id}:{service_name}:{operation_name}:{uuid4().hex[:6]}"
        return {
            "usage_id": usage_id,
            "run_id": run_id,
            "service_name": service_name,
            "operation_name": operation_name,
            "token_count": token_count,
            "api_calls": api_calls,
            "execution_time_ms": execution_time_ms,
            "estimated_cost_usd": cost if cost else None,
            "timestamp": timestamp,
        }

    @staticmethod
    def _estimate_behavior_tokens(baseline_tokens: int, behavior_count: int) -> int:
        baseline = baseline_tokens if baseline_tokens > 0 else 1000
        base_tokens = max(100, min(500, int(baseline * 0.15)))
        behavior_bonus = behavior_count * 30
        return min(base_tokens + behavior_bonus, 2000)

    @staticmethod
    def _estimate_runservice_tokens(baseline_tokens: int) -> int:
        if baseline_tokens <= 0:
            baseline_tokens = 800
        return max(50, min(250, int(baseline_tokens * 0.02)))

    def _calculate_service_cost(self, service_name: str, token_count: int, api_calls: int) -> float:
        profile = _SERVICE_COST_MODEL.get(service_name, {})
        token_rate = profile.get("cost_per_1k_tokens", 0.06)
        call_rate = profile.get("cost_per_api_call", 0.0)
        token_cost = ((token_count or 0) / 1000.0) * token_rate if token_count else 0.0
        call_cost = (api_calls or 0) * call_rate
        total = token_cost + call_cost
        return round(total, 6) if total else 0.0

    def _calculate_savings(
        self, baseline_tokens: Optional[int], output_tokens: Optional[int]
    ) -> Optional[float]:
        if baseline_tokens is None or output_tokens is None:
            return None
        token_delta = baseline_tokens - output_tokens
        if token_delta <= 0:
            return 0.0
        token_rate = _SERVICE_COST_MODEL.get("ActionService", {}).get("cost_per_1k_tokens", 0.06)
        savings = (token_delta / 1000.0) * token_rate
        return round(savings, 6)

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
