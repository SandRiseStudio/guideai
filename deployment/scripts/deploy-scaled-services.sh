#!/bin/bash

# GuideAI Scaled Services Deployment Script
# Deploys all GuideAI services with horizontal scaling
# Date: 2025-11-08
# Usage: ./deployment/scripts/deploy-scaled-services.sh [start|stop|status|logs|cleanup|scale]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/podman-compose-scaled.yml"
CONFIG_DIR="$PROJECT_DIR/config"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
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

    # Check if podman is installed
    if ! command -v podman &> /dev/null; then
        log_error "Podman is not installed. Please install Podman first."
        log_info "Visit: https://podman.io/getting-started/installation"
        exit 1
    fi

    # Check if podman-compose is installed
    if ! command -v podman-compose &> /dev/null; then
        log_error "Podman Compose is not installed. Please install podman-compose first."
        log_info "pip install podman-compose"
        exit 1
    fi

    # Check if compose file exists
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        log_error "Compose file not found: $COMPOSE_FILE"
        exit 1
    fi

    # Check if podman machine is running (if using podman machine)
    if command -v podman &> /dev/null && podman system info &> /dev/null; then
        if ! podman system info | grep -q "host.machine: running"; then
            log_warning "Podman machine is not running. Starting podman machine..."
            podman machine start || log_warning "Could not start podman machine"
        fi
    fi

    log_success "Prerequisites check passed"
}

# Create necessary directories
setup_directories() {
    log_info "Setting up directories..."

    mkdir -p "$PROJECT_DIR/data"/{behaviors,actions,runs,compliance,orchestrator,bci,mcp}
    mkdir -p "$PROJECT_DIR/logs"
    mkdir -p "$PROJECT_DIR/backups"
    mkdir -p "$CONFIG_DIR"/{nginx,redis,prometheus,grafana}
    mkdir -p "$PROJECT_DIR/deployment/config/ssl"
    mkdir -p "$PROJECT_DIR/deployment/config/prometheus/rules"

    log_success "Directories created"
}

# Generate configuration files
generate_configs() {
    log_info "Generating configuration files..."

    # Create prometheus alert rules
    cat > "$CONFIG_DIR/prometheus/rules/scaling-alerts.yml" << 'EOF'
groups:
- name: guideai-scaling
  rules:
  - alert: HighResponseTime
    expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 0.5
    for: 2m
    labels:
      severity: warning
    annotations:
      summary: "High response time detected"
      description: "95th percentile response time is {{ $value }}s"

  - alert: HighErrorRate
    expr: sum(rate(http_requests_total{status=~"5.."}[5m])) / sum(rate(http_requests_total[5m])) * 100 > 5
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "High error rate detected"
      description: "Error rate is {{ $value }}%"

  - alert: ServiceDown
    expr: up == 0
    for: 1m
    labels:
      severity: critical
    annotations:
      summary: "Service is down"
      description: "Service {{ $labels.instance }} is down"

  - alert: HighCPUUsage
    expr: sum(rate(container_cpu_usage_seconds_total[5m])) / sum(container_spec_replicas) > 0.8
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High CPU usage detected"
      description: "CPU usage is {{ $value }} cores on average"

  - alert: DatabaseConnectionsHigh
    expr: sum(pg_stat_database_numbackends) / sum(pg_settings_max_connections) > 0.8
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High database connections"
      description: "Database connection usage is {{ $value | humanizePercentage }}%"
EOF

    # Create SSL certificate placeholder
    cat > "$PROJECT_DIR/deployment/config/ssl/README.md" << 'EOF'
# SSL Certificates

This directory should contain:
- guideai.crt (SSL certificate)
- guideai.key (Private key)

For development, you can generate self-signed certificates:
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout guideai.key -out guideai.crt \
  -subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"
EOF

    log_success "Configuration files generated"
}

# Start scaled services
start_services() {
    log_info "Starting scaled services..."

    cd "$PROJECT_DIR"

    # Pull latest images
    log_info "Pulling latest images..."
    if podman-compose -f "$COMPOSE_FILE" pull; then
        log_success "Images pulled successfully"
    else
        log_warning "Some images could not be pulled, continuing with local images"
    fi

    # Stop existing services if running
    log_info "Stopping existing services..."
    podman-compose -f "$COMPOSE_FILE" down || true

    # Start services
    log_info "Starting all services..."
    if podman-compose -f "$COMPOSE_FILE" up -d; then
        log_success "Services started"
    else
        log_error "Failed to start services"
        show_logs
        exit 1
    fi

    # Wait for services to be healthy
    log_info "Waiting for services to be healthy..."
    sleep 30

    # Check service health
    check_service_health

    log_success "All services started successfully"
}

