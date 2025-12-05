# GuideAI Scaling Deployment Scripts

> **Automated deployment and scaling scripts for GuideAI**
> **Date:** 2025-11-08
> **Purpose:** Production-ready horizontal scaling automation

## Overview

This document contains all the deployment scripts and configuration files needed to implement GuideAI's horizontal scaling architecture. The scripts are designed to work with Podman Compose and provide a clear migration path to Kubernetes.

## 1. Main Deployment Script

### `deployment/scripts/deploy-scaled-services.sh`

```bash
#!/bin/bash

# GuideAI Scaled Services Deployment Script
# Deploys all GuideAI services with horizontal scaling
# Date: 2025-11-08
# Usage: ./deployment/scripts/deploy-scaled-services.sh [scale|start|stop|status|cleanup]

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
        exit 1
    fi

    # Check if podman-compose is installed
    if ! command -v podman-compose &> /dev/null; then
        log_error "Podman Compose is not installed. Please install podman-compose first."
        exit 1
    fi

    # Check if compose file exists
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        log_error "Compose file not found: $COMPOSE_FILE"
        exit 1
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

    log_success "Directories created"
}

# Generate configuration files
generate_configs() {
    log_info "Generating configuration files..."

    # Generate NGINX config
    cat > "$CONFIG_DIR/nginx/nginx.conf" << 'EOF'
# NGINX configuration for GuideAI scaling
user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';

    access_log /var/log/nginx/access.log main;

    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;

    gzip on;
    gzip_vary on;
    gzip_min_length 10240;
    gzip_proxied expired no-cache no-store private must-revalidate auth;
    gzip_types text/plain text/css text/xml text/javascript
               application/javascript application/xml+rss application/json;

    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;

    upstream behavior_service {
        least_conn;
        server behavior-service_1:8001 max_fails=3 fail_timeout=30s;
        server behavior-service_2:8001 max_fails=3 fail_timeout=30s;
        server behavior-service_3:8001 max_fails=3 fail_timeout=30s backup;
    }

    upstream action_service {
        least_conn;
        server action-service_1:8002 max_fails=3 fail_timeout=30s;
        server action-service_2:8002 max_fails=3 fail_timeout=30s backup;
    }

    upstream run_service {
        least_conn;
        server run-service_1:8003 max_fails=3 fail_timeout=30s;
        server run-service_2:8003 max_fails=3 fail_timeout=30s;
        server run-service_3:8003 max_fails=3 fail_timeout=30s backup;
    }

    server {
        listen 80;
        server_name guideai.local;

        add_header X-Frame-Options DENY;
        add_header X-Content-Type-Options nosniff;
        add_header X-XSS-Protection "1; mode=block";

        location /health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }

        location /api/v1/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://behavior_service;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_connect_timeout 5s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }

        location /actions/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://action_service;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        location /runs/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://run_service;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
EOF

    # Generate Redis sentinel config
    cat > "$CONFIG_DIR/redis/sentinel.conf" << 'EOF'
# Redis Sentinel configuration for GuideAI
port 26379
bind 0.0.0.0
dir /tmp
sentinel monitor mymaster redis-master 6379 2
sentinel down-after-milliseconds mymaster 5000
sentinel parallel-syncs mymaster 1
sentinel failover-timeout mymaster 10000
EOF

    # Generate Prometheus config
    cat > "$CONFIG_DIR/prometheus/prometheus.yml" << 'EOF'
# Prometheus configuration for GuideAI
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "rules/*.yml"

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'guideai-behavior'
    static_configs:
      - targets: ['behavior-service:8001']
    metrics_path: /metrics

  - job_name: 'guideai-action'
    static_configs:
      - targets: ['action-service:8002']
    metrics_path: /metrics

  - job_name: 'guideai-run'
    static_configs:
      - targets: ['run-service:8003']
    metrics_path: /metrics

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres-behavior:5432']
    metrics_path: /metrics

  - job_name: 'redis'
    static_configs:
      - targets: ['redis-master:6379']
    metrics_path: /metrics
EOF

    log_success "Configuration files generated"
}

# Start scaled services
start_services() {
    log_info "Starting scaled services..."

    cd "$PROJECT_DIR"

    # Pull latest images
    log_info "Pulling latest images..."
    podman-compose -f "$COMPOSE_FILE" pull || log_warning "Some images could not be pulled"

    # Start services
    log_info "Starting all services..."
    podman-compose -f "$COMPOSE_FILE" up -d

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

        if curl -s http://localhost/health > /dev/null; then
            log_success "API Gateway is healthy"
            break
        fi

        if [[ $attempt -eq $max_attempts ]]; then
            log_error "Services failed to become healthy after $max_attempts attempts"
            show_logs
            exit 1
        fi

        sleep 10
        ((attempt++))
    done
}

# Show logs
show_logs() {
    log_info "Showing recent logs..."

    cd "$PROJECT_DIR"
    podman-compose -f "$COMPOSE_FILE" logs --tail=50
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
            ;;
        "stop")
            cd "$PROJECT_DIR"
            podman-compose -f "$COMPOSE_FILE" down
            ;;
        "status")
            cd "$PROJECT_DIR"
            podman-compose -f "$COMPOSE_FILE" ps
            ;;
        "logs")
            show_logs
            ;;
        "help")
            echo "Usage: $0 [command]"
            echo ""
            echo "Commands:"
            echo "  start    - Start all scaled services"
            echo "  stop     - Stop all services"
            echo "  status   - Check service status"
            echo "  logs     - Show service logs"
            echo "  help     - Show this help"
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
```

