# GuideAI CI/CD Deployment Guide

> **Last Updated:** 2025-10-23
> **Behaviors:** `behavior_orchestrate_cicd`, `behavior_prevent_secret_leaks`, `behavior_git_governance`
> **Status:** Pipeline operational, test fixtures deferred (see [CICD_TEST_STATUS.md](CICD_TEST_STATUS.md))

## Overview

This guide documents the GuideAI CI/CD pipeline implementing automated testing, security scanning, and multi-environment deployments. The pipeline enforces quality gates across all 282 tests, secret scanning, and cross-surface parity validation before allowing deployments.

**Current Status (2025-10-23):**
- ✅ Pipeline infrastructure fully operational (6/9 jobs passing)
- ✅ Security scanning, linting, builds working
- ⏸️ Test failures deferred to telemetry infrastructure phase (need PostgreSQL/Kafka fixtures)
- 📋 See [CICD_TEST_STATUS.md](CICD_TEST_STATUS.md) for detailed analysis

## Pipeline Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     CI/CD Pipeline Flow                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Push/PR → Security Scan ──→ Pre-Commit ──→ Test Matrix    │
│                │                  │              │           │
│                ├─ Gitleaks        ├─ Lint        ├─ Py 3.10 │
│                ├─ Pre-commit      ├─ Format      ├─ Py 3.11 │
│                └─ Hooks check     └─ Types       └─ Py 3.12 │
│                                                              │
│  ──→ Service Parity ──→ MCP Server ──→ Dashboard ──→ Gate   │
│         │                   │              │           │     │
│         ├─ 162 parity       ├─ Protocol    ├─ Build    ✓    │
│         ├─ 11 consistency   └─ Validation  └─ Lint          │
│         └─ 28 device flow                                    │
│                                                              │
│  Gate Pass → Deploy (dev/staging/prod) → Smoke Tests        │
│                     │                                         │
│                     └─ Podman build/push → Registry         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Container Runtime: Podman

GuideAI uses **Podman** as the container runtime for lightweight, daemonless container management. Podman is already in use for the analytics dashboard ([`docker-compose.analytics-dashboard.yml`](../docker-compose.analytics-dashboard.yml)) and provides Docker CLI compatibility without requiring a daemon process.

## Jobs & Stages

### Stage 1: Security & Validation

#### `security-scan` Job
- **Purpose:** Detect leaked secrets and credentials
- **Tools:** Gitleaks via [`scripts/scan_secrets.sh`](../../scripts/scan_secrets.sh)
- **Scope:** Full git history scan
- **Artifacts:** Scan reports uploaded to `security/scan_reports/`
- **Behavior:** `behavior_prevent_secret_leaks`
- **Failure:** Pipeline stops if secrets detected

#### `pre-commit` Job
- **Purpose:** Enforce code quality standards
- **Tools:** Pre-commit hooks (black, isort, flake8, mypy, prettier)
- **Scope:** All files
- **Behavior:** `behavior_git_governance`
- **Failure:** Pipeline stops on format/lint violations

### Stage 2: Testing Matrix

#### `test-python` Job
- **Purpose:** Cross-version Python compatibility testing
- **Matrix:** Python 3.10, 3.11, 3.12 on Ubuntu
- **Test Count:** 282 total tests (excluding Kafka tests requiring broker)
- **Coverage:** Pytest with coverage reporting to Codecov
- **Timeout:** 30s per test
- **Artifacts:** Test results XML + coverage reports
- **Behavior:** `behavior_orchestrate_cicd`

**Test Breakdown:**
- Service parity tests: 162 (CLI/REST/MCP consistency)
- Cross-surface consistency: 11
- Device flow OAuth: 28
- MCP server protocol: 4
- Additional integration tests: ~77

#### `test-parity` Job
- **Purpose:** Validate surface parity contracts
- **Scope:** All `test_*_parity.py` files
- **Critical Tests:**
  - AgentAuthService (17 tests)
  - BehaviorService (25 tests)
  - WorkflowService (17 tests)
  - ComplianceService (17 tests)
  - RunService (22 tests)
  - MetricsService (19 tests)
  - AnalyticsService (10 tests)
- **Behavior:** `behavior_wire_cli_to_orchestrator`, `behavior_align_storage_layers`

