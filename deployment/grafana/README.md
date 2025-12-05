# Embedding Optimization Monitoring (Phase 2)

This directory contains Grafana dashboards and Prometheus alert rules for monitoring Phase 1 embedding optimization SLO targets.

## Phase 1 SLO Targets

Per `RETRIEVAL_ENGINE_PERFORMANCE.md`:

- **P95 Retrieval Latency**: <250ms
- **Memory Footprint**: <750MB
- **Quality (nDCG@5)**: >0.85 (validated offline)
- **Disk Storage**: <100MB

## Quick Start

### 1. Install Monitoring Dependencies

```bash
# Install prometheus_client (required for metrics instrumentation)
pip install guideai[postgres]  # includes prometheus_client>=0.19
```

### 2. Start GuideAI API Server

```bash
# With embedding optimization enabled
export EMBEDDING_MODEL_NAME="sentence-transformers/all-MiniLM-L6-v2"
export EMBEDDING_MODEL_LAZY_LOAD="true"

uvicorn guideai.api:app --reload
```

### 3. Verify Metrics Endpoint

```bash
# Check metrics are exposed
curl http://localhost:8000/metrics | grep guideai_embedding

# Expected metrics:
# - guideai_embedding_model_load_count_total
# - guideai_embedding_model_load_time_seconds
# - guideai_embedding_model_memory_bytes
# - guideai_retrieval_latency_seconds
# - guideai_retrieval_cache_hits_total
# - guideai_retrieval_cache_misses_total
# - guideai_retrieval_degraded_mode_total
# - guideai_retrieval_failures_total
# - guideai_faiss_index_behaviors_total
# - guideai_faiss_index_rebuild_total
```

### 4. Configure Prometheus

Add scrape target to `prometheus.yml`:

```yaml
scrape_configs:
  - job_name: 'guideai-api'
    scrape_interval: 30s
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
```

Load alert rules:

```yaml
rule_files:
  - '/path/to/guideai/deployment/prometheus/embedding_alerts.yml'
```

### 5. Import Grafana Dashboard

1. Navigate to Grafana → Dashboards → Import
2. Upload `deployment/grafana/embedding_optimization.json`
3. Select Prometheus data source
4. Verify panels populate with data

## Available Metrics

### Model Loading Metrics

| Metric | Type | Description | SLO Target |
|--------|------|-------------|------------|
| `guideai_embedding_model_load_count_total` | Counter | Total model loads (should be 1) | =1 (lazy loading validation) |
| `guideai_embedding_model_load_time_seconds` | Histogram | Model initialization duration | <30s (first-use overhead) |
| `guideai_embedding_model_memory_bytes` | Gauge | Model memory footprint | <750MB |

### Retrieval Performance Metrics

| Metric | Type | Description | SLO Target |
|--------|------|-------------|------------|
| `guideai_retrieval_latency_seconds` | Histogram | Retrieval duration by strategy | P95 <250ms |
| `guideai_retrieval_requests_total` | Counter | Total retrieval requests | N/A |
| `guideai_retrieval_matches_total` | Counter | Total behaviors matched | N/A |

### Cache Efficiency Metrics

| Metric | Type | Description | SLO Target |
|--------|------|-------------|------------|
| `guideai_retrieval_cache_hits_total` | Counter | Cache hit count (token savings) | Hit rate >30% |
| `guideai_retrieval_cache_misses_total` | Counter | Cache miss count (inference needed) | N/A |

### Quality Proxy Metrics

| Metric | Type | Description | SLO Target |
|--------|------|-------------|------------|
| `guideai_retrieval_degraded_mode_total` | Counter | Degraded mode (semantic unavailable) | <10% requests |
| `guideai_retrieval_failures_total` | Counter | Retrieval failures by error type | <5% error rate |

### FAISS Index Metrics

| Metric | Type | Description | SLO Target |
|--------|------|-------------|------------|
| `guideai_faiss_index_behaviors_total` | Gauge | Behaviors in FAISS index | N/A |
| `guideai_faiss_index_rebuild_total` | Counter | Index rebuild count | <2/hour |
| `guideai_faiss_index_rebuild_duration_seconds` | Histogram | Index rebuild duration | <60s |

## Alert Rules

All alerts defined in `deployment/prometheus/embedding_alerts.yml`:

### Critical Alerts (Severity: page)

