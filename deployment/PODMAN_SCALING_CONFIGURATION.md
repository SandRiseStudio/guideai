# GuideAI Podman Compose Scaling Configuration

> **Production-ready horizontal scaling with Podman-first approach**
> **Date:** 2025-11-08
> **Phase:** 1 - Local Scaling Implementation

## Overview

This document provides the complete Podman Compose configuration for scaling GuideAI services horizontally. The configuration supports scaling individual services, manages inter-service communication, and provides a clear migration path to Kubernetes.

## Core Scaling Architecture

### Service Pod Architecture
Each service is deployed in its own Podman pod with the following pattern:

- **API Gateway Pod**: NGINX proxy with SSL termination and rate limiting
- **Service Pods**: Individual service containers (behavior, action, run, etc.)
- **Database Pods**: PostgreSQL cluster with TimescaleDB and streaming replication
- **Cache Pods**: Redis Sentinel for high availability
- **Messaging Pods**: Kafka cluster for event streaming

### Scaling Strategy
- **Horizontal Scaling**: Replica-based scaling for stateless services
- **Database Scaling**: Read replicas for read-heavy workloads
- **Caching**: Redis cluster for distributed caching
- **Load Balancing**: NGINX upstream configuration

### NGINX templating safeguards
- The API gateway container renders `/etc/nginx/nginx.conf` through `deployment/scripts/nginx-entrypoint.sh`, ensuring only the variables listed in `NGINX_TEMPLATE_VARS` are substituted before nginx starts.
- For scaled deployments we currently pass an empty `NGINX_TEMPLATE_VARS` value, which makes the script copy the template verbatim while still guarding `$http_*` directives from accidental `envsubst` expansion.
- When pointing the gateway at alternate upstreams, set `NGINX_TEMPLATE_VARS` plus the corresponding environment variables and inspect `/etc/nginx/nginx.conf` via `podman exec guideai-api-gateway cat /etc/nginx/nginx.conf` if requests fail.

## Podman Compose Configuration Files

### 1. Main Scaling Configuration
**File:** `deployment/podman-compose-scaled.yml`

