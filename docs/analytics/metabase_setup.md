# Metabase Analytics Dashboard Setup

> **Purpose:** Deploy and configure Metabase for GuideAI PRD metrics visualization
> **Owner:** Product Analytics + Engineering
> **Last Updated:** 2025-10-20

## Overview

Metabase is the visualization layer for GuideAI's analytics infrastructure, connecting to the DuckDB warehouse (`data/telemetry.duckdb`) to provide interactive dashboards tracking the four PRD success metrics:

1. **Behavior Reuse Rate** (target: ≥70%)
2. **Token Savings Rate** (target: ≥30%)
3. **Task Completion Rate** (target: ≥80%)
4. **Compliance Coverage Rate** (target: ≥95%)

## Architecture

```
┌─────────────┐      ┌──────────────┐      ┌────────────────┐
│ Telemetry   │─────▶│ DuckDB       │◀────▶│ Metabase       │
│ Events      │      │ Warehouse    │      │ (Port 3000)    │
│ (Kafka/File)│      │ (Read-Only)  │      │                │
└─────────────┘      └──────────────┘      └────────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │ 4 KPI Views  │
                     │ + 4 Fact     │
                     │ Tables       │
                     └──────────────┘
```

## Quick Start (Local Development)

### 1. Start Metabase

```bash
# Ensure Podman machine is running
podman machine start

# From repository root
podman-compose -f docker-compose.analytics-dashboard.yml up -d

# Check logs
podman-compose -f docker-compose.analytics-dashboard.yml logs -f metabase

# Wait for "Metabase Initialization COMPLETE" (30-60 seconds)
```

**Note:** GuideAI uses Podman instead of Docker for lighter resource usage and better security. If you have `docker-compose` aliased to `podman-compose`, the standard commands will work. See `deployment/PODMAN.md` for setup instructions.

### 2. Access Web Interface

Open browser: **http://localhost:3000**

**Default Credentials:**
- Email: `admin@guideai.local`
- Password: `changeme123`

⚠️ **Change password immediately after first login!**

### 3. Connect to DuckDB Warehouse

**Important:** DuckDB files use a proprietary format that isn't directly readable by SQLite drivers. We export the DuckDB data to SQLite format for Metabase compatibility.

#### Step 1: Export DuckDB to SQLite

```bash
# Export analytics data to SQLite format
python scripts/export_duckdb_to_sqlite.py

# Output: data/telemetry_sqlite.db (SQLite format, Metabase-compatible)
```

**Run this export:**
- After DuckDB schema changes
- When new telemetry data is added
- Before creating/updating Metabase dashboards
- Recommended: Daily cron job for production

#### Step 2: Connect Metabase to SQLite Export

1. Go to **Settings** (gear icon) → **Admin Settings** → **Databases** → **Add Database**
2. Configure:
   - **Database type:** SQLite
   - **Display name:** GuideAI Analytics Warehouse
   - **Filename:** `/duckdb/telemetry_sqlite.db`
   - **Advanced options:**
     - Read-only: ✅ (recommended)
     - Sync schema: ✅
3. Click **Save**
4. Wait for schema sync (should detect 8 tables/views)

**Available Tables:**
- `fact_behavior_usage` - Behavior citations per run
- `fact_token_savings` - Token efficiency metrics
- `fact_execution_status` - Run completion status
- `fact_compliance_steps` - Checklist execution records
- `view_behavior_reuse_rate` - Aggregated behavior reuse %
- `view_token_savings_rate` - Aggregated token savings %
- `view_completion_rate` - Aggregated task completion %
- `view_compliance_coverage_rate` - Aggregated compliance coverage %

#### Alternative: Direct DuckDB Access (Future)

When Metabase adds native DuckDB support, you can connect directly:

1. Download DuckDB JDBC driver: https://github.com/duckdb/duckdb/releases
2. Place in Metabase plugins directory: `/metabase-data/plugins/`
3. Configure:
   - **Database type:** Other (Custom JDBC)
   - **JDBC connection string:** `jdbc:duckdb:/duckdb/telemetry.duckdb`
   - **Driver class:** `org.duckdb.DuckDBDriver`