#### `test-mcp-server` Job
- **Purpose:** Validate MCP server protocol compliance
- **Tests:**
  1. Initialize handshake (protocol 2024-11-05)
  2. tools/list (59 tools discovered)
  3. tools/call (auth.authStatus execution)
  4. ping (health check)
- **Validation:** [`examples/test_mcp_server.py`](../../examples/test_mcp_server.py)
- **Behavior:** `behavior_wire_cli_to_orchestrator`

### Stage 3: Build Validation

#### `test-dashboard` Job
- **Purpose:** Frontend build and lint validation
- **Stack:** React + Vite + TypeScript
- **Steps:**
  1. npm ci (install dependencies)
  2. npm run lint (ESLint + Prettier)
  3. npm run build (production build)
- **Artifacts:** `dashboard/dist/` uploaded for deployment

#### `test-extension` Job
- **Purpose:** VS Code extension compilation
- **Stack:** TypeScript + Webpack
- **Steps:**
  1. npm ci
  2. npm run compile (webpack build)
  3. vsce package (VSIX packaging)
- **Artifacts:** `.vsix` file for marketplace publishing

### Stage 4: Integration Gate

#### `integration-gate` Job
- **Purpose:** Ensure all quality gates passed
- **Dependencies:** All previous jobs must succeed
- **Outputs:** Summary of passed checks
- **Behavior:** `behavior_handbook_compliance_prompt`

### Stage 5: Deployment

#### `deploy` Job
- **Trigger:**
  - Manual via workflow_dispatch (any environment)
  - Automatic on push to `main` branch (dev environment)
- **Environments:**
  - **dev:** Development environment (relaxed security, debug logging)
  - **staging:** Production-like environment (test data, full security)
  - **prod:** Production environment (strict limits, audit logging)
- **Config:** Environment-specific `.env` files in [`deployment/environments/`](../environments/)
- **Behavior:** `behavior_orchestrate_cicd`, `behavior_update_docs_after_changes`

## Environment Configuration

### Development Environment
- **URL:** https://dev.guideai.com
- **Database:** PostgreSQL `guideai_dev`
- **Auth:** Plaintext tokens allowed (dev only)
- **Telemetry:** File sink (`data/telemetry_dev.jsonl`)
- **Logging:** DEBUG level
- **CORS:** All origins allowed (`*`)
- **Rate Limits:** Disabled
- **Config:** [`deployment/environments/dev.env.example`](../environments/dev.env.example)

### Staging Environment
- **URL:** https://staging.guideai.com
- **Database:** PostgreSQL `guideai_staging` (production-like)
- **Auth:** Encrypted tokens, KeychainTokenStore
- **Telemetry:** Kafka cluster (`staging-kafka.guideai.com`)
- **Logging:** INFO level, centralized aggregator
- **CORS:** Restricted to staging domains
- **Rate Limits:** Production thresholds
- **MFA:** Enabled for high-risk scopes
- **Config:** [`deployment/environments/staging.env.example`](../environments/staging.env.example)

### Production Environment
- **URL:** https://api.guideai.com
- **Database:** HA PostgreSQL cluster with connection pooling
- **Auth:** Encrypted tokens, HashiCorp Vault integration
- **Telemetry:** Production Kafka cluster (3 brokers, SASL-SSL)
- **Logging:** WARNING level, structured JSON, centralized
- **CORS:** Strict domain whitelist
- **Rate Limits:** Strict per-IP and per-user limits (Redis-backed)
- **MFA:** Enforced for `high_risk`, `actions.replay`, `agentauth.manage` scopes
- **Security:** HSTS, CSP, CSRF protection, PII encryption
- **Monitoring:** Prometheus + Grafana + Alertmanager
- **Backup:** 6h interval, 30-day retention, S3 storage
- **Compliance:** 7-year audit log retention (SOC2/GDPR)
- **Config:** [`deployment/environments/prod.env.example`](../environments/prod.env.example)

## Running the Pipeline

### Local Pre-Flight Checks

Before pushing, run local validations:

```bash
# 1. Install pre-commit hooks
./scripts/install_hooks.sh

# 2. Run secret scan
./scripts/scan_secrets.sh

# 3. Run pre-commit checks
pre-commit run --all-files

# 4. Run tests
pytest --ignore=test_kafka_consume.py -v

# 5. Run parity tests
pytest tests/test_*_parity.py -v

# 6. Validate MCP server
python examples/test_mcp_server.py
```

### Triggering CI

```bash
# Push to trigger automatic CI
git push origin main

# Create pull request (triggers full CI suite)
gh pr create --title "Feature: ..." --body "..."
```

### Manual Deployment

```bash
# Deploy to development
gh workflow run ci.yml --ref main -f environment=dev

# Deploy to staging
gh workflow run ci.yml --ref main -f environment=staging

# Deploy to production (requires approval)
gh workflow run ci.yml --ref main -f environment=prod
```

### Podman Container Deployment

GuideAI services can be containerized using Podman for deployment:

```bash
# Build API service image
podman build -t guideai-api:latest -f deployment/Dockerfile.api .

# Build dashboard image
podman build -t guideai-dashboard:latest -f deployment/Dockerfile.dashboard ./dashboard

# Push to container registry (GHCR, Quay.io, or private)
podman tag guideai-api:latest ghcr.io/nas4146/guideai-api:latest
podman push ghcr.io/nas4146/guideai-api:latest

# Run with Podman Compose (multi-service orchestration)
podman-compose -f docker-compose.analytics-dashboard.yml up -d

# Or use Kubernetes/OpenShift with Podman-generated manifests
podman generate kube guideai-api > deployment/k8s/api-deployment.yaml
```

**Why Podman?**
- ✅ **Daemonless**: No background daemon required (lighter weight)
- ✅ **Rootless**: Run containers without root privileges (better security)
- ✅ **Docker-compatible**: Drop-in replacement for Docker CLI
- ✅ **Already in use**: Analytics dashboard uses Podman Compose
- ✅ **Kubernetes-native**: Generates Kubernetes YAML directly
- ✅ **Systemd integration**: Native systemd service generation

**Podman vs Docker:**
```bash
# Commands are identical (alias docker=podman)
podman build -t myapp .     # docker build -t myapp .
podman run -p 8000:8000 ...  # docker run -p 8000:8000 ...
podman ps                    # docker ps
podman logs <container>      # docker logs <container>
```

# Deploy to staging
gh workflow run ci.yml --ref main -f environment=staging

# Deploy to production (requires approval)
gh workflow run ci.yml --ref main -f environment=prod
```

## Monitoring & Alerts

### Pipeline Failures

**Secret Scan Failure:**
```
Error: Gitleaks detected 1 secret(s)
Action: Review security/scan_reports/ci-latest.json
Remediation: Follow behavior_rotate_leaked_credentials
```

**Test Failure:**
```
Error: 5 tests failed in test-python (Python 3.11)
Action: Download test-results-py3.11.xml artifact
Remediation: Fix failing tests, update parity contracts if needed
```

**Parity Failure:**
```
Error: CLI/REST/MCP parity mismatch in BehaviorService
Action: Review parity-coverage-report.txt artifact
Remediation: Align adapter implementations per behavior_align_storage_layers
```

### Deployment Monitoring

After deployment, monitor:
- **Health Checks:** `/health`, `/ready` endpoints
- **Metrics:** Prometheus at `:9090/metrics`
- **Logs:** Centralized aggregator (Grafana Loki)
- **Alerts:** PagerDuty/Slack integration
- **Dashboards:** Grafana at https://grafana.guideai.com

## Rollback Procedures

### Automatic Rollback Triggers
- Health check failures (3 consecutive failures)
- Error rate > 5% (within 5 minutes)
- Response latency p99 > 1000ms

### Manual Rollback

```bash
# Identify last successful deployment
gh run list --workflow=ci.yml --status=success --limit=5

# Re-run previous successful workflow
gh run rerun <run-id>