```yaml
# GuideAI Production-Ready Podman Compose Configuration
# Supports horizontal scaling with resource limits and health checks
# Date: 2025-11-08

version: '3.8'

networks:
  guideai-internal:
    driver: bridge
    ipam:
      config:
        - subnet: 172.25.0.0/16
  guideai-database:
    driver: bridge
    ipam:
      config:
        - subnet: 172.26.0.0/16
  guideai-cache:
    driver: bridge
    ipam:
      config:
        - subnet: 172.27.0.0/16

volumes:
  postgres-telemetry-data:
    driver: local
  postgres-behavior-data:
    driver: local
  postgres-action-data:
    driver: local
  postgres-run-data:
    driver: local
  postgres-compliance-data:
    driver: local
  redis-data:
    driver: local
  kafka-data:
    driver: local
  nginx-data:
    driver: local

services:
  # ===================================================================
  # API Gateway - Load Balancer and Rate Limiting
  # ===================================================================
  api-gateway:
    image: nginx:alpine
    container_name: guideai-api-gateway
    networks:
      - guideai-internal
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./config/nginx/nginx.conf:/etc/nginx/nginx.conf.template:ro
      - ./scripts/nginx-entrypoint.sh:/etc/nginx/start-guideai.sh:ro
      - ./config/nginx/conf.d:/etc/nginx/conf.d:ro
      - ./config/ssl:/etc/nginx/ssl:ro
      - nginx-data:/var/cache/nginx
    environment:
      - NGINX_HOST=guideai.local
      - NGINX_PORT=80
      - NGINX_TEMPLATE_VARS=
    command: ["/bin/sh", "/etc/nginx/start-guideai.sh"]
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    deploy:
      replicas: 1
      resources:
        limits:
          cpus: '1'
          memory: 1G
        reservations:
          cpus: '0.5'
          memory: 512M

  # ===================================================================
  # Behavior Service - Multi-Replica Scaling
  # ===================================================================
  behavior-service:
    image: ghcr.io/nas4146/guideai-behavior:latest
    container_name: guideai-behavior-service
    networks:
      - guideai-internal
    environment:
      - DATABASE_URL=postgresql://guideai_behavior:dev_behavior_pass@postgres-behavior:5432/behaviors
      - REDIS_URL=redis://redis:6379/0
      - BEHAVIOR_SERVICE_PORT=8001
    volumes:
      - ./data/behaviors:/app/data
    depends_on:
      postgres-behavior:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    scale: 3  # Default replica count
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '1'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 1G

  # ===================================================================
  # Action Service - Scalable Action Processing
  # ===================================================================
  action-service:
    image: ghcr.io/nas4146/guideai-action:latest
    container_name: guideai-action-service
    networks:
      - guideai-internal
    environment:
      - DATABASE_URL=postgresql://guideai_user:local_dev_pw@postgres-action:5432/guideai_action
      - REDIS_URL=redis://redis:6379/1
      - ACTION_SERVICE_PORT=8002
    volumes:
      - ./data/actions:/app/data
    depends_on:
      postgres-action:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:8002/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    scale: 2  # Default replica count
    deploy:
      replicas: 2
      resources:
        limits:
          cpus: '0.5'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 512M

  # ===================================================================
  # Run Service - Orchestration and State Management
  # ===================================================================
  run-service:
    image: ghcr.io/nas4146/guideai-run:latest
    container_name: guideai-run-service
    networks:
      - guideai-internal
    environment:
      - DATABASE_URL=postgresql://guideai_user:local_dev_pw@postgres-run:5432/guideai_run
      - REDIS_URL=redis://redis:6379/2
      - KAFKA_BOOTSTRAP_SERVERS=kafka-1:9092,kafka-2:9093,kafka-3:9094
      - RUN_SERVICE_PORT=8003
    volumes:
      - ./data/runs:/app/data
    depends_on:
      postgres-run:
        condition: service_healthy
      redis:
        condition: service_healthy
      kafka-1:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:8003/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    scale: 3  # Default replica count
    deploy:
      replicas: 3
      resources:
        limits:
          cpus: '1'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 1G

  # ===================================================================
  # Compliance Service - Audit and Governance
  # ===================================================================
  compliance-service:
    image: ghcr.io/nas4146/guideai-compliance:latest
    container_name: guideai-compliance-service
    networks:
      - guideai-internal
    environment:
      - DATABASE_URL=postgresql://guideai_user:local_dev_pw@postgres-compliance:5432/guideai_compliance
      - REDIS_URL=redis://redis:6379/3
      - COMPLIANCE_SERVICE_PORT=8004
    volumes:
      - ./data/compliance:/app/data
      - ./data/audit-logs:/app/audit-logs
    depends_on:
      postgres-compliance:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:8004/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    scale: 1  # Default replica count (high availability, not high load)
    deploy:
      replicas: 1
      resources:
        limits:
          cpus: '0.5'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 512M

  # ===================================================================
  # Agent Orchestrator Service - Multi-Agent Coordination
  # ===================================================================
  agent-orchestrator:
    image: ghcr.io/nas4146/guideai-agent-orchestrator:latest
    container_name: guideai-agent-orchestrator
    networks:
      - guideai-internal
    environment:
      - DATABASE_URL=postgresql://guideai_user:local_dev_pw@postgres-agent-orchestrator:5432/guideai_agent_orchestrator
      - REDIS_URL=redis://redis:6379/4
      - ORCHESTRATOR_PORT=8005
    volumes:
      - ./data/orchestrator:/app/data
    depends_on:
      postgres-agent-orchestrator:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:8005/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    restart: unless-stopped
    scale: 2  # Default replica count
    deploy:
      replicas: 2
      resources:
        limits:
          cpus: '0.5'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 512M

  # ===================================================================
  # Database Layer - PostgreSQL Cluster
  # ===================================================================

  postgres-telemetry:
    image: timescale/timescaledb:latest-pg16
    container_name: guideai-postgres-telemetry
    networks:
      - guideai-database
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_DB=telemetry
      - POSTGRES_USER=guideai_telemetry
      - POSTGRES_PASSWORD=dev_telemetry_pass
      - POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C
    command:
      - postgres
      - -c
      - log_min_duration_statement=1000
      - -c
      - shared_preload_libraries=timescaledb
      - -c
      - max_connections=200
      - -c
      - shared_buffers=256MB
      - -c
      - effective_cache_size=1GB
    volumes:
      - postgres-telemetry-data:/var/lib/postgresql/data
      - ./schema/migrations:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U guideai_telemetry -d telemetry"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    deploy:
      replicas: 1
      resources:
        limits:
          cpus: '2'
          memory: 4G
        reservations:
          cpus: '1'
          memory: 2G

  postgres-telemetry-replica-1:
    image: timescale/timescaledb:latest-pg16
    container_name: guideai-postgres-telemetry-replica-1
    networks:
      - guideai-database
    environment:
      - POSTGRES_DB=telemetry
      - POSTGRES_USER=guideai_telemetry
      - POSTGRES_PASSWORD=dev_telemetry_pass
      - POSTGRES_MASTER_SERVICE=postgres-telemetry
      - POSTGRES_REPLICA_MODE=slave
    command:
      - postgres
      - -c
      - hot_standby=on
      - -c
      - max_connections=150
      - -c
      - shared_buffers=256MB
    volumes:
      - postgres-telemetry-data-replica-1:/var/lib/postgresql/data
    depends_on:
      postgres-telemetry:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U guideai_telemetry -d telemetry"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    deploy:
      replicas: 1
      resources:
        limits:
          cpus: '1'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 1G

  # Additional database instances for other services (behavior, action, run, compliance, orchestrator)
  postgres-behavior:
    image: pgvector/pgvector:pg16
    container_name: guideai-postgres-behavior
    networks:
      - guideai-database
    ports:
      - "5433:5432"
    environment:
      - POSTGRES_DB=behaviors
      - POSTGRES_USER=guideai_behavior
      - POSTGRES_PASSWORD=dev_behavior_pass
      - POSTGRES_INITDB_ARGS=--encoding=UTF8 --locale=C
    command:
      - postgres
      - -c
      - log_min_duration_statement=1000
      - -c
      - max_connections=100
    volumes:
      - postgres-behavior-data:/var/lib/postgresql/data
      - ./schema/migrations:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U guideai_behavior -d behaviors"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 1G

  postgres-action:
    image: postgres:16-alpine
    container_name: guideai-postgres-action
    networks:
      - guideai-database
    ports:
      - "5434:5432"
    environment:
      - POSTGRES_DB=guideai_action
      - POSTGRES_USER=guideai_user
      - POSTGRES_PASSWORD=local_dev_pw
    command:
      - postgres
      - -c
      - log_min_duration_statement=1000
      - -c
      - max_connections=100
    volumes:
      - postgres-action-data:/var/lib/postgresql/data
      - ./schema/migrations:/docker-entrypoint-initdb.d:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U guideai_user -d guideai_action"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 1G

  # ===================================================================
  # Cache Layer - Redis for High Availability
  # ===================================================================

  redis-master:
    image: redis:7-alpine
    container_name: guideai-redis-master
    networks:
      - guideai-cache
    ports:
      - "6379:6379"
    command:
      - redis-server
      - --maxmemory
      - "1gb"
      - --maxmemory-policy
      - "allkeys-lru"
      - --save
      - "60 1"
      - --appendonly
      - "yes"
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 1G

  redis-replica-1:
    image: redis:7-alpine
    container_name: guideai-redis-replica-1
    networks:
      - guideai-cache
    environment:
      - REDIS_MASTER=redis-master
    command:
      - redis-server
      - --replicaof
      - redis-master
      - 6379
      - --maxmemory
      - "1gb"
      - --maxmemory-policy
      - "allkeys-lru"
    volumes:
      - redis-data-replica-1:/data
    depends_on:
      - redis-master
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 512M

  # ===================================================================
  # Monitoring and Observability
  # ===================================================================

  prometheus:
    image: prom/prometheus:latest
    container_name: guideai-prometheus
    networks:
      - guideai-internal
    ports:
      - "9090:9090"
    volumes:
      - ./config/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./config/prometheus/rules:/etc/prometheus/rules:ro
      - prometheus-data:/prometheus
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --web.console.libraries=/etc/prometheus/console_libraries
      - --web.console.templates=/etc/prometheus/consoles
      - --web.enable-lifecycle
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '1'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 1G

  grafana:
    image: grafana/grafana:latest
    container_name: guideai-grafana
    networks:
      - guideai-internal
    ports:
      - "3001:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin123
      - GF_USERS_ALLOW_SIGN_UP=false
    volumes:
      - grafana-data:/var/lib/grafana
      - ./config/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
      - ./config/grafana/datasources:/etc/grafana/provisioning/datasources:ro
    depends_on:
      - prometheus
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 1G
        reservations:
          cpus: '0.25'
          memory: 512M

# Additional volumes for monitoring
volumes:
  prometheus-data:
    driver: local
  grafana-data:
    driver: local
```