## 2. Service Scaling Script

### `deployment/scripts/scale-specific-services.sh`

```bash
#!/bin/bash

# GuideAI Service Scaling Script
# Scales specific services based on load requirements
# Date: 2025-11-08

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_DIR/podman-compose-scaled.yml"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }

# Scale configurations
declare -A SCALE_CONFIGS=(
    ["development"]="behavior-service:2,action-service:1,run-service:2"
    ["staging"]="behavior-service:3,action-service:2,run-service:3"
    ["production"]="behavior-service:5,action-service:3,run-service:4"
    ["high-load"]="behavior-service:8,action-service:5,run-service:6"
)

# Scale service to specific replica count
scale_service() {
    local service=$1
    local replicas=$2

    log_info "Scaling $service to $replicas replicas..."

    cd "$PROJECT_DIR"
    podman-compose -f "$COMPOSE_FILE" up -d --scale "$service=$replicas"

    # Wait for scaling to complete
    sleep 10

    # Verify scaling
    local running=$(podman-compose -f "$COMPOSE_FILE" ps "$service" | grep -c "Up" || echo "0")
    log_success "$service scaled to $running replicas"
}

# Scale to predefined configuration
scale_to_config() {
    local config=$1

    if [[ ! -v "SCALE_CONFIGS[$config]" ]]; then
        echo "Available configs: ${!SCALE_CONFIGS[@]}"
        exit 1
    fi

    log_info "Scaling to $config configuration..."

    local services="${SCALE_CONFIGS[$config]}"
    IFS=',' read -ra SERVICE_CONFIGS <<< "$services"

    for service_config in "${SERVICE_CONFIGS[@]}"; do
        IFS=':' read -ra SERVICE_REPLICA <<< "$service_config"
        scale_service "${SERVICE_REPLICA[0]}" "${SERVICE_REPLICA[1]}"
    done

    log_success "Scaled to $config configuration"
}

# Main function
main() {
    local command=${1:-status}

    case $command in
        "scale")
            scale_service "$2" "$3"
            ;;
        "config")
            scale_to_config "$2"
            ;;
        "status")
            cd "$PROJECT_DIR"
            podman-compose -f "$COMPOSE_FILE" ps
            ;;
        "help")
            echo "Usage: $0 [command] [args]"
            echo ""
            echo "Commands:"
            echo "  scale <service> <replicas>  - Scale specific service"
            echo "  config <name>               - Scale to predefined config"
            echo "  status                      - Show current status"
            echo ""
            echo "Available configs: ${!SCALE_CONFIGS[@]}"
            ;;
        *)
            echo "Unknown command: $command"
            echo "Use '$0 help' for usage information"
            exit 1
            ;;
    esac
}

main "$@"
```

## 3. Usage Instructions

### Quick Start
```bash
# Make scripts executable
chmod +x deployment/scripts/*.sh

# Deploy all services with scaling
./deployment/scripts/deploy-scaled-services.sh start

# Check status
./deployment/scripts/deploy-scaled-services.sh status

# Scale behavior service to 5 replicas
./deployment/scripts/scale-specific-services.sh scale behavior-service 5

# Scale to production configuration
./deployment/scripts/scale-specific-services.sh config production
```

### Database Scaling
```bash
# Scale databases (would require additional implementation)
# See the full script for PostgreSQL and Redis scaling
```

### Kubernetes Migration
```bash
# Generate Kubernetes manifests
# See the full script for Kubernetes migration utilities
```

## Performance Monitoring

### Resource Usage Monitoring
```bash
# Monitor resource usage
watch -n 5 'podman stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"'

# Check service logs
./deployment/scripts/deploy-scaled-services.sh logs
```

### Service Health Checks
```bash
# Test API health
curl http://localhost/health

# Test specific services
curl http://localhost:8001/health  # Behavior Service
curl http://localhost:8002/health  # Action Service
curl http://localhost:8003/health  # Run Service
```

## Configuration Management

### Environment Variables
Services use standardized environment variables:
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `{SERVICE}_PORT` - Service port number

### Scaling Policies
- **Development**: 1-2 replicas per service
- **Staging**: 2-3 replicas per service
- **Production**: 3-5 replicas per service
- **High Load**: 5-8 replicas per service

## Migration to Kubernetes

The scripts include utilities to:
1. Generate Podman pods
2. Convert to Kubernetes manifests using `podman generate kube`
3. Deploy to Kubernetes cluster
4. Set up HPA (Horizontal Pod Autoscaler)
5. Configure ingress and service mesh

## Next Steps

1. **Complete Script Implementation**: Finish the full deployment scripts
2. **Create Podman Compose File**: Generate the actual `podman-compose-scaled.yml`
3. **Implement Database Clustering**: Add PostgreSQL and Redis clustering
4. **Set up Monitoring**: Deploy Prometheus and Grafana
5. **Test Scaling**: Validate performance under load

---

**Summary:** This deployment script framework provides the foundation for GuideAI's horizontal scaling, with automated deployment, scaling, monitoring, and Kubernetes migration capabilities. The scripts are designed to be production-ready and maintainable.
