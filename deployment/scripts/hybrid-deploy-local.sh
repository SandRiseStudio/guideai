#!/bin/bash
# Hybrid Flink Architecture - Local Development Setup
# ARM64-compatible development environment using dev mode

set -e

echo "🚀 Deploying GuideAI Hybrid Flink - Local Development Environment"
echo "=================================================================="

# Configuration
CONFIG_FILE="deployment/config/hybrid-flink.env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check if Podman is available (preferred)
    if command -v podman >/dev/null 2>&1; then
        log_success "Podman is available (preferred)"
    elif command -v docker >/dev/null 2>&1; then
        log_warning "Docker is available (fallback to Podman)"
    else
        log_error "Neither Podman nor Docker is available. Please install Podman."
        exit 1
    fi

    # Check if Podman machine is running (if using Podman Desktop)
    if command -v podman >/dev/null 2>&1 && [[ "$OSTYPE" == "darwin"* ]]; then
        if ! podman machine info >/dev/null 2>&1; then
            log_info "Starting Podman machine..."
            podman machine start
        fi
    fi

    # Check if Python 3.11+ is available
    if ! python3 --version | grep -E "3\.(11|12|13)" > /dev/null; then
        log_error "Python 3.11+ required. Current version:"
        python3 --version
        exit 1
    fi

    # Check if GuideAI is installed
    if ! python3 -c "import guideai" 2>/dev/null; then
        log_warning "GuideAI not installed. Installing in development mode..."
        pip install -e ".[telemetry]"
    fi

    log_success "Prerequisites check passed"
}

# Load configuration
load_config() {
    log_info "Loading configuration from $CONFIG_FILE"

    if [ -f "$CONFIG_FILE" ]; then
        # Set environment variables
        set -a
        source "$CONFIG_FILE"
        set +a

        # Ensure local mode
        DEPLOYMENT_MODE=local
        FLINK_MODE=dev
        WAREHOUSE_TYPE=duckdb

        log_success "Configuration loaded successfully"
    else
        log_error "Configuration file not found: $CONFIG_FILE"
        exit 1
    fi
}

# Start local infrastructure
start_infrastructure() {
    log_info "Starting local Kafka infrastructure (Podman-first approach)..."

    # Check if compose file exists
    COMPOSE_FILE="docker-compose.telemetry.yml"
    if [ ! -f "$COMPOSE_FILE" ]; then
        log_error "Compose file not found: $COMPOSE_FILE"
        exit 1
    fi

    # Determine which container runtime to use
    if command -v podman >/dev/null 2>&1; then
        log_info "Using Podman for container orchestration..."
        RUNTIME="podman"
        if command -v podman-compose >/dev/null 2>&1; then
            COMPOSE_CMD="podman-compose"
        else
            log_error "podman-compose not found. Install: pip install podman-compose"
            exit 1
        fi
    elif command -v docker >/dev/null 2>&1; then
        log_info "Using Docker for container orchestration..."
        RUNTIME="docker"
        COMPOSE_CMD="docker compose"
    else
        log_error "No container runtime available"
        exit 1
    fi

    # Start services
    log_info "Starting Kafka, TimescaleDB, and monitoring services..."
    if $COMPOSE_CMD -f "$COMPOSE_FILE" up -d; then
        log_success "Infrastructure started successfully with $RUNTIME"
    else
        log_error "Failed to start infrastructure"
        exit 1
    fi

    # Wait for services to be ready
    log_info "Waiting for services to be ready..."
    sleep 30

    # Check service health
    check_service_health
}

# Check service health
check_service_health() {
    log_info "Checking service health..."

    # Determine which container runtime to use for health checks
    if command -v podman >/dev/null 2>&1; then
        CONTAINER_CMD="podman"
        KAFKA_CONTAINER="guideai-kafka"
        DB_CONTAINER="guideai-postgres-telemetry"
    else
        CONTAINER_CMD="docker"
        KAFKA_CONTAINER="guideai-kafka"
        DB_CONTAINER="guideai-postgres-telemetry"
    fi

    # Check Kafka
    if $CONTAINER_CMD exec $KAFKA_CONTAINER kafka-broker-api-versions --bootstrap-server localhost:9092 > /dev/null 2>&1; then
        log_success "Kafka is healthy"
    else
        log_error "Kafka is not responding"
        return 1
    fi

    # Check TimescaleDB
    if $CONTAINER_CMD exec $DB_CONTAINER pg_isready -U guideai_telemetry -d guideai_telemetry > /dev/null 2>&1; then
        log_success "TimescaleDB is healthy"
    else
        log_error "TimescaleDB is not responding"
        return 1
    fi

    log_success "All services are healthy"
}

