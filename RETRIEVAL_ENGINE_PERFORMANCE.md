# Retrieval Engine Performance & Scaling Plan

## Summary
The behavior retriever powers Strategist/Teacher/Student workflows across the platform UI, CLI, API, and MCP tools. This plan defines the initial performance envelope, capacity assumptions, and scaling controls needed to meet the PRD targets (fast behavior reuse with predictable latency) while remaining reproducible for future deployments.

## Load Assumptions (Milestone 0 – Internal Teams)
| Dimension | Target | Notes |
| --- | --- | --- |
| Concurrent interactive sessions | 20 Strategist/Student sessions | Mix of UI + IDE clients during working hours |
| CLI/MCP automation jobs | 10 concurrent background jobs | Includes replay + reflection pipelines |
| Behavior corpus size | 15k approved behaviors | Includes historical behaviors and drafts |
| Average retrieval per session | 6 queries | Plan/execute/reflect loops |
| Peak QPS | 40 queries/second | Includes bursts from batch reflections |

## Latency & Quality Targets
- **P50 latency:** ≤ 75 ms end-to-end (retrieval + ranking) for top-10 behaviors.
- **P95 latency:** ≤ 200 ms for interactive use; ≤ 350 ms for batch reflections.
- **Recall expectation:** ≥ 90% of ground-truth behaviors within top-10 for regression set (curated weekly).
- **Availability:** 99.5% uptime, measured per week.

## Capacity Plan
1. **Index Selection:**
   - Vector store: FAISS IVF-PQ backed by managed service (Qdrant/Weaviate) with replication factor 3.
   - Keyword fallback: Postgres full-text search for trigger keywords.
2. **Shards & Replicas:**
   - Start with 2 shards × 3 replicas (active-active) to support 15k vectors with room for 5× growth.
   - Autoscale policy when CPU > 70% or latency SLO violated for three consecutive 5-minute windows.
3. **Caching:**
   - LRU cache (Redis) for top queries (TTL 10 minutes) to reduce hot-path latency.
4. **Batch Windows:**
   - Schedule reflection-driven bulk retrievals during off-peak windows (nightly UTC 03:00–05:00) with rate limiting (10 QPS).

## Scaling Strategy
- **Growth Triggers:** Revisit shard count when corpus exceeds 60k behaviors or peak QPS exceeds 150.
- **Horizontal Scale:** Add shards, re-run k-means centroid training offline, and rebalance vectors via background jobs.
- **Vertical Scale:** Increase RAM/CPU on vector nodes only after horizontal options exhausted; record changes via `guideai record-action`.
- **Disaster Recovery:** Daily snapshot of vector index and keyword DB; RPO 1 hour, RTO 30 minutes.

## Instrumentation & Alerts
- Emit metrics: `retriever_request_count`, `retriever_latency_ms` (p50/p95), `retriever_recall_score`, `retriever_cache_hit_ratio`.
- Alerting thresholds:
  - P95 latency > 250 ms for 5 min (page engineering on-call).
  - Recall < 85% on regression suite (trigger reindex workflow).
  - Cache hit ratio < 30% (investigate workload shift).
- Logs include `run_id`, `behavior_ids`, latency breakdown; stored in observability pipeline defined in telemetry plan.

## Validation & Benchmarking
- Maintain nightly load test (`tests/perf/retriever_benchmark.py`) simulating 50 QPS for 10 minutes; fail build if P95 > target.
- Regression dataset curated in `data/retriever_eval/` with golden behavior selections (update via `guideai record-action`).
- Document benchmarking results in `docs/perf/retriever/` after each release cycle.

## Dependencies & Owners
- **Owners:** Engineering (retriever squad) with support from Platform for infra changes.
- **Dependencies:** Vector DB provider SLAs, Redis cache cluster, telemetry pipeline, behavior ingestion tooling.

## Open Questions
- How soon do we need multi-tenant isolation per customer? (Impacts shard sizing.)
- Should we support on-device embeddings for air-gapped deployments? (Affects resource footprint.)
- Can we share cache between Strategist and Student personas without leaking restricted behaviors?
