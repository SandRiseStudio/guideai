#!/usr/bin/env bash
# Safe test runner for GuideAI with Podman containers
# Behaviors: behavior_align_storage_layers, behavior_unify_execution_records,
#            behavior_instrument_metrics_pipeline
#
# Usage:
#   ./scripts/run_tests.sh                    # Run all tests serially (safest)
#   ./scripts/run_tests.sh -n 2               # Run with 2 workers
#   ./scripts/run_tests.sh tests/test_cli_*.py  # Run specific tests
#   ./scripts/run_tests.sh --check-only       # Only check environment
#   ./scripts/run_tests.sh --amprealize --env ci    # Use amprealize with 'ci' environment
#   ./scripts/run_tests.sh --env-file custom.yaml --env prod  # Custom manifest and environment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export GUIDEAI_REPO_ROOT="$REPO_ROOT"
cd "$REPO_ROOT"

# =============================================================================
# Terminal Styling (Amprealize-aligned)
# =============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

# Symbols
SYM_CHECK="✓"
SYM_CROSS="✗"
SYM_WARN="⚠"
SYM_DOT="•"

# Output helpers for consistent styling
print_header() {
    local title="$1"
    local line="━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo -e "${BLUE}${line}${NC}"
    echo -e "${BOLD}              $title${NC}"
    echo -e "${BLUE}${line}${NC}"
}

print_section() {
    echo ""
    echo -e "${CYAN}${BOLD}$1${NC}"
}

print_success() {
    echo -e "  ${GREEN}${SYM_CHECK}${NC} $1"
}

print_error() {
    echo -e "  ${RED}${SYM_CROSS}${NC} $1"
}

print_warning() {
    echo -e "  ${YELLOW}${SYM_WARN}${NC} $1"
}

print_info() {
    echo -e "  ${DIM}${SYM_DOT}${NC} $1"
}

print_kv() {
    local key="$1"
    local value="$2"
    echo -e "  ${DIM}${key}:${NC}$(printf '%*s' $((18 - ${#key})) '') $value"
}

# =============================================================================
# Configuration
# =============================================================================

PARALLEL_WORKERS=0
CHECK_ONLY=false
PYTEST_ARGS=()
CONNECTION_TIMEOUT=5
QUERY_TIMEOUT=30
GUIDEAI_TEST_INFRA_MODE="${GUIDEAI_TEST_INFRA_MODE:-legacy}"
GUIDEAI_AMPREALIZE_ENV_FILE_DEFAULT="$REPO_ROOT/environments.yaml"
export GUIDEAI_AMPREALIZE_ENV_FILE="${GUIDEAI_AMPREALIZE_ENV_FILE:-$GUIDEAI_AMPREALIZE_ENV_FILE_DEFAULT}"
export GUIDEAI_AMPREALIZE_ENVIRONMENT="${GUIDEAI_AMPREALIZE_ENVIRONMENT:-ci}"
GUIDEAI_AMPREALIZE_MANAGED_MACHINE=""
GUIDEAI_AMPREALIZE_MACHINE_NAME=""
NETSTAT_LAST_RX_BYTES=""
NETSTAT_LAST_TX_BYTES=""
WITH_KAFKA=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --check-only)
            CHECK_ONLY=true
            shift
            ;;
        --amprealize)
            GUIDEAI_TEST_INFRA_MODE="amprealize"
            shift
            ;;
        --with-kafka)
            WITH_KAFKA=true
            shift
            ;;
        --env)
            export GUIDEAI_AMPREALIZE_ENVIRONMENT="$2"
            shift 2
            ;;
        --env-file)
            export GUIDEAI_AMPREALIZE_ENV_FILE="$2"
            shift 2
            ;;
        -n)
            PARALLEL_WORKERS="$2"
            shift 2
            ;;
        --help|-h)
            print_header "GuideAI Test Runner"
            echo ""
            echo "Usage: $0 [options] [test-paths...]"
            echo ""
            echo -e "${CYAN}Options:${NC}"
            print_kv "--check-only" "Only check environment, don't run tests"
            print_kv "--amprealize" "Use Amprealize infrastructure mode"
            print_kv "--env <name>" "Specify environment name (default: ci)"
            print_kv "--env-file <path>" "Specify environment manifest file"
            print_kv "--with-kafka" "Enable Kafka streaming module"
            print_kv "-n <workers>" "Number of parallel workers (0=serial)"
            print_kv "-h, --help" "Show this help message"
            echo ""
            echo -e "${CYAN}Examples:${NC}"
            print_info "$0                                    # Run all tests"
            print_info "$0 --amprealize                       # Use amprealize infra"
            print_info "$0 --amprealize --env development     # Use 'development' env"
            print_info "$0 --amprealize --env test --with-kafka  # Include Kafka"
            print_info "$0 -n 4 tests/test_api.py            # Run tests in parallel"
            echo ""
            exit 0
            ;;
        *)
            PYTEST_ARGS+=("$1")
            shift
            ;;
    esac
done