**Note:** This requires Metabase restart and manual JDBC driver installation.

### 4. Import Dashboard Definitions

1. Go to **Collections** → **New Collection** → Name: "PRD Metrics"
2. For each JSON file in `docs/analytics/dashboard-exports/`:
   - Click **+** → **Dashboard** → **Import**
   - Upload JSON file
   - Verify queries execute successfully
3. Pin primary dashboard to homepage

**Available Dashboards:**
- `prd_kpi_summary.json` – Executive overview (all 4 metrics)
- `behavior_usage_trends.json` – Time series of behavior citations
- `token_savings_analysis.json` – Efficiency tracking over time
- `compliance_coverage_breakdown.json` – Checklist completion heatmap

### 5. Verify Data

Navigate to each dashboard and confirm:
- ✅ Queries return data (not empty state)
- ✅ Metrics match REST API values (`curl http://localhost:8000/v1/analytics/kpi-summary`)
- ✅ Date filters work correctly
- ✅ Drill-down links navigate properly

## Configuration Reference

### Environment Variables

Customize via `.env` file or export before `docker-compose up`:

```bash
# Admin account (first-time setup only)
export MB_ADMIN_EMAIL="your-email@company.com"
export MB_ADMIN_PASSWORD="SecurePassword123!"
export MB_ADMIN_FIRST_NAME="Your"
export MB_ADMIN_LAST_NAME="Name"

# Site configuration
export MB_SITE_NAME="GuideAI Analytics"
export MB_SITE_URL="https://analytics.guideai.company.com"
export MB_TIMEZONE="America/New_York"

# Application database (production: use Postgres)
export MB_DB_TYPE="postgres"
export MB_DB_HOST="postgres.internal"
export MB_DB_PORT="5432"
export MB_DB_NAME="metabase"
export MB_DB_USER="metabase"
export MB_DB_PASS="SecureDBPassword!"

# Email (for alerts and subscriptions)
export MB_EMAIL_SMTP_HOST="smtp.sendgrid.net"
export MB_EMAIL_SMTP_PORT="587"
export MB_EMAIL_SMTP_USERNAME="apikey"
export MB_EMAIL_SMTP_PASSWORD="SG.xxxxx"
export MB_EMAIL_FROM_ADDRESS="noreply@guideai.company.com"
```

### Volume Mounts

```yaml
volumes:
  # Metabase app database (H2/Postgres metadata)
  - metabase-data:/metabase-data

  # DuckDB warehouse (READ-ONLY to prevent corruption)
  - ./data/telemetry.duckdb:/duckdb/telemetry.duckdb:ro

  # Dashboard exports (backup/restore)
  - ./docs/analytics/dashboard-exports:/dashboard-exports:ro
```

## Dashboard Queries

Each dashboard executes SQL against the DuckDB warehouse. Example queries:

### KPI Summary (Last 30 Days)

```sql
SELECT
  snapshot_time,
  behavior_reuse_pct,
  average_token_savings_pct,
  task_completion_rate_pct,
  average_compliance_coverage_pct,
  total_runs,
  completed_runs,
  failed_runs
FROM main.view_kpi_summary
WHERE snapshot_time >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY snapshot_time DESC
LIMIT 1;
```

### Behavior Usage Trends (Time Series)

```sql
SELECT
  DATE_TRUNC('day', execution_timestamp) AS date,
  COUNT(DISTINCT run_id) AS total_runs,
  SUM(behavior_count) AS total_behaviors_cited,
  AVG(behavior_count) AS avg_behaviors_per_run,
  COUNT(DISTINCT UNNEST(behavior_ids)) AS unique_behaviors
FROM main.fact_behavior_usage
WHERE execution_timestamp >= {{start_date}}
  AND execution_timestamp < {{end_date}}
GROUP BY date
ORDER BY date;
```

### Token Savings Distribution