# Create data directories
setup_data_directories() {
    log_info "Setting up data directories..."

    mkdir -p data/logs
    mkdir -p data/checkpoints
    mkdir -p data/telemetry

    log_success "Data directories created"
}

# Validate local deployment
validate_deployment() {
    log_info "Validating local deployment..."

    cd "$PROJECT_ROOT"

    # Run validation script if it exists
    if [ -f "scripts/validate_telemetry_pipeline.sh" ]; then
        log_info "Running telemetry pipeline validation..."
        if ./scripts/validate_telemetry_pipeline.sh; then
            log_success "Local deployment validation passed"
        else
            log_warning "Local deployment validation had issues - check logs"
        fi
    else
        log_warning "Validation script not found - manual validation required"
    fi
}

# Start Flink job in dev mode
start_flink_job() {
    log_info "Starting Flink job in dev mode..."

    cd "$PROJECT_ROOT"

    # Start the job in background
    nohup python deployment/flink/telemetry_kpi_job.py \
        --mode dev \
        --kafka-servers "$KAFKA_BOOTSTRAP_SERVERS" \
        --kafka-topic "$KAFKA_TOPIC_TELEMETRY_EVENTS" \
        > data/logs/flink-dev.log 2>&1 &

    FLINK_PID=$!
    echo $FLINK_PID > data/logs/flink-dev.pid

    log_success "Flink dev mode job started (PID: $FLINK_PID)"
    log_info "Logs available at: data/logs/flink-dev.log"

    # Wait a moment and check if job is running
    sleep 5
    if kill -0 $FLINK_PID 2>/dev/null; then
        log_success "Flink job is running successfully"
    else
        log_error "Flink job failed to start - check logs"
        return 1
    fi
}

# Show status
show_status() {
    echo ""
    echo "🎉 Local Development Environment Ready!"
    echo "========================================="
    echo ""

    # Show container runtime info
    if command -v podman >/dev/null 2>&1; then
        echo "🔧 Container Runtime: Podman (preferred)"
        echo "   Check status: podman ps"
    elif command -v docker >/dev/null 2>&1; then
        echo "🔧 Container Runtime: Docker (fallback)"
        echo "   Check status: docker ps"
    fi

    echo ""
    echo "📊 Monitoring Links:"
    echo "   - Kafka UI: http://localhost:8080"
    echo "   - Flink Dashboard: http://localhost:8081"
    echo "   - pgAdmin: http://localhost:5050 (admin@example.com / admin)"
    echo ""
    echo "🔧 Local Services:"
    echo "   - Kafka: localhost:9092"
    echo "   - TimescaleDB: localhost:5432"
    echo "   - DuckDB: data/telemetry.duckdb"
    echo ""
    echo "📝 Logs:"
    echo "   - Flink Job: data/logs/flink-dev.log"
    echo "   - Flink PID: data/logs/flink-dev.pid"
    echo ""
    echo "🔄 Next Steps:"
    echo "   1. Test event emission: ./scripts/seed_telemetry_data.py"
    echo "   2. Check KPI projection: python examples/validate_metrics.py"
    echo "   3. Monitor real-time processing in dashboard"
    echo ""

    # Show appropriate stop command
    if command -v podman >/dev/null 2>&1 && command -v podman-compose >/dev/null 2>&1; then
        echo "🛑 To stop: podman-compose -f docker-compose.telemetry.yml down"
    elif command -v docker >/dev/null 2>&1; then
        echo "🛑 To stop: docker compose -f docker-compose.telemetry.yml down"
    else
        echo "🛑 To stop services: Check container runtime status and stop manually"
    fi
}

# Main execution
main() {
    echo "Starting at: $(date)"
    echo "Working directory: $(pwd)"
    echo ""

    check_prerequisites
    load_config
    start_infrastructure
    setup_data_directories
    start_flink_job
    validate_deployment
    show_status

    echo ""
    log_success "Local development environment deployment completed successfully!"
    log_info "Time taken: $(($(date +%s) - $(date -d "$(echo 'Starting at: ')" +%s))) seconds"
}

# Script entry point
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