if [ ${#PYTEST_ARGS[@]} -eq 0 ]; then
    PYTEST_ARGS=("tests/")
fi

STAGING_STACK_MODE="${GUIDEAI_ENABLE_STAGING_STACK:-auto}"
START_STAGING_STACK=false
STAGING_STACK_ACTIVE=false
STAGING_PORT_REASSIGNED=false

# =============================================================================
# Environment Variables Loading
# =============================================================================

# Load amprealize environment variables from environments.yaml
# This exports all variables from the 'variables' section of the specified environment
load_amprealize_variables() {
    local env_file="$1"
    local env_name="$2"

    [ ! -f "$env_file" ] && return 1

    # Parse YAML and export variables
    eval "$(python - "$env_file" "$env_name" <<'PY'
import sys, yaml
from pathlib import Path

manifest_path, env_name = Path(sys.argv[1]), sys.argv[2]
try:
    data = yaml.safe_load(manifest_path.read_text()) or {}
except Exception:
    sys.exit(1)

env = (data.get("environments") or {}).get(env_name)
if not env:
    sys.exit(1)

variables = env.get("variables") or {}
for key, value in variables.items():
    # Escape single quotes in values
    safe_value = str(value).replace("'", "'\\''")
    print(f"export {key}='{safe_value}'")
PY
)"
}

# Load required_endpoints from environments.yaml (amprealize-driven health checks)
# Returns endpoints as "host|port|label" lines for the specified environment
load_amprealize_endpoints() {
    local env_file="$1"
    local env_name="$2"

    [ ! -f "$env_file" ] && return 1

    python - "$env_file" "$env_name" <<'PY'
import sys, yaml
from pathlib import Path

manifest_path, env_name = Path(sys.argv[1]), sys.argv[2]
try:
    data = yaml.safe_load(manifest_path.read_text()) or {}
except Exception:
    sys.exit(1)

env = (data.get("environments") or {}).get(env_name)
if not env:
    sys.exit(1)

endpoints = env.get("required_endpoints") or []
for ep in endpoints:
    host = ep.get("host", "localhost")
    port = ep.get("port", 0)
    label = ep.get("label", f"{host}:{port}")
    print(f"{host}|{port}|{label}")
PY
}

# If in amprealize mode, load variables from environments.yaml FIRST
# These will override the defaults set below
if [ "$GUIDEAI_TEST_INFRA_MODE" = "amprealize" ]; then
    # IMPORTANT: Unset any pre-existing DSN variables to prevent stale values
    # from overriding freshly constructed DSNs. The ${VAR:-default} pattern
    # only applies defaults if VAR is unset, so we must explicitly unset.
    unset GUIDEAI_TELEMETRY_PG_DSN 2>/dev/null || true
    unset GUIDEAI_BEHAVIOR_PG_DSN 2>/dev/null || true
    unset GUIDEAI_WORKFLOW_PG_DSN 2>/dev/null || true
    unset GUIDEAI_ACTION_PG_DSN 2>/dev/null || true
    unset GUIDEAI_RUN_PG_DSN 2>/dev/null || true
    unset GUIDEAI_COMPLIANCE_PG_DSN 2>/dev/null || true
    unset GUIDEAI_ORCHESTRATOR_PG_DSN 2>/dev/null || true
    unset GUIDEAI_METRICS_PG_DSN 2>/dev/null || true

    if [ -f "$GUIDEAI_AMPREALIZE_ENV_FILE" ]; then
        load_amprealize_variables "$GUIDEAI_AMPREALIZE_ENV_FILE" "$GUIDEAI_AMPREALIZE_ENVIRONMENT" || true
    fi
fi

# =============================================================================
# Default Environment Variables (used when not overridden by amprealize)
# =============================================================================

# Database connection defaults - amprealize mode overrides these via environments.yaml
export GUIDEAI_PG_HOST_BEHAVIOR="${GUIDEAI_PG_HOST_BEHAVIOR:-localhost}"
export GUIDEAI_PG_PORT_BEHAVIOR="${GUIDEAI_PG_PORT_BEHAVIOR:-5433}"
export GUIDEAI_PG_USER_BEHAVIOR="${GUIDEAI_PG_USER_BEHAVIOR:-behavior}"
export GUIDEAI_PG_PASS_BEHAVIOR="${GUIDEAI_PG_PASS_BEHAVIOR:-behavior_dev}"
export GUIDEAI_PG_DB_BEHAVIOR="${GUIDEAI_PG_DB_BEHAVIOR:-behavior}"

export GUIDEAI_PG_HOST_WORKFLOW="${GUIDEAI_PG_HOST_WORKFLOW:-localhost}"
export GUIDEAI_PG_PORT_WORKFLOW="${GUIDEAI_PG_PORT_WORKFLOW:-5434}"
export GUIDEAI_PG_USER_WORKFLOW="${GUIDEAI_PG_USER_WORKFLOW:-workflow}"
export GUIDEAI_PG_PASS_WORKFLOW="${GUIDEAI_PG_PASS_WORKFLOW:-workflow_dev}"
export GUIDEAI_PG_DB_WORKFLOW="${GUIDEAI_PG_DB_WORKFLOW:-workflow}"

export GUIDEAI_PG_HOST_ACTION="${GUIDEAI_PG_HOST_ACTION:-localhost}"
export GUIDEAI_PG_PORT_ACTION="${GUIDEAI_PG_PORT_ACTION:-5435}"
export GUIDEAI_PG_USER_ACTION="${GUIDEAI_PG_USER_ACTION:-action}"
export GUIDEAI_PG_PASS_ACTION="${GUIDEAI_PG_PASS_ACTION:-action_dev}"
export GUIDEAI_PG_DB_ACTION="${GUIDEAI_PG_DB_ACTION:-action}"

export GUIDEAI_PG_HOST_RUN="${GUIDEAI_PG_HOST_RUN:-localhost}"
export GUIDEAI_PG_PORT_RUN="${GUIDEAI_PG_PORT_RUN:-5436}"
export GUIDEAI_PG_USER_RUN="${GUIDEAI_PG_USER_RUN:-run}"
export GUIDEAI_PG_PASS_RUN="${GUIDEAI_PG_PASS_RUN:-run_dev}"
export GUIDEAI_PG_DB_RUN="${GUIDEAI_PG_DB_RUN:-run}"

export GUIDEAI_PG_HOST_COMPLIANCE="${GUIDEAI_PG_HOST_COMPLIANCE:-localhost}"
export GUIDEAI_PG_PORT_COMPLIANCE="${GUIDEAI_PG_PORT_COMPLIANCE:-5437}"
export GUIDEAI_PG_USER_COMPLIANCE="${GUIDEAI_PG_USER_COMPLIANCE:-compliance}"
export GUIDEAI_PG_PASS_COMPLIANCE="${GUIDEAI_PG_PASS_COMPLIANCE:-compliance_dev}"
export GUIDEAI_PG_DB_COMPLIANCE="${GUIDEAI_PG_DB_COMPLIANCE:-compliance}"

export GUIDEAI_PG_HOST_TELEMETRY="${GUIDEAI_PG_HOST_TELEMETRY:-localhost}"
export GUIDEAI_PG_PORT_TELEMETRY="${GUIDEAI_PG_PORT_TELEMETRY:-5432}"
export GUIDEAI_PG_USER_TELEMETRY="${GUIDEAI_PG_USER_TELEMETRY:-telemetry}"
export GUIDEAI_PG_PASS_TELEMETRY="${GUIDEAI_PG_PASS_TELEMETRY:-telemetry_dev}"
export GUIDEAI_PG_DB_TELEMETRY="${GUIDEAI_PG_DB_TELEMETRY:-telemetry}"

export GUIDEAI_PG_HOST_METRICS="${GUIDEAI_PG_HOST_METRICS:-localhost}"
export GUIDEAI_PG_PORT_METRICS="${GUIDEAI_PG_PORT_METRICS:-5439}"
export GUIDEAI_PG_USER_METRICS="${GUIDEAI_PG_USER_METRICS:-guideai_metrics_user}"
export GUIDEAI_PG_PASS_METRICS="${GUIDEAI_PG_PASS_METRICS:-local_metrics_dev_pw}"
export GUIDEAI_PG_DB_METRICS="${GUIDEAI_PG_DB_METRICS:-guideai_metrics}"

export GUIDEAI_PG_HOST_AUTH="${GUIDEAI_PG_HOST_AUTH:-localhost}"
export GUIDEAI_PG_PORT_AUTH="${GUIDEAI_PG_PORT_AUTH:-5440}"
export GUIDEAI_PG_USER_AUTH="${GUIDEAI_PG_USER_AUTH:-guideai_auth}"
export GUIDEAI_PG_PASS_AUTH="${GUIDEAI_PG_PASS_AUTH:-dev_auth_pass}"
export GUIDEAI_PG_DB_AUTH="${GUIDEAI_PG_DB_AUTH:-guideai_auth}"

# Blueprint port variables (used by local-test-suite.yaml)
# These map to the same ports as GUIDEAI_PG_PORT_* but with the naming the blueprint expects
export TELEMETRY_DB_PORT="${TELEMETRY_DB_PORT:-$GUIDEAI_PG_PORT_TELEMETRY}"
export BEHAVIOR_DB_PORT="${BEHAVIOR_DB_PORT:-$GUIDEAI_PG_PORT_BEHAVIOR}"
export WORKFLOW_DB_PORT="${WORKFLOW_DB_PORT:-$GUIDEAI_PG_PORT_WORKFLOW}"
export ACTION_DB_PORT="${ACTION_DB_PORT:-$GUIDEAI_PG_PORT_ACTION}"
export RUN_DB_PORT="${RUN_DB_PORT:-$GUIDEAI_PG_PORT_RUN}"
export COMPLIANCE_DB_PORT="${COMPLIANCE_DB_PORT:-$GUIDEAI_PG_PORT_COMPLIANCE}"
export ORCHESTRATOR_DB_PORT="${ORCHESTRATOR_DB_PORT:-6438}"
export METRICS_DB_PORT="${METRICS_DB_PORT:-$GUIDEAI_PG_PORT_METRICS}"
export AUTH_DB_PORT="${AUTH_DB_PORT:-$GUIDEAI_PG_PORT_AUTH}"
export REDIS_LOCAL_PORT="${REDIS_LOCAL_PORT:-6379}"
export KAFKA_EXTERNAL_PORT="${KAFKA_EXTERNAL_PORT:-10092}"
# Redis and Kafka port mappings for the blueprint
export REDIS_PORT="${REDIS_PORT:-$REDIS_LOCAL_PORT}"
export KAFKA_PORT="${KAFKA_PORT:-$KAFKA_EXTERNAL_PORT}"

export REDIS_HOST="${REDIS_HOST:-localhost}"
export REDIS_URL="${REDIS_URL:-redis://${REDIS_HOST}:${REDIS_PORT}/0}"
export CACHE_REDIS_URL="${CACHE_REDIS_URL:-$REDIS_URL}"
export KAFKA_BOOTSTRAP_SERVERS="${KAFKA_BOOTSTRAP_SERVERS:-localhost:${KAFKA_PORT}}"

ENCODED_STATEMENT_TIMEOUT="-c%20statement_timeout%3D${QUERY_TIMEOUT}s"
DSN_QUERY_PARAMS="?connect_timeout=${CONNECTION_TIMEOUT}&options=${ENCODED_STATEMENT_TIMEOUT}"

# Construct DSNs from the (possibly overridden) variables
export GUIDEAI_BEHAVIOR_PG_DSN="${GUIDEAI_BEHAVIOR_PG_DSN:-postgresql://${GUIDEAI_PG_USER_BEHAVIOR}:${GUIDEAI_PG_PASS_BEHAVIOR}@${GUIDEAI_PG_HOST_BEHAVIOR}:${GUIDEAI_PG_PORT_BEHAVIOR}/${GUIDEAI_PG_DB_BEHAVIOR}${DSN_QUERY_PARAMS}}"
export GUIDEAI_WORKFLOW_PG_DSN="${GUIDEAI_WORKFLOW_PG_DSN:-postgresql://${GUIDEAI_PG_USER_WORKFLOW}:${GUIDEAI_PG_PASS_WORKFLOW}@${GUIDEAI_PG_HOST_WORKFLOW}:${GUIDEAI_PG_PORT_WORKFLOW}/${GUIDEAI_PG_DB_WORKFLOW}${DSN_QUERY_PARAMS}}"
export GUIDEAI_ACTION_PG_DSN="${GUIDEAI_ACTION_PG_DSN:-postgresql://${GUIDEAI_PG_USER_ACTION}:${GUIDEAI_PG_PASS_ACTION}@${GUIDEAI_PG_HOST_ACTION}:${GUIDEAI_PG_PORT_ACTION}/${GUIDEAI_PG_DB_ACTION}${DSN_QUERY_PARAMS}}"
export GUIDEAI_RUN_PG_DSN="${GUIDEAI_RUN_PG_DSN:-postgresql://${GUIDEAI_PG_USER_RUN}:${GUIDEAI_PG_PASS_RUN}@${GUIDEAI_PG_HOST_RUN}:${GUIDEAI_PG_PORT_RUN}/${GUIDEAI_PG_DB_RUN}${DSN_QUERY_PARAMS}}"
export GUIDEAI_COMPLIANCE_PG_DSN="${GUIDEAI_COMPLIANCE_PG_DSN:-postgresql://${GUIDEAI_PG_USER_COMPLIANCE}:${GUIDEAI_PG_PASS_COMPLIANCE}@${GUIDEAI_PG_HOST_COMPLIANCE}:${GUIDEAI_PG_PORT_COMPLIANCE}/${GUIDEAI_PG_DB_COMPLIANCE}${DSN_QUERY_PARAMS}}"
export GUIDEAI_TELEMETRY_PG_DSN="${GUIDEAI_TELEMETRY_PG_DSN:-postgresql://${GUIDEAI_PG_USER_TELEMETRY}:${GUIDEAI_PG_PASS_TELEMETRY}@${GUIDEAI_PG_HOST_TELEMETRY}:${GUIDEAI_PG_PORT_TELEMETRY}/${GUIDEAI_PG_DB_TELEMETRY}${DSN_QUERY_PARAMS}}"
export GUIDEAI_METRICS_PG_DSN="${GUIDEAI_METRICS_PG_DSN:-postgresql://${GUIDEAI_PG_USER_METRICS}:${GUIDEAI_PG_PASS_METRICS}@${GUIDEAI_PG_HOST_METRICS}:${GUIDEAI_PG_PORT_METRICS}/${GUIDEAI_PG_DB_METRICS}${DSN_QUERY_PARAMS}}"
export GUIDEAI_AUTH_PG_DSN="${GUIDEAI_AUTH_PG_DSN:-postgresql://${GUIDEAI_PG_USER_AUTH}:${GUIDEAI_PG_PASS_AUTH}@${GUIDEAI_PG_HOST_AUTH}:${GUIDEAI_PG_PORT_AUTH}/${GUIDEAI_PG_DB_AUTH}${DSN_QUERY_PARAMS}}"
export GUIDEAI_TRACE_ANALYSIS_PG_DSN="${GUIDEAI_TRACE_ANALYSIS_PG_DSN:-$GUIDEAI_BEHAVIOR_PG_DSN}"
export GUIDEAI_AGENTAUTH_PG_DSN="${GUIDEAI_AGENTAUTH_PG_DSN:-$GUIDEAI_TELEMETRY_PG_DSN}"
export DATABASE__POSTGRES_URL="${DATABASE__POSTGRES_URL:-$GUIDEAI_AGENTAUTH_PG_DSN}"
export GUIDEAI_TASK_PG_DSN="${GUIDEAI_TASK_PG_DSN:-$GUIDEAI_TELEMETRY_PG_DSN}"

# API Server config
API_SERVER_HOST="${GUIDEAI_API_SERVER_HOST:-localhost}"
API_SERVER_PORT="${GUIDEAI_API_SERVER_PORT:-8000}"
API_SERVER_LOG_DIR="${GUIDEAI_API_SERVER_LOG_DIR:-$REPO_ROOT/.tmp}"
API_SERVER_LOG_FILE="${GUIDEAI_API_SERVER_LOG_FILE:-$API_SERVER_LOG_DIR/api_server.log}"
API_SERVER_WORKERS="${GUIDEAI_API_SERVER_WORKERS:-1}"

if ! [[ "$API_SERVER_WORKERS" =~ ^[0-9]+$ ]] || [ "$API_SERVER_WORKERS" -lt 1 ]; then
    print_error "GUIDEAI_API_SERVER_WORKERS must be a positive integer (received '${API_SERVER_WORKERS}')"
    exit 1
fi

ORIGINAL_API_BASE_URL="http://${API_SERVER_HOST}:${API_SERVER_PORT}"

build_default_api_server_cmd() {
    local cmd="uvicorn guideai.api:create_app --factory --host 0.0.0.0 --port ${API_SERVER_PORT}"
    if [ "$API_SERVER_WORKERS" -gt 1 ]; then
        cmd="${cmd} --workers ${API_SERVER_WORKERS}"
    fi
    echo "$cmd"
}

DEFAULT_API_SERVER_CMD="$(build_default_api_server_cmd)"
API_SERVER_CMD="${GUIDEAI_API_SERVER_CMD:-$DEFAULT_API_SERVER_CMD}"
API_SERVER_STARTED_BY_SCRIPT=false
API_SERVER_PID=""

# Default endpoints for non-amprealize mode
DEFAULT_REQUIRED_ENDPOINTS=(
    "${GUIDEAI_PG_HOST_BEHAVIOR}|${GUIDEAI_PG_PORT_BEHAVIOR}|PostgreSQL Behavior"
    "${GUIDEAI_PG_HOST_WORKFLOW}|${GUIDEAI_PG_PORT_WORKFLOW}|PostgreSQL Workflow"
    "${GUIDEAI_PG_HOST_ACTION}|${GUIDEAI_PG_PORT_ACTION}|PostgreSQL Action"
    "${GUIDEAI_PG_HOST_RUN}|${GUIDEAI_PG_PORT_RUN}|PostgreSQL Run"
    "${GUIDEAI_PG_HOST_COMPLIANCE}|${GUIDEAI_PG_PORT_COMPLIANCE}|PostgreSQL Compliance"
    "${GUIDEAI_PG_HOST_TELEMETRY}|${GUIDEAI_PG_PORT_TELEMETRY}|TimescaleDB Telemetry"
    "${GUIDEAI_PG_HOST_METRICS}|${GUIDEAI_PG_PORT_METRICS}|TimescaleDB Metrics"
    "${GUIDEAI_PG_HOST_AUTH}|${GUIDEAI_PG_PORT_AUTH}|PostgreSQL Auth"
    "${REDIS_HOST}|${REDIS_PORT}|Redis"
)

# Build REQUIRED_ENDPOINTS: use amprealize config if available, otherwise use defaults
REQUIRED_ENDPOINTS=()
if [ "$GUIDEAI_TEST_INFRA_MODE" = "amprealize" ] && [ -f "$GUIDEAI_AMPREALIZE_ENV_FILE" ]; then
    # Read endpoints from environments.yaml (amprealize-driven health checks)
    while IFS= read -r line; do
        [ -n "$line" ] && REQUIRED_ENDPOINTS+=("$line")
    done < <(load_amprealize_endpoints "$GUIDEAI_AMPREALIZE_ENV_FILE" "$GUIDEAI_AMPREALIZE_ENVIRONMENT" 2>/dev/null)
fi

# Fall back to defaults if no amprealize endpoints defined
if [ ${#REQUIRED_ENDPOINTS[@]} -eq 0 ]; then
    REQUIRED_ENDPOINTS=("${DEFAULT_REQUIRED_ENDPOINTS[@]}")
    # Only require Kafka if explicitly requested (legacy mode)
    if [ "$WITH_KAFKA" = "true" ]; then
        REQUIRED_ENDPOINTS+=("localhost|${KAFKA_PORT}|Kafka")
    fi
fi

COMPOSE_FILE="$REPO_ROOT/docker-compose.test.yml"
STAGING_COMPOSE_FILE="$REPO_ROOT/deployment/podman-compose-staging.yml"
STAGING_NETWORK_NAME="guideai-postgres-net"
STAGING_ENDPOINTS=(
    "localhost|8000|Staging API"
    "localhost|8080|Staging NGINX"
)

if [ ! -f "$COMPOSE_FILE" ]; then
    print_error "Missing docker-compose.test.yml at $COMPOSE_FILE"
    exit 1
fi

# =============================================================================
# Utility Functions
# =============================================================================

is_port_ready() {
    # Use -G for connection timeout on macOS, -w on Linux
    nc -z -G 2 "$1" "$2" 2>/dev/null || nc -z -w 2 "$1" "$2" 2>/dev/null
}

check_port() {
    local host=$1 port=$2 service=$3
    if nc -z -G 2 "$host" "$port" 2>/dev/null || nc -z -w 2 "$host" "$port" 2>/dev/null; then
        print_success "$service"
        return 0
    else
        print_error "$service ${DIM}($host:$port)${NC}"
        return 1
    fi
}

find_free_port() {
    python - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
}

format_bytes() {
    local bytes="${1:-0}"
    if ! [[ "$bytes" =~ ^[0-9]+$ ]]; then
        echo "${bytes}B"
        return
    fi
    python - <<PY
value = float(${bytes:-0})
units = ["B", "KB", "MB", "GB", "TB"]
idx = 0
while value >= 1024 and idx < len(units) - 1:
    value /= 1024.0
    idx += 1
print(f"{value:.1f}{units[idx]}")
PY
}

format_duration() {
    local seconds=$1
    if [ "$seconds" -lt 60 ]; then
        echo "${seconds}s"
    elif [ "$seconds" -lt 3600 ]; then
        echo "$((seconds / 60))m $((seconds % 60))s"
    else
        echo "$((seconds / 3600))h $((seconds % 3600 / 60))m"
    fi
}

# =============================================================================
# Resource Monitoring
# =============================================================================

capture_netstat_totals() {
    if ! command -v netstat >/dev/null 2>&1; then
        return 1
    fi
    local sums
    sums=$(netstat -ib 2>/dev/null | awk 'NR>1 && NF>=11 && $10 ~ /^[0-9]+$/ && $11 ~ /^[0-9]+$/ {rx+=$10; tx+=$11} END {if (rx+tx>0) printf "%s %s", rx, tx}')
    [ -n "$sums" ] && echo "$sums"
}

report_resources() {
    local stage="$1"

    if [ "$GUIDEAI_TEST_INFRA_MODE" != "amprealize" ]; then
        return
    fi

    print_section "Resources ($stage)"

    # Host info
    local host_name host_desc
    host_name=$(hostname 2>/dev/null || echo "unknown")
    host_desc=$(uname -srm 2>/dev/null || echo "unknown")
    print_kv "Host" "$host_name (${host_desc})"
    print_kv "Environment" "${GUIDEAI_AMPREALIZE_ENVIRONMENT:-n/a}"

    # Memory (macOS)
    local memory_used_mb=0 memory_total_mb=0 memory_pct=0
    if command -v vm_stat >/dev/null 2>&1 && command -v sysctl >/dev/null 2>&1; then
        local page_size total_bytes free_pages free_bytes used_bytes
        page_size=$(sysctl -n hw.pagesize 2>/dev/null || echo 4096)
        total_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
        free_pages=$(vm_stat | awk '/Pages (free|inactive)/ {gsub(".", "", $3); total+=$3} END {print total+0}' 2>/dev/null)
        free_bytes=$((free_pages * page_size))
        [ "$free_bytes" -lt 0 ] && free_bytes=0
        used_bytes=$((total_bytes - free_bytes))
        [ "$used_bytes" -lt 0 ] && used_bytes=0
        memory_used_mb=$((used_bytes / 1024 / 1024))
        memory_total_mb=$((total_bytes / 1024 / 1024))
        if [ "$memory_total_mb" -gt 0 ]; then
            memory_pct=$((memory_used_mb * 100 / memory_total_mb))
        fi
        print_kv "Memory" "$(format_bytes "$used_bytes") / $(format_bytes "$total_bytes")"
    fi

    # Podman machine specs
    local podman_cpus=0 podman_memory_mb=0 podman_disk_gb=0
    if [ -n "$GUIDEAI_AMPREALIZE_MACHINE_NAME" ] && command -v podman >/dev/null 2>&1; then
        local inspect_output cpus memory_mb disk_gb
        if inspect_output=$(podman machine inspect "$GUIDEAI_AMPREALIZE_MACHINE_NAME" 2>/dev/null); then
            cpus=$(printf '%s' "$inspect_output" | jq -r '.[0].VM.Resources.CPUs // empty' 2>/dev/null)
            memory_mb=$(printf '%s' "$inspect_output" | jq -r '.[0].VM.Resources.Memory // empty' 2>/dev/null)
            disk_gb=$(printf '%s' "$inspect_output" | jq -r '.[0].VM.Resources.DiskSize // empty' 2>/dev/null)
            if [ -n "$cpus" ] && [ -n "$memory_mb" ]; then
                podman_cpus=$cpus
                podman_memory_mb=$memory_mb
                [ -n "$disk_gb" ] && podman_disk_gb=$disk_gb
                print_kv "Podman VM" "${cpus} CPU / $(format_bytes $((memory_mb * 1024 * 1024)))"
            fi
        fi
    fi

    # Container stats (max CPU/mem)
    local cpu_max_num=0
    if command -v podman >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
        local stats_json cpu_max mem_max
        stats_json=$(podman stats --no-stream --format "json" 2>/dev/null)
        if [ -n "$stats_json" ]; then
            cpu_max=$(echo "$stats_json" | jq -r 'max_by(.CPUPerc // 0) | .CPUPerc' 2>/dev/null)
            mem_max=$(echo "$stats_json" | jq -r 'max_by(.MemPerc // 0) | .MemPerc' 2>/dev/null)
            if [ -n "$cpu_max" ] && [ "$cpu_max" != "null" ]; then
                cpu_max_num=$(echo "$cpu_max" | tr -d '%' | cut -d. -f1)
                print_kv "Container Peak" "CPU ${cpu_max} / Mem ${mem_max}"
            fi
        fi
    fi

    # Disk usage from Podman
    local disk_used_mb=0 disk_total_mb=0
    if command -v podman >/dev/null 2>&1; then
        local df_output total_size
        df_output=$(podman system df --format "json" 2>/dev/null || echo "{}")
        total_size=$(echo "$df_output" | jq '[.Images[]?.Size // 0, .Containers[]?.Size // 0, .Volumes[]?.Size // 0] | add // 0' 2>/dev/null || echo "0")
        disk_used_mb=$((total_size / 1024 / 1024))
        disk_total_mb=$((podman_disk_gb * 1024))
    fi

    # Network delta
    local totals current_rx current_tx
    if totals=$(capture_netstat_totals); then
        current_rx=$(echo "$totals" | awk '{print $1}')
        current_tx=$(echo "$totals" | awk '{print $2}')
        if [ -n "$NETSTAT_LAST_RX_BYTES" ] && [ -n "$NETSTAT_LAST_TX_BYTES" ]; then
            local delta_rx=$((current_rx - NETSTAT_LAST_RX_BYTES))
            local delta_tx=$((current_tx - NETSTAT_LAST_TX_BYTES))
            [ "$delta_rx" -lt 0 ] && delta_rx=0
            [ "$delta_tx" -lt 0 ] && delta_tx=0
            print_kv "Network" "↓$(format_bytes "$delta_rx") ↑$(format_bytes "$delta_tx")"
        fi
        NETSTAT_LAST_RX_BYTES="$current_rx"
        NETSTAT_LAST_TX_BYTES="$current_tx"
    fi

    # Resource Insights (plain-English status)
    # Thresholds from env vars or defaults
    local memory_warning="${AMPREALIZE_INSIGHT_MEMORY_WARNING:-70}"
    local memory_critical="${AMPREALIZE_INSIGHT_MEMORY_CRITICAL:-90}"
    local disk_warning="${AMPREALIZE_INSIGHT_DISK_WARNING:-75}"
    local disk_critical="${AMPREALIZE_INSIGHT_DISK_CRITICAL:-90}"
    local cpu_warning="${AMPREALIZE_INSIGHT_CPU_WARNING:-70}"
    local cpu_critical="${AMPREALIZE_INSIGHT_CPU_CRITICAL:-90}"

    # Color codes
    local GREEN='\033[32m' YELLOW='\033[33m' RED='\033[31m' RESET='\033[0m'

    echo ""
    echo "  Resource Insights:"

    # Memory insight
    if [ "$memory_total_mb" -gt 0 ]; then
        local mem_color="$GREEN" mem_icon="🟢" mem_msg="healthy"
        if [ "$memory_pct" -ge "$memory_critical" ]; then
            mem_color="$RED"; mem_icon="🔴"; mem_msg="at capacity - performance may degrade"
        elif [ "$memory_pct" -ge "$memory_warning" ]; then
            mem_color="$YELLOW"; mem_icon="🟡"; mem_msg="nearing capacity"
        elif [ "$memory_pct" -lt 10 ]; then
            mem_color="$GREEN"; mem_icon="🟢"; mem_msg="plenty available"
        fi
        echo -e "    Memory: ${mem_color}${mem_icon} ${mem_msg}${RESET} (${memory_pct}%)"
    fi

    # Disk insight
    if [ "$disk_total_mb" -gt 0 ]; then
        local disk_pct=$((disk_used_mb * 100 / disk_total_mb))
        local disk_color="$GREEN" disk_icon="🟢" disk_msg="healthy"
        if [ "$disk_pct" -ge "$disk_critical" ]; then
            disk_color="$RED"; disk_icon="🔴"; disk_msg="nearly full - action required"
        elif [ "$disk_pct" -ge "$disk_warning" ]; then
            disk_color="$YELLOW"; disk_icon="🟡"; disk_msg="running low"
        elif [ "$disk_pct" -lt 30 ]; then
            disk_color="$GREEN"; disk_icon="🟢"; disk_msg="plenty available"
        fi
        echo -e "    Disk: ${disk_color}${disk_icon} ${disk_msg}${RESET} (${disk_pct}%)"
    fi

    # CPU insight (from container stats)
    if [ "$cpu_max_num" -gt 0 ] 2>/dev/null; then
        local cpu_color="$GREEN" cpu_icon="🟢" cpu_msg="healthy"
        if [ "$cpu_max_num" -ge "$cpu_critical" ]; then
            cpu_color="$RED"; cpu_icon="🔴"; cpu_msg="maxed out - system under heavy load"
        elif [ "$cpu_max_num" -ge "$cpu_warning" ]; then
            cpu_color="$YELLOW"; cpu_icon="🟡"; cpu_msg="usage elevated"
        elif [ "$cpu_max_num" -lt 20 ]; then
            cpu_color="$GREEN"; cpu_icon="🟢"; cpu_msg="barely utilized"
        fi
        echo -e "    CPU: ${cpu_color}${cpu_icon} ${cpu_msg}${RESET} (${cpu_max_num}%)"
    fi
}

# =============================================================================
# Staging Stack
# =============================================================================

requires_staging_tests() {
    local total=${#PYTEST_ARGS[@]}
    [ $total -eq 0 ] && return 1

    for ((i = 0; i < total; i++)); do
        local arg="${PYTEST_ARGS[$i]}"
        case "$arg" in
            tests|tests/|tests/.|tests/smoke|tests/smoke/*|tests/smoke/test_staging_core.py*)
                return 0 ;;
        esac
        [[ "$arg" == *"staging"* ]] && return 0
        if [[ "$arg" == "-k" || "$arg" == "-m" ]] && [ $((i + 1)) -lt $total ]; then
            [[ "${PYTEST_ARGS[$((i + 1))]}" == *"staging"* ]] && return 0
        fi
    done
    return 1
}

should_enable_staging_stack() {
    local mode
    mode="$(printf '%s' "$STAGING_STACK_MODE" | tr '[:upper:]' '[:lower:]')"
    case "$mode" in
        1|true|on|yes) return 0 ;;
        0|false|off|no) return 1 ;;
    esac
    requires_staging_tests
}

should_enable_staging_stack && START_STAGING_STACK=true

refresh_api_server_cmd() {
    [ -z "${GUIDEAI_API_SERVER_CMD:-}" ] && API_SERVER_CMD="$(build_default_api_server_cmd)"
    ORIGINAL_API_BASE_URL="http://${API_SERVER_HOST}:${API_SERVER_PORT}"
}

set_api_env_vars() {
    local computed_url="http://${API_SERVER_HOST}:${API_SERVER_PORT}"
    if [ -z "${GUIDEAI_API_URL:-}" ] || [ "${GUIDEAI_API_URL}" = "${ORIGINAL_API_BASE_URL}" ]; then
        export GUIDEAI_API_URL="$computed_url"
    fi
    export GUIDEAI_API_SERVER_PORT="$API_SERVER_PORT"
}

api_server_supports_internal_auth() {
    local base_url="http://${API_SERVER_HOST}:${API_SERVER_PORT}"
    command -v curl >/dev/null 2>&1 || return 1
    # Use --max-time to prevent hanging on slow/unresponsive servers
    curl -sf --max-time 2 "${base_url}/health" >/dev/null 2>&1 && \
    curl -sf --max-time 2 "${base_url}/api/v1/auth/providers" >/dev/null 2>&1
}

# =============================================================================
# Amprealize Infrastructure
# =============================================================================

load_amprealize_env_details() {
    python - "$1" "$2" <<'PY'
import json, sys, yaml
from pathlib import Path

manifest_path, env_name = Path(sys.argv[1]), sys.argv[2]
try:
    data = yaml.safe_load(manifest_path.read_text()) or {}
except FileNotFoundError:
    print(f"Error: Manifest not found at {manifest_path}", file=sys.stderr)
    sys.exit(1)

env = (data.get("environments") or {}).get(env_name)
if not env:
    print(f"Error: Environment '{env_name}' not defined", file=sys.stderr)
    sys.exit(1)

infra = env.get("infrastructure") or {}
if not infra.get("blueprint_id"):
    print(f"Error: Missing blueprint_id for '{env_name}'", file=sys.stderr)
    sys.exit(1)

# Return environment details including active_modules for amprealize-driven module filtering
print(json.dumps({
    "blueprint_id": infra["blueprint_id"],
    "runtime": env.get("runtime") or {},
    "active_modules": env.get("active_modules") or []
}))
PY
}

cleanup_amprealize_machine() {
    if [ -n "$GUIDEAI_AMPREALIZE_MANAGED_MACHINE" ]; then
        podman machine stop "$GUIDEAI_AMPREALIZE_MANAGED_MACHINE" >/dev/null 2>&1 || true
        GUIDEAI_AMPREALIZE_MANAGED_MACHINE=""
        GUIDEAI_AMPREALIZE_MACHINE_NAME=""
    fi
}

ensure_amprealize_podman_machine() {
    local provider="$1" machine_name="$2" memory_limit_mb="$3" cpu_limit="$4"
    [ "$provider" != "podman" ] || [ -z "$machine_name" ] && return

    command -v podman >/dev/null 2>&1 || { print_error "Podman CLI required"; exit 1; }
    command -v jq >/dev/null 2>&1 || { print_error "jq required"; exit 1; }

    local machine_list
    machine_list=$(podman machine list --format json 2>/dev/null) || { print_error "Cannot query podman machines"; exit 1; }

    # Stop conflicting machines
    local running_machines
    running_machines=$(echo "$machine_list" | jq -r '.[] | select(.Running == true) | .Name')
    for name in $running_machines; do
        [ "$name" != "$machine_name" ] && podman machine stop "$name" >/dev/null 2>&1 || true
    done

    # Initialize if needed
    machine_list=$(podman machine list --format json 2>/dev/null)
    if ! echo "$machine_list" | jq -e ".[] | select(.Name == \"$machine_name\")" >/dev/null; then
        print_info "Initializing Podman machine '$machine_name'..."
        local init_args=()
        [[ "$cpu_limit" =~ ^[0-9]+$ ]] && [ "$cpu_limit" -gt 0 ] && init_args+=(--cpus "$cpu_limit")
        [[ "$memory_limit_mb" =~ ^[0-9]+$ ]] && [ "$memory_limit_mb" -gt 0 ] && init_args+=(--memory "$memory_limit_mb")
        podman machine init "${init_args[@]}" "$machine_name"
    fi

    # Start if needed
    if ! echo "$machine_list" | jq -e ".[] | select(.Name == \"$machine_name\" and .Running == true)" >/dev/null; then
        print_info "Starting Podman machine '$machine_name'..."
        podman machine start "$machine_name"
    fi

    # Get socket
    local socket_path=""
    local inspect_output
    if inspect_output=$(podman machine inspect "$machine_name" 2>/dev/null); then
        socket_path=$(printf '%s' "$inspect_output" | jq -r '.[0].ConnectionInfo.PodmanSocket.Path // ""')
    fi

    if [ -n "$socket_path" ] && [ "$socket_path" != "<nil>" ]; then
        export CONTAINER_HOST="unix://$socket_path"
        export GUIDEAI_AMPREALIZE_PODMAN_SOCKET="$socket_path"
    fi

    GUIDEAI_AMPREALIZE_MANAGED_MACHINE="$machine_name"
}

ensure_amprealize_infrastructure() {
    print_section "Amprealize Infrastructure"

    local env_file="$GUIDEAI_AMPREALIZE_ENV_FILE"
    local env_name="$GUIDEAI_AMPREALIZE_ENVIRONMENT"

    [ ! -f "$env_file" ] && { print_error "Manifest not found: $env_file"; exit 1; }

    export GUIDEAI_ENV_FILE="$env_file"
    local env_details
    env_details=$(load_amprealize_env_details "$env_file" "$env_name") || { cleanup_amprealize_machine; exit 1; }

    local blueprint_id runtime_provider runtime_machine runtime_memory runtime_cpus active_modules_json
    blueprint_id=$(echo "$env_details" | jq -r '.blueprint_id')
    runtime_provider=$(echo "$env_details" | jq -r '.runtime.provider // ""')
    runtime_machine=$(echo "$env_details" | jq -r '.runtime.podman_machine // ""')
    runtime_memory=$(echo "$env_details" | jq -r '.runtime.memory_limit_mb // 0')
    runtime_cpus=$(echo "$env_details" | jq -r '.runtime.cpu_limit // 0')
    active_modules_json=$(echo "$env_details" | jq -c '.active_modules // []')

    GUIDEAI_AMPREALIZE_MACHINE_NAME="$runtime_machine"
    ensure_amprealize_podman_machine "$runtime_provider" "$runtime_machine" "$runtime_memory" "$runtime_cpus"

    print_kv "Environment" "$env_name"
    print_kv "Blueprint" "$blueprint_id"
    print_kv "Manifest" "$env_file"

    # Build module arguments from environment config (amprealize-driven)
    local module_args=()
    local modules_display=""

    # Read active_modules from environment config
    while IFS= read -r mod; do
        [ -n "$mod" ] && module_args+=("--module" "$mod") && modules_display="${modules_display:+$modules_display, }$mod"
    done < <(echo "$active_modules_json" | jq -r '.[]' 2>/dev/null)

    # If WITH_KAFKA is set and streaming not already included, add it
    if [ "$WITH_KAFKA" = "true" ]; then
        if [[ ! " ${module_args[*]} " =~ " streaming " ]]; then
            module_args+=("--module" "streaming")
            modules_display="${modules_display:+$modules_display, }streaming (Kafka via --with-kafka)"
        fi
    fi

    # Fallback to core if no modules defined
    if [ ${#module_args[@]} -eq 0 ]; then
        module_args=("--module" "core")
        modules_display="core (default)"
    fi

    print_kv "Modules" "$modules_display"

    # Plan
    print_info "Planning..."
    local plan_output
    plan_output=$(GUIDEAI_ENV_FILE="$env_file" guideai amprealize plan \
        --blueprint-id "$blueprint_id" \
        --environment "$env_name" \
        --env-file "$env_file" \
        --force-podman \
        "${module_args[@]}" \
        --output json) || { print_error "Plan failed"; cleanup_amprealize_machine; exit 1; }

    export GUIDEAI_AMPREALIZE_PLAN_ID=$(echo "$plan_output" | jq -r '.plan_id')
    export GUIDEAI_AMPREALIZE_RUN_ID=$(echo "$plan_output" | jq -r '.amp_run_id')

    [ -z "$GUIDEAI_AMPREALIZE_PLAN_ID" ] || [ "$GUIDEAI_AMPREALIZE_PLAN_ID" = "null" ] && {
        print_error "Failed to extract plan_id"
        exit 1
    }

    local service_count estimated_boot
    service_count=$(echo "$plan_output" | jq '.signed_manifest.blueprint.services | keys | length' 2>/dev/null || echo "?")
    estimated_boot=$(echo "$plan_output" | jq -r '.environment_estimates.expected_boot_duration_s // "?"' 2>/dev/null)

    print_success "Plan created"
    print_kv "Plan ID" "$GUIDEAI_AMPREALIZE_PLAN_ID"
    print_kv "Services" "$service_count"
    print_kv "Est. Boot" "${estimated_boot}s"

    # Apply with full resource management enabled:
    # - proactive-cleanup: Run cleanup BEFORE resource check
    # - auto-cleanup: Handle low resources during provisioning
    # - auto-cleanup-aggressive: Include images/cache in cleanup
    # - auto-resolve-stale: Remove stale/exited/dead containers
    # - auto-resolve-conflicts: Resolve port conflicts automatically
    # - stale-max-age-hours=0: Clean ALL stale containers (any age)
    print_info "Applying (with auto-resolve and proactive cleanup enabled)..."
    GUIDEAI_ENV_FILE="$env_file" guideai amprealize apply \
        --plan-id "$GUIDEAI_AMPREALIZE_PLAN_ID" \
        --env-file "$env_file" \
        --force-podman \
        --proactive-cleanup \
        --auto-cleanup \
        --auto-cleanup-aggressive \
        --auto-resolve-stale \
        --auto-resolve-conflicts \
        --stale-max-age-hours 0 \
        --allow-host-resource-warning \
        --watch || { print_error "Apply failed"; cleanup_amprealize_machine; exit 1; }

    # Wait for all required services to be ready (including Kafka if enabled)
    print_info "Waiting for services to be ready..."
    local max_attempts=60
    local attempt=0
    while [ $attempt -lt $max_attempts ]; do
        local all_ready=true
        for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
            IFS='|' read -r host port label <<< "$endpoint"
            if ! is_port_ready "$host" "$port"; then
                all_ready=false
                if [ $((attempt % 10)) -eq 0 ]; then
                    print_warning "Waiting for $label on $host:$port..."
                fi
                break
            fi
        done

        if [ "$all_ready" = true ]; then
            break
        fi

        attempt=$((attempt + 1))
        sleep 2
    done

    if [ "$all_ready" != true ]; then
        print_error "Services not ready after ${max_attempts} attempts"
        for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
            IFS='|' read -r host port label <<< "$endpoint"
            if ! is_port_ready "$host" "$port"; then
                print_error "  - $label on $host:$port not responding"
            fi
        done
        cleanup_amprealize_machine
        exit 1
    fi

    print_success "Infrastructure ready"
    export GUIDEAI_TEST_INFRA_MODE="amprealize"
}

teardown_amprealize_infrastructure() {
    if [ "$GUIDEAI_TEST_INFRA_MODE" = "amprealize" ] && [ -n "${GUIDEAI_AMPREALIZE_RUN_ID:-}" ]; then
        local env_file="$GUIDEAI_AMPREALIZE_ENV_FILE"
        [ -f "$env_file" ] && export GUIDEAI_ENV_FILE="$env_file"
        print_info "Tearing down infrastructure..."
        guideai amprealize destroy \
            --run-id "$GUIDEAI_AMPREALIZE_RUN_ID" \
            --reason "POST_TEST" \
            --force-podman \
            --env-file "$env_file" 2>/dev/null || true
        unset GUIDEAI_AMPREALIZE_PLAN_ID GUIDEAI_AMPREALIZE_RUN_ID
    fi
}

# =============================================================================
# Legacy Infrastructure
# =============================================================================

ensure_test_infrastructure() {
    if [ "$GUIDEAI_TEST_INFRA_MODE" = "amprealize" ]; then
        ensure_amprealize_infrastructure
        return
    fi

    print_section "Infrastructure"

    local missing_services=()
    for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
        IFS='|' read -r host port label <<< "$endpoint"
        is_port_ready "$host" "$port" || missing_services+=("$label")
    done

    if [ ${#missing_services[@]} -eq 0 ]; then
        print_success "All services reachable"
        return
    fi

    print_warning "Starting missing services..."

    command -v podman >/dev/null 2>&1 || { print_error "Podman not installed"; exit 1; }
    podman info >/dev/null 2>&1 || {
        command -v podman-machine >/dev/null 2>&1 && podman machine start >/dev/null || {
            print_error "Podman machine not running"
            print_info "Start with: ${DIM}podman machine start${NC}"
            exit 1
        }
    }

    local -a compose_cmd
    command -v podman-compose >/dev/null 2>&1 && compose_cmd=(podman-compose) || compose_cmd=(podman compose)

    "${compose_cmd[@]}" -f "$COMPOSE_FILE" up -d >/dev/null

    local attempt=0 max_attempts=30
    while [ $attempt -lt $max_attempts ]; do
        local ready=true
        for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
            IFS='|' read -r host port _ <<< "$endpoint"
            is_port_ready "$host" "$port" || { ready=false; break; }
        done
        [ "$ready" = true ] && { print_success "Infrastructure ready"; return; }
        attempt=$((attempt + 1))
        sleep 2
    done

    print_error "Infrastructure failed to start"
    exit 1
}

ensure_staging_stack() {
    [ "$START_STAGING_STACK" != true ] && return
    [ "$STAGING_STACK_ACTIVE" = true ] && return
    [ ! -f "$STAGING_COMPOSE_FILE" ] && { print_error "Missing staging compose file"; exit 1; }

    print_section "Staging Stack"

    command -v podman >/dev/null 2>&1 || { print_error "Podman required"; exit 1; }
    podman info >/dev/null 2>&1 || podman machine start >/dev/null
    podman network exists "$STAGING_NETWORK_NAME" >/dev/null 2>&1 || podman network create "$STAGING_NETWORK_NAME" >/dev/null

    local compose_cmd
    command -v podman-compose >/dev/null 2>&1 && compose_cmd=(podman-compose) || compose_cmd=(podman compose)

    export GUIDEAI_STAGING_UPSTREAM_HOST="${GUIDEAI_STAGING_UPSTREAM_HOST:-guideai-api-staging}"
    export GUIDEAI_STAGING_UPSTREAM_PORT="${GUIDEAI_STAGING_UPSTREAM_PORT:-8000}"

    local staging_ready=true
    for endpoint in "${STAGING_ENDPOINTS[@]}"; do
        IFS='|' read -r host port _ <<< "$endpoint"
        is_port_ready "$host" "$port" || { staging_ready=false; break; }
    done

    if [ "$staging_ready" = false ]; then
        print_info "Starting staging containers..."
        "${compose_cmd[@]}" -f "$STAGING_COMPOSE_FILE" up -d >/dev/null

        local attempt=0 max_attempts=60
        while [ $attempt -lt $max_attempts ]; do
            local ready=true
            for endpoint in "${STAGING_ENDPOINTS[@]}"; do
                IFS='|' read -r host port _ <<< "$endpoint"
                is_port_ready "$host" "$port" || { ready=false; break; }
            done
            [ "$ready" = true ] && { staging_ready=true; break; }
            attempt=$((attempt + 1))
            sleep 2
        done
        [ "$staging_ready" = false ] && { print_error "Staging stack failed to start"; exit 1; }
    fi

    STAGING_STACK_ACTIVE=true
    export STAGING_API_URL="${STAGING_API_URL:-http://localhost:8000}"
    export STAGING_NGINX_URL="${STAGING_NGINX_URL:-http://localhost:8080}"

    if [ "$STAGING_PORT_REASSIGNED" = false ]; then
        local fallback_port
        fallback_port="$(find_free_port)"
        if [ -n "$fallback_port" ]; then
            API_SERVER_PORT="$fallback_port"
            STAGING_PORT_REASSIGNED=true
            refresh_api_server_cmd
        fi
    fi

    print_success "Staging stack ready"
}

# =============================================================================
# Schema Migrations
# =============================================================================

ensure_schema() {
    local name="$1" table="$2" dsn_var="$3" migration_script="$4"

    local table_exists=""
    if command -v psql >/dev/null 2>&1; then
        local dsn="${!dsn_var}"
        table_exists=$(psql "$dsn" -Atqc "SELECT to_regclass('public.${table}');" 2>/dev/null || echo "")
    fi

    if [[ "$table_exists" == "$table" ]]; then
        return 0
    fi

    # Run migration - suppress output but allow failures (migrations may have been applied)
    python "$migration_script" --dsn "${!dsn_var}" >/dev/null 2>&1 || true
    return 0
}

ensure_all_schemas() {
    print_section "Database Schemas"

    # Helper to check if a service is in required endpoints
    is_service_required() {
        local port="$1"
        for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
            IFS='|' read -r host p label <<< "$endpoint"
            [ "$p" = "$port" ] && return 0
        done
        return 1
    }

    # Temporarily enable verbose output for debugging
    set -x

    # Telemetry schema (port 5432 or 6432)
    if is_service_required "$GUIDEAI_PG_PORT_TELEMETRY"; then
        ensure_schema "Telemetry" "telemetry_events" "GUIDEAI_TELEMETRY_PG_DSN" "$REPO_ROOT/scripts/run_postgres_telemetry_migration.py"
        # Base telemetry warehouse (001)
        python "$REPO_ROOT/scripts/run_postgres_telemetry_migration.py" --dsn "$GUIDEAI_TELEMETRY_PG_DSN" --migration "$REPO_ROOT/schema/migrations/001_create_telemetry_warehouse.sql" >/dev/null 2>&1 || true
    fi

    # Metrics schema (port 5439)
    if is_service_required "$GUIDEAI_PG_PORT_METRICS"; then
        ensure_schema "Metrics" "metrics_snapshots" "GUIDEAI_METRICS_PG_DSN" "$REPO_ROOT/scripts/run_postgres_metrics_migration.py"
    fi

    # Behavior migrations (port 5433)
    if is_service_required "$GUIDEAI_PG_PORT_BEHAVIOR"; then
        local migrations=(
            "$REPO_ROOT/schema/migrations/002_create_behavior_service.sql"
            "$REPO_ROOT/schema/migrations/015_add_behavior_namespace.sql"
        )
        for migration in "${migrations[@]}"; do
            [ -f "$migration" ] && python "$REPO_ROOT/scripts/run_postgres_behavior_migration.py" --migration "$migration" >/dev/null 2>&1
        done
        # Trace analysis schema (013)
        python "$REPO_ROOT/scripts/run_postgres_trace_migration.py" --dsn "$GUIDEAI_TRACE_ANALYSIS_PG_DSN" >/dev/null 2>&1 || true
    fi

    # Workflow migrations (port 5434)
    if is_service_required "$GUIDEAI_PG_PORT_WORKFLOW"; then
        local workflow_migrations=(
            "$REPO_ROOT/schema/migrations/003_create_workflow_service.sql"
            "$REPO_ROOT/schema/migrations/009_refactor_workflow_schema.sql"
        )
        for migration in "${workflow_migrations[@]}"; do
            [ -f "$migration" ] && python "$REPO_ROOT/scripts/run_postgres_workflow_migration.py" --migration "$migration" >/dev/null 2>&1 || true
        done
    fi

    # Action service schema (port 5435)
    if is_service_required "$GUIDEAI_PG_PORT_ACTION"; then
        python "$REPO_ROOT/scripts/run_postgres_action_migration.py" >/dev/null 2>&1 || true
    fi

    # Run service schema (port 5436)
    if is_service_required "$GUIDEAI_PG_PORT_RUN"; then
        python "$REPO_ROOT/scripts/run_postgres_run_migration.py" >/dev/null 2>&1 || true
    fi

    # Compliance service schema (port 5437)
    if is_service_required "$GUIDEAI_PG_PORT_COMPLIANCE"; then
        python "$REPO_ROOT/scripts/run_postgres_compliance_migration.py" >/dev/null 2>&1 || true
    fi

    # Auth service schema (port 5440)
    if is_service_required "$GUIDEAI_PG_PORT_AUTH"; then
        python "$REPO_ROOT/scripts/run_postgres_auth_migration.py" >/dev/null 2>&1 || true
    fi

    set +x

    print_success "Schemas ready"
}

# =============================================================================
# API Server
# =============================================================================

start_api_server() {
    if [ "${GUIDEAI_SKIP_API_SERVER:-0}" = "1" ]; then
        set_api_env_vars
        return
    fi

    if is_port_ready "$API_SERVER_HOST" "$API_SERVER_PORT"; then
        if api_server_supports_internal_auth; then
            print_success "API server ready (${API_SERVER_HOST}:${API_SERVER_PORT})"
            set_api_env_vars
            return
        fi

        local fallback_port
        fallback_port="$(find_free_port)"
        [ -z "$fallback_port" ] && { print_error "No free port for API server"; exit 1; }
        API_SERVER_PORT="$fallback_port"
        refresh_api_server_cmd
    fi

    print_info "Starting API server on port ${API_SERVER_PORT}..."
    mkdir -p "$API_SERVER_LOG_DIR"
    nohup bash -c "$API_SERVER_CMD" > "$API_SERVER_LOG_FILE" 2>&1 &
    API_SERVER_PID=$!
    API_SERVER_STARTED_BY_SCRIPT=true

    local attempt=0 max_attempts=60
    while [ $attempt -lt $max_attempts ]; do
        if is_port_ready "$API_SERVER_HOST" "$API_SERVER_PORT"; then
            print_success "API server ready"
            set_api_env_vars
            return
        fi
        kill -0 "$API_SERVER_PID" >/dev/null 2>&1 || {
            print_error "API server exited unexpectedly"
            tail -n 20 "$API_SERVER_LOG_FILE" 2>/dev/null || true
            exit 1
        }
        attempt=$((attempt + 1))
        sleep 0.5
    done

    print_error "API server timeout"
    exit 1
}

stop_api_server() {
    if [ "$API_SERVER_STARTED_BY_SCRIPT" = true ] && [ -n "$API_SERVER_PID" ]; then
        kill "$API_SERVER_PID" >/dev/null 2>&1 || true
        wait "$API_SERVER_PID" >/dev/null 2>&1 || true
    fi
}

cleanup() {
    local exit_code="${1:-0}"
    stop_api_server
    [ "$GUIDEAI_TEST_INFRA_MODE" = "amprealize" ] && teardown_amprealize_infrastructure
    cleanup_amprealize_machine
}

# Handle signals properly - INT/TERM should exit after cleanup
handle_signal() {
    echo ""
    print_warning "Interrupted - cleaning up..."
    cleanup
    exit 130  # Standard exit code for SIGINT
}

trap cleanup EXIT
trap handle_signal INT TERM

# =============================================================================
# Main Execution
# =============================================================================

print_header "GuideAI Test Runner"

# Show configuration
print_kv "Mode" "$GUIDEAI_TEST_INFRA_MODE"
[ "$GUIDEAI_TEST_INFRA_MODE" = "amprealize" ] && print_kv "Environment" "$GUIDEAI_AMPREALIZE_ENVIRONMENT"
print_kv "Workers" "${PARALLEL_WORKERS:-serial}"
print_kv "Tests" "${PYTEST_ARGS[*]}"

# Setup infrastructure
ensure_test_infrastructure

# Verify services
print_section "Service Health"
all_healthy=true
for endpoint in "${REQUIRED_ENDPOINTS[@]}"; do
    IFS='|' read -r host port label <<< "$endpoint"
    check_port "$host" "$port" "$label" || all_healthy=false
done

if [ "$all_healthy" = false ]; then
    echo ""
    print_error "Some services unavailable"
    print_info "Start containers: ${DIM}podman-compose -f docker-compose.test.yml up -d${NC}"
    exit 1
fi

# Schemas & staging
ensure_all_schemas
# Always start staging stack when smoke tests require it, regardless of infra mode
# NGINX and staging API are needed for tests/smoke/test_staging_core.py
ensure_staging_stack

# Resource snapshot
report_resources "pre-tests"

# Check only mode
if [ "$CHECK_ONLY" = true ]; then
    echo ""
    print_success "Environment ready"
    exit 0
fi

# Clean up stale API server processes before starting
cleanup_stale_api_server() {
    local port="${API_SERVER_PORT:-8000}"
    local pid
    pid=$(lsof -i ":$port" -t -sTCP:LISTEN 2>/dev/null | head -1) || true

    if [ -n "$pid" ]; then
        local cmd
        cmd=$(ps -p "$pid" -o comm= 2>/dev/null) || cmd="unknown"

        # Only kill guideai-related processes (python, uvicorn, etc.)
        case "$cmd" in
            python*|uvicorn*|gunicorn*|guideai*)
                print_info "Killing stale process on port $port (PID: $pid, cmd: $cmd)..."
                kill "$pid" 2>/dev/null || true
                sleep 0.5
                # Force kill if still alive
                kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null || true
                print_success "Cleaned up stale process"
                ;;
            *)
                print_warning "Port $port in use by: $cmd (PID: $pid) - skipping cleanup"
                ;;
        esac
    fi
}

# Start API server
print_section "API Server"
cleanup_stale_api_server
start_api_server

# =============================================================================
# Test Execution
# =============================================================================

print_header "Running Tests"

PYTEST_CMD="pytest"
[ "$PARALLEL_WORKERS" -gt 0 ] && PYTEST_CMD="$PYTEST_CMD -n $PARALLEL_WORKERS --dist=loadfile"
PYTEST_CMD="$PYTEST_CMD -v ${PYTEST_ARGS[*]}"

echo ""
echo -e "${DIM}$PYTEST_CMD${NC}"
echo ""

start_time=$(date +%s)

set +e
eval "$PYTEST_CMD"
test_exit_code=$?
set -e

end_time=$(date +%s)
duration=$((end_time - start_time))

# =============================================================================
# Results
# =============================================================================

print_header "Results"

print_kv "Duration" "$(format_duration $duration)"

if [ $test_exit_code -eq 0 ]; then
    print_success "All tests passed"
else
    print_error "Tests failed (exit code: $test_exit_code)"
    echo ""
    print_info "Troubleshooting:"
    print_info "  ${DIM}podman logs <container>${NC}"
    print_info "  ${DIM}pytest -v <test>::<name>${NC}"
fi

report_resources "post-tests"

exit $test_exit_code