```sql
SELECT
  CASE
    WHEN token_savings_pct >= 0.5 THEN '50%+'
    WHEN token_savings_pct >= 0.3 THEN '30-50%'
    WHEN token_savings_pct >= 0.1 THEN '10-30%'
    ELSE '<10%'
  END AS savings_bucket,
  COUNT(*) AS run_count,
  AVG(token_savings_pct) * 100 AS avg_savings_pct
FROM main.fact_token_savings
WHERE execution_timestamp >= {{start_date}}
GROUP BY savings_bucket
ORDER BY savings_bucket DESC;
```

### Compliance Coverage by Checklist

```sql
SELECT
  checklist_id,
  template_id,
  AVG(coverage_score) AS avg_coverage,
  COUNT(*) AS execution_count,
  SUM(CASE WHEN all_steps_complete THEN 1 ELSE 0 END) AS fully_complete_count
FROM main.fact_compliance_steps
WHERE execution_timestamp >= {{start_date}}
GROUP BY checklist_id, template_id
ORDER BY avg_coverage DESC;
```

## Production Deployment

### Prerequisites

- [ ] Provision Postgres database for Metabase application metadata
- [ ] Configure TLS certificates for HTTPS
- [ ] Set up reverse proxy (nginx/Traefik) with rate limiting
- [ ] Provision persistent volume for DuckDB warehouse (if using network storage)
- [ ] Configure SSO/SAML authentication (Metabase Enterprise)
- [ ] Set up backup strategy for Metabase metadata

### Deployment Steps

1. **Update `docker-compose.analytics-dashboard.yml` for production:**

```yaml
services:
  metabase:
    environment:
      # Use Postgres for app DB
      MB_DB_TYPE: postgres
      MB_DB_HOST: ${POSTGRES_HOST}
      MB_DB_PORT: ${POSTGRES_PORT}
      MB_DB_NAME: ${POSTGRES_DB}
      MB_DB_USER: ${POSTGRES_USER}
      MB_DB_PASS: ${POSTGRES_PASSWORD}

      # Production site URL
      MB_SITE_URL: https://analytics.guideai.company.com

      # Email configuration
      MB_EMAIL_SMTP_HOST: ${SMTP_HOST}
      MB_EMAIL_SMTP_PORT: ${SMTP_PORT}
      MB_EMAIL_SMTP_USERNAME: ${SMTP_USER}
      MB_EMAIL_SMTP_PASSWORD: ${SMTP_PASS}

      # SAML SSO (Enterprise)
      MB_SAML_ENABLED: true
      MB_SAML_IDP_URI: ${SAML_IDP_URI}
      MB_SAML_IDP_CERT: ${SAML_IDP_CERT}
```

2. **Set up nginx reverse proxy:**

```nginx
server {
    listen 443 ssl http2;
    server_name analytics.guideai.company.com;

    ssl_certificate /etc/ssl/certs/analytics.crt;
    ssl_certificate_key /etc/ssl/private/analytics.key;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

3. **Deploy and validate:**

```bash
# Load secrets from vault
export $(cat .env.production | xargs)

# Start services
docker-compose -f docker-compose.analytics-dashboard.yml up -d

# Check health
curl -f https://analytics.guideai.company.com/api/health

# Monitor logs
docker-compose -f docker-compose.analytics-dashboard.yml logs -f
```

4. **Configure monitoring:**

```yaml
# Add to prometheus.yml
scrape_configs:
  - job_name: 'metabase'
    static_configs:
      - targets: ['localhost:3000']
    metrics_path: '/api/health'
```

## Maintenance

### Backup Metabase Configuration

```bash
# Export all dashboards/questions
podman exec guideai-metabase \
  java -jar /app/metabase.jar export \
  /backup/metabase-$(date +%Y%m%d).dump

# Copy to safe location
podman cp guideai-metabase:/backup/metabase-20251020.dump \
  ./backups/
```

### Update Metabase Version

```bash
# Stop current instance
podman-compose -f docker-compose.analytics-dashboard.yml down

# Update image tag in docker-compose.analytics-dashboard.yml
# metabase/metabase:v0.48.0 → v0.49.0

# Restart with new version
podman-compose -f docker-compose.analytics-dashboard.yml up -d