### 2. NGINX Configuration for Load Balancing
**File:** `deployment/config/nginx/nginx.conf`

```nginx
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

    # Logging format
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';

    access_log /var/log/nginx/access.log main;

    # Performance tuning
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 10240;
    gzip_proxied expired no-cache no-store private must-revalidate auth;
    gzip_types
        text/plain
        text/css
        text/xml
        text/javascript
        application/javascript
        application/xml+rss
        application/json;

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req_zone $binary_remote_addr zone=login:10m rate=1r/s;

    # Upstream configurations
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

    # Health check endpoint
    server {
        listen 80;
        server_name guideai.local;

        location /health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }
    }

    # Main server configuration
    server {
        listen 80;
        server_name guideai.local;

        # Security headers
        add_header X-Frame-Options DENY;
        add_header X-Content-Type-Options nosniff;
        add_header X-XSS-Protection "1; mode=block";
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

        # API rate limiting
        location /api/v1/ {
            limit_req zone=api burst=20 nodelay;
            proxy_pass http://behavior_service;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Timeouts
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

        # Health checks
        location /health {
            access_log off;
            return 200 "healthy\n";
            add_header Content-Type text/plain;
        }
    }
}
```

## Usage Instructions

### 1. Start Scaled Services
```bash
# Start all services with default scaling
cd /Users/nick/guideai
podman-compose -f deployment/podman-compose-scaled.yml up -d

# Scale specific services
podman-compose -f deployment/podman-compose-scaled.yml up -d --scale behavior-service=5
podman-compose -f deployment/podman-compose-scaled.yml up -d --scale run-service=4

# View running services
podman-compose -f deployment/podman-compose-scaled.yml ps
```