# OR deploy specific git tag/commit
gh workflow run ci.yml --ref <commit-sha> -f environment=prod
```

### Rollback Validation
1. Verify health checks pass
2. Check error logs for anomalies
3. Validate PRD metrics (behavior reuse, token savings, completion rate)
4. Confirm audit logs recording properly

## Security Best Practices

### Secrets Management (`behavior_prevent_secret_leaks`)
- ✅ Never commit secrets to git
- ✅ Use GitHub Secrets for CI/CD credentials
- ✅ Rotate secrets every 30 days (production)
- ✅ Scan every commit with gitleaks
- ✅ Use environment-specific `.env` files (gitignored)
- ✅ Leverage HashiCorp Vault for production secrets

### Access Control
- **Dev:** Open access (local development)
- **Staging:** Team members only (GitHub team-based)
- **Prod:** Require approval from 2+ maintainers

### Audit Trail (`behavior_update_docs_after_changes`)
- Record all deployments via `guideai record-action`
- Link CI run URLs in BUILD_TIMELINE.md
- Update PRD_ALIGNMENT_LOG.md with deployment evidence
- Capture deployment telemetry in analytics warehouse

## Test Coverage Requirements

### Minimum Coverage Thresholds
- **Overall:** 80% line coverage
- **Service Layer:** 90% line coverage
- **Adapters:** 95% branch coverage (parity critical)
- **Auth/Security:** 100% coverage

### Parity Test Requirements
Every service operation MUST have:
1. CLI test
2. REST API test
3. MCP tool test
4. Cross-surface consistency test
5. Adapter payload validation

**Reference:** [`tests/test_all_service_parity.py`](../../tests/test_all_service_parity.py)

## Troubleshooting

### Common Issues

**Issue:** `ModuleNotFoundError: No module named 'guideai'`
```bash
# Solution: Install package in development mode
pip install -e ".[dev,semantic]"
```

**Issue:** `Kafka connection timeout in test_kafka_consume.py`
```bash
# Solution: Skip Kafka tests in CI (broker not running)
pytest --ignore=test_kafka_consume.py
```

**Issue:** `Gitleaks detected false positive`
```bash
# Solution: Add to .gitleaksignore
echo "path/to/file.txt" >> .gitleaksignore
```

**Issue:** `Pre-commit hook failing on formatting`
```bash
# Solution: Auto-fix with pre-commit
pre-commit run --all-files
git add -u
git commit --amend --no-edit
```

## Maintenance & Updates

### Weekly Tasks
- [ ] Review security scan reports
- [ ] Update dependencies (`pip list --outdated`, `npm outdated`)
- [ ] Check test flakiness (GitHub Actions insights)
- [ ] Validate deployment success rate

### Monthly Tasks
- [ ] Rotate secrets (production)
- [ ] Review and prune old artifacts
- [ ] Update environment configurations
- [ ] Performance optimization review

### Quarterly Tasks
- [ ] Dependency security audit (`pip-audit`, `npm audit`)
- [ ] Pipeline optimization review
- [ ] Disaster recovery drill
- [ ] Compliance audit (SOC2/GDPR)

## Evidence & Compliance

### Action Logging
Record CI/CD changes via ActionService:

```bash
guideai record-action \
  --artifact .github/workflows/ci.yml \
  --summary "Enhanced CI/CD pipeline with 282 test coverage" \
  --behaviors behavior_orchestrate_cicd behavior_prevent_secret_leaks behavior_git_governance
```

### Documentation Updates
Maintain alignment per `behavior_update_docs_after_changes`:
- **BUILD_TIMELINE.md:** Log pipeline enhancements
- **PRD_ALIGNMENT_LOG.md:** Link to PRD infrastructure goals
- **PROGRESS_TRACKER.md:** Update CI/CD checklist status
- **docs/capability_matrix.md:** Note deployment automation capability

## References

- **Behaviors:** `AGENTS.md` (`behavior_orchestrate_cicd`, `behavior_prevent_secret_leaks`, `behavior_git_governance`)
- **Git Strategy:** [`docs/GIT_STRATEGY.md`](../../docs/GIT_STRATEGY.md)
- **DevOps Playbook:** [`docs/AGENT_DEVOPS.md`](../../docs/AGENT_DEVOPS.md)
- **Secret Scanning:** [`SECRETS_MANAGEMENT_PLAN.md`](../../SECRETS_MANAGEMENT_PLAN.md)
- **Pre-Commit Hooks:** [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml)
- **Parity Tests:** [`tests/test_all_service_parity.py`](../../tests/test_all_service_parity.py)

_Last Updated: 2025-10-23_