# Verify upgrade
podman-compose -f docker-compose.analytics-dashboard.yml logs metabase
```

### Refresh DuckDB Connection

If warehouse schema changes:

1. Go to **Admin** → **Databases** → **GuideAI Analytics Warehouse**
2. Click **Sync database schema now**
3. Wait for completion (~10 seconds)
4. Verify new tables/views appear in **Data Model**

## Troubleshooting

### Metabase won't start

```bash
# Check logs
podman-compose -f docker-compose.analytics-dashboard.yml logs metabase

# Common issues:
# - Podman machine not running → podman machine start
# - Port 3000 already in use → change ports: "3001:3000"
# - Insufficient memory → increase JAVA_OPTS: "-Xmx2g"
# - Corrupted H2 database → delete volume: podman volume rm guideai_metabase-data
```

### Can't connect to DuckDB

```bash
# Verify file exists and is readable
podman exec guideai-metabase ls -lh /duckdb/telemetry.duckdb

# Test query directly
podman exec guideai-metabase \
  sqlite3 /duckdb/telemetry.duckdb \
  "SELECT COUNT(*) FROM main.fact_behavior_usage;"

# If not found, check volume mount in docker-compose.analytics-dashboard.yml
```

### Dashboards show "No results"

```bash
# Verify warehouse has data
python -c "import duckdb; conn = duckdb.connect('data/telemetry.duckdb'); print(conn.execute('SELECT COUNT(*) FROM main.fact_behavior_usage').fetchone())"

# Check date filters (may be filtering out all data)
# Adjust dashboard date range to "All Time"

# Verify SQL syntax compatibility
# DuckDB uses slightly different syntax than SQLite
```

### Queries are slow

```bash
# Add indexes to DuckDB warehouse
python -c "
import duckdb
conn = duckdb.connect('data/telemetry.duckdb')
conn.execute('CREATE INDEX IF NOT EXISTS idx_behavior_usage_timestamp ON main.fact_behavior_usage(execution_timestamp);')
conn.execute('CREATE INDEX IF NOT EXISTS idx_token_savings_timestamp ON main.fact_token_savings(execution_timestamp);')
conn.close()
"

# Increase Metabase memory
# Edit docker-compose.yml: JAVA_OPTS: "-Xmx2g -Xms1g"
```

## Security Considerations

- [ ] Change default admin password immediately
- [ ] Enable HTTPS for production deployments
- [ ] Configure firewall rules (allow only internal network)
- [ ] Mount DuckDB warehouse as read-only (`:ro` flag)
- [ ] Use secrets manager for credentials (avoid .env files in production)
- [ ] Enable audit logging in Metabase Enterprise
- [ ] Configure row-level permissions if multi-tenant
- [ ] Regularly update Metabase image for security patches

## Resources

- **Metabase Documentation:** https://www.metabase.com/docs/latest/
- **DuckDB SQL Reference:** https://duckdb.org/docs/sql/introduction
- **Podman Setup Guide:** `deployment/PODMAN.md`
- **Container Comparison:** `deployment/CONTAINER_COMPARISON.md`
- **PRD Metrics Schema:** `docs/analytics/prd_metrics_schema.sql`
- **Warehouse Client:** `guideai/analytics/warehouse.py`
- **REST API Endpoints:** http://localhost:8000/v1/analytics/*

## Referenced Behaviors

- `behavior_orchestrate_cicd` – Docker Compose configuration and deployment
- `behavior_externalize_configuration` – Environment variables and secrets management
- `behavior_instrument_metrics_pipeline` – Dashboard queries wired to warehouse
- `behavior_update_docs_after_changes` – Documentation and runbook maintenance
- `behavior_lock_down_security_surface` – Security checklist and production hardening

---

**Next Steps:**
1. ✅ Deploy Metabase locally and test DuckDB connection
2. ⏳ Author dashboard JSON exports for 4 PRD metrics
3. ⏳ Provision production Postgres for Metabase metadata
4. ⏳ Configure SSO/SAML authentication (if Enterprise)
5. ⏳ Set up alerting and scheduled email reports