- **EmbeddingRetrievalLatencyHigh**: P95 latency >250ms for 5 minutes
- **EmbeddingModelMemoryHigh**: Memory usage >750MB for 2 minutes
- **EmbeddingRetrievalFailureRateHigh**: Error rate >5% for 5 minutes

### Warning Alerts (Severity: warning)

- **EmbeddingCacheHitRateLow**: Cache hit rate <30% for 10 minutes
- **EmbeddingDegradedModeHigh**: Degraded mode >10% of requests for 10 minutes
- **EmbeddingModelNotLazyLoaded**: Model loaded >1 times (singleton failure)
- **EmbeddingIndexRebuildStorm**: Rebuild rate >2/hour for 10 minutes

## Dashboard Panels

The Grafana dashboard (`embedding_optimization.json`) includes 11 panels:

1. **P95 Retrieval Latency vs 250ms SLO** - Time series with SLO line
2. **Model Memory Footprint vs 750MB SLO** - Gauge with threshold coloring
3. **Model Load Count** - Stat (should be 1 for lazy loading)
4. **Model Load Time** - Stat (lazy loading overhead)
5. **Cache Hit Ratio** - Time series (token savings metric)
6. **Retrieval Requests by Strategy** - Time series (traffic breakdown)
7. **Degraded Mode Rate** - Time series (quality proxy)
8. **FAISS Index Size** - Stat (behavior count)
9. **FAISS Index Rebuild Rate** - Stat (rebuilds/day)
10. **Retrieval Failure Rate** - Time series (error monitoring)
11. **P50/P95/P99 Latency Percentiles** - Time series (detailed latency view)

## Troubleshooting

### Metrics Not Appearing

```bash
# Check prometheus_client installed
python -c "from guideai.storage.embedding_metrics import PROMETHEUS_AVAILABLE; print(PROMETHEUS_AVAILABLE)"

# Should print: True
# If False, install postgres extras:
pip install guideai[postgres]
```

### Memory Metric Always Zero

The `guideai_embedding_model_memory_bytes` metric requires process-level memory tracking (not yet implemented). For Phase 2, manually verify memory via:

```bash
# Check process RSS
ps aux | grep uvicorn | awk '{print $6/1024 " MB"}'

# Or use prometheus node_exporter for process metrics
```

### Lazy Loading Not Working (Load Count >1)

```bash
# Verify environment configuration
echo $EMBEDDING_MODEL_LAZY_LOAD  # should be "true" or empty (default)

# Check uvicorn workers
# Single worker: OK (singleton shared within process)
# Multi-worker without --preload: Each worker loads own model instance

# Recommended for production:
uvicorn guideai.api:app --workers 4 --preload
```

### Cache Hit Rate Low (<30%)

```bash
# Check Redis availability
redis-cli ping  # should return PONG

# Review query diversity (high cardinality reduces hits)
curl http://localhost:8000/metrics | grep guideai_retrieval_cache

# Consider increasing cache TTL
# Edit guideai/behavior_retriever.py:
# BehaviorRetriever(cache_ttl=1200)  # 20 minutes instead of 10
```

## Phase 2 Deployment Checklist

- [x] Prometheus metrics instrumentation (`guideai/storage/embedding_metrics.py`)
- [x] BehaviorRetriever instrumented with metrics tracking
- [x] Grafana dashboard created (`embedding_optimization.json`)
- [x] Prometheus alert rules defined (`embedding_alerts.yml`)
- [ ] Gradual rollout mechanism (EMBEDDING_ROLLOUT_PERCENTAGE)
- [ ] Production deployment with 10% traffic
- [ ] 24-48 hour validation window
- [ ] Documentation updates (BUILD_TIMELINE #130, WORK_STRUCTURE, RETRIEVAL_ENGINE_PERFORMANCE)

## Related Documentation

- `RETRIEVAL_ENGINE_PERFORMANCE.md` - Phase 1 SLO targets and optimization strategy
- `docs/MONITORING_GUIDE.md` - General PostgreSQL metrics monitoring guide
- `BUILD_TIMELINE.md` Entry #129 - Phase 1 completion summary
- `PRD_ALIGNMENT_LOG.md` - Quality trade-off justification

## Next Steps (Phase 3 & 4)

- **Phase 3 (Quantization)**: If memory pressure detected, evaluate model.quantize() to reduce footprint
- **Phase 4 (Distillation)**: If latency bottleneck, evaluate knowledge distillation to faster models

_Last updated: 2025-12-20 (Phase 2 monitoring infrastructure)_