# Check service health
check_service_health() {
    log_info "Checking service health..."

    local max_attempts=30
    local attempt=1

    while [[ $attempt -le $max_attempts ]]; do
        log_info "Health check attempt $attempt/$max_attempts..."

        # Check API Gateway
        if curl -s http://localhost/health > /dev/null; then
            log_success "API Gateway is healthy"
            break
        fi

        # Check individual services
        local healthy_count=0
        local total_services=5

        for port in 8001 8002 8003 8004 8005; do
            if curl -s http://localhost:$port/health > /dev/null 2>&1; then
                ((healthy_count++))
            fi
        done

        log_info "Services healthy: $healthy_count/$total_services"

        if [[ $healthy_count -eq $total_services ]]; then
            log_success "All services are healthy"
            break
        fi

        if [[ $attempt -eq $max_attempts ]]; then
            log_error "Services failed to become healthy after $max_attempts attempts"
            log_info "Services that are not healthy:"
            for port in 8001 8002 8003 8004 8005; do
                if ! curl -s http://localhost:$port/health > /dev/null 2>&1; then
                    log_error "  Service on port $port is not healthy"
                fi
            done
            show_logs
            return 1
        fi

        sleep 10
        ((attempt++))
    done
}

# Show logs
show_logs() {
    log_info "Showing recent logs..."

    cd "$PROJECT_DIR"
    echo ""
    echo "=== BEHAVIOR SERVICE LOGS ==="
    podman-compose -f "$COMPOSE_FILE" logs --tail=10 behavior-service || true
    echo ""
    echo "=== ACTION SERVICE LOGS ==="
    podman-compose -f "$COMPOSE_FILE" logs --tail=10 action-service || true
    echo ""
    echo "=== RUN SERVICE LOGS ==="
    podman-compose -f "$COMPOSE_FILE" logs --tail=10 run-service || true
    echo ""
    echo "=== API GATEWAY LOGS ==="
    podman-compose -f "$COMPOSE_FILE" logs --tail=10 api-gateway || true
}

# Scale services
scale_services() {
    local service=${1:-"all"}
    local replicas=${2:-3}

    log_info "Scaling $service to $replicas replicas..."

    cd "$PROJECT_DIR"

    if [[ "$service" == "all" ]]; then
        log_info "Scaling all services..."
        podman-compose -f "$COMPOSE_FILE" up -d --scale behavior-service=$replicas
        podman-compose -f "$COMPOSE_FILE" up -d --scale action-service=$replicas
        podman-compose -f "$COMPOSE_FILE" up -d --scale run-service=$replicas
    else
        podman-compose -f "$COMPOSE_FILE" up -d --scale "$service=$replicas"
    fi

    # Wait for scaling to complete
    sleep 10

    # Verify scaling
    check_service_health
    show_service_status

    log_success "Scaling completed"
}

# Show service status
show_service_status() {
    log_info "Service status:"

    cd "$PROJECT_DIR"
    podman-compose -f "$COMPOSE_FILE" ps
}

# Stop services
stop_services() {
    log_info "Stopping all services..."

    cd "$PROJECT_DIR"
    podman-compose -f "$COMPOSE_FILE" down

    log_success "All services stopped"
}

# Clean up everything
cleanup() {
    log_warning "This will remove all containers, volumes, and networks!"
    read -p "Are you sure? [y/N]: " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Cleaning up all resources..."

        cd "$PROJECT_DIR"
        podman-compose -f "$COMPOSE_FILE" down -v --rmi all --remove-orphans

        # Clean up networks
        podman network prune -f

        # Clean up unused images
        podman image prune -f

        log_success "Cleanup completed"
    else
        log_info "Cleanup cancelled"
    fi
}

# Main function
main() {
    local command=${1:-start}

    case $command in
        "start")
            check_prerequisites
            setup_directories
            generate_configs
            start_services
            show_service_status
            ;;
        "stop")
            stop_services
            ;;
        "restart")
            stop_services
            sleep 5
            start_services
            ;;
        "status")
            show_service_status
            ;;
        "logs")
            show_logs
            ;;
        "scale")
            scale_services "$2" "$3"
            ;;
        "health")
            check_service_health
            ;;
        "cleanup")
            cleanup
            ;;
        "help"|"-h"|"--help")
            echo "Usage: $0 [command]"
            echo ""
            echo "Commands:"
            echo "  start     - Start all scaled services (default)"
            echo "  stop      - Stop all services"
            echo "  restart   - Restart all services"
            echo "  status    - Check service status"
            echo "  logs      - Show service logs"
            echo "  scale     - Scale services [service] [replicas]"
            echo "  health    - Check service health"
            echo "  cleanup   - Remove all containers and data"
            echo "  help      - Show this help"
            echo ""
            echo "Examples:"
            echo "  $0 start"
            echo "  $0 scale behavior-service 5"
            echo "  $0 scale all 3"
            ;;
        *)
            log_error "Unknown command: $command"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
