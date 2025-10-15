# Telemetry Schema & Retention Policy

## Goals
- Provide consistent observability across Web, CLI, API, and MCP surfaces.
- Supply evidence for PRD metrics (behavior reuse %, token savings, task completion rate, compliance coverage).
- Meet compliance requirements for auditability (immutable logs, defined retention windows).

## Event Model
All telemetry events share a common envelope:
```json
{
  "event_id": "uuid",
  "timestamp": "RFC3339",
  "actor": {
    "id": "uuid",
    "role": "Strategist|Student|Teacher|Admin",
    "surface": "web|cli|vscode|api|mcp"
  },
  "run_id": "uuid",
  "action_id": "uuid|null",
  "session_id": "uuid",
  "payload": { "...domain-specific fields..." }
}
```

### Domain Events
| Event Type | Required Fields | Purpose |
| --- | --- | --- |
| `behavior_retrieved` | `payload.behavior_ids[]`, `payload.latency_ms`, `payload.relevance_scores[]`, `payload.query_vector_version` | Measure reuse rate, latency, and retriever quality. |
| `plan_created` | `payload.behavior_ids[]`, `payload.steps[]`, `payload.checklist_status` | Track behavior citation and checklist coverage at plan time. |
| `execution_update` | `payload.step`, `payload.status`, `payload.commands[]`, `payload.validation_results[]` | Monitor task completion and validation evidence. |
| `reflection_submitted` | `payload.trace_id`, `payload.behavior_candidates[]`, `payload.retrieval_latency_ms` | Evaluate self-improvement loops. |
| `action_recorded` | `payload.artifact_path`, `payload.summary`, `payload.behaviors_cited[]` | Ensure reproducibility logs are complete. |
| `compliance_step_recorded` | `payload.checklist_step`, `payload.status`, `payload.evidence_uri` | Demonstrate 95% compliance coverage. |

## Storage & Pipeline
1. **Ingestion:**
   - Clients emit events via gRPC/HTTP to `TelemetryService`.
   - Events validated against JSON Schema (versioned under `schema/telemetry/`).
2. **Processing:**
   - Write-once append to Kafka topic `telemetry.events` with schema registry.
   - Stream processors project into OLAP warehouse (Snowflake) tables `fact_events`, `fact_behaviors`, `fact_compliance`.
3. **Cold Storage:**
   - Daily roll-up archived to S3-compatible bucket with WORM policy.
4. **Access Control:**
   - Role-based views: Compliance (full), Product (aggregates), Engineering (operational metrics).

## Retention Policy
| Data Tier | Retention | Notes |
| --- | --- | --- |
| Hot (Kafka) | 7 days | Supports replay for incident response. |
| Warm (Warehouse) | 3 years | Required for PRD metrics trending and audits. |
| Cold (WORM object store) | 7 years | Meets SOC2/GDPR evidence requirements; immutable storage. |

Deletion requests (GDPR) executed via anonymization job that strips actor PII while retaining aggregate metrics; log via `guideai record-action`.

## Monitoring & Quality
- Metrics: `telemetry_ingest_qps`, `telemetry_validation_errors_total`, `telemetry_pipeline_lag_seconds`.
- Alerts: validation error rate > 0.5% (warn), pipeline lag > 120s (page), warehouse load failures.
- Weekly schema drift report compares live payloads against stored schema; deviations trigger update workflow in `AGENT_ENGINEERING.md`.

## Implementation Tasks
- Generate schemas in `schema/telemetry/v1/*.json`.
- Implement TelemetryService ingestion endpoint (part of MCP server) with request signing.
- Configure Kafka topic and connector to warehouse with encryption at rest.
- Document querying patterns in developer guide (`docs/analytics/telemetry_queries.md`).

## Owners & Dependencies
- **Owners:** Engineering (Telemetry), Compliance (retention policy review), Product Analytics (reporting dashboards).
- **Dependencies:** MCP server ActionService linkage, warehouse infrastructure, IAM policies for least privilege.