### 2. Monitor Scaling
```bash
# Check service health
curl http://localhost/health

# View logs for specific service
podman-compose -f deployment/podman-compose-scaled.yml logs -f behavior-service

# Monitor resource usage
podman stats
```

### 3. Scale Up/Down
```bash
# Scale up behavior service
podman-compose -f deployment/podman-compose-scaled.yml up -d --scale behavior-service=5

# Scale down
podman-compose -f deployment/podman-compose-scaled.yml up -d --scale behavior-service=2

# Scale all services
podman-compose -f deployment/podman-compose-scaled.yml up -d --scale behavior-service=3 --scale action-service=2
```

### 4. Database Scaling
```bash
# Add read replica
podman-compose -f deployment/podman-compose-scaled.yml up -d postgres-telemetry-replica-3

# Scale Redis replicas
podman-compose -f deployment/podman-compose-scaled.yml up -d --scale redis-replica-1=2
```

## Performance Validation

### Load Testing Commands
```bash
# Test API load
curl -H "Content-Type: application/json" \
     -X POST http://localhost/api/v1/behaviors/search \
     -d '{"query": "behavior_test", "limit": 10}'

# Benchmark with wrk
wrk -t4 -c100 -d30s --script=load_test.lua http://localhost/api/v1/behaviors/health
```

### Resource Monitoring
```bash
# Monitor resource usage per container
podman top $(podman ps -q)

# Check scaling efficiency
watch -n 5 'podman stats --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}"'
```

## Migration to Kubernetes

### Generate K8s Manifests
```bash
# Create podman pods for services
podman pod create --name guideai-behavior-pod --infra=false -p 8001:8001
podman run -d --pod guideai-behavior-pod --name behavior-api ghcr.io/nas4146/guideai-behavior:latest

# Generate K8s manifests
podman generate kube guideai-behavior-pod > k8s/behavior-service.yaml
kubectl apply -f k8s/behavior-service.yaml

# Scale in Kubernetes
kubectl scale deployment behavior-service --replicas=5
```

## Cost Optimization

### Resource Allocation Guidelines
- **API Gateway**: 1 replica, 1 CPU, 1GB RAM
- **Core Services**: 2-3 replicas, 0.5-1 CPU, 1-2GB RAM each
- **Database**: 1 master + 2 replicas, 1-2 CPU, 2-4GB RAM each
- **Cache**: 1 master + 2 replicas, 0.5-1 CPU, 1-2GB RAM each
- **Monitoring**: 1 replica each, minimal resource usage

### Expected Costs (AWS)
- **Development**: $300-500/month
- **Staging**: $800-1,200/month
- **Production**: $2,000-3,500/month

---

**Summary:** This Podman Compose configuration provides a production-ready foundation for horizontal scaling, with clear upgrade paths to Kubernetes and comprehensive monitoring. The configuration maintains consistency with GuideAI's existing Podman standardization while providing enterprise-grade scaling capabilities.
