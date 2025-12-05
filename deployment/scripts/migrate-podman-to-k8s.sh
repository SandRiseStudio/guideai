#!/bin/bash

# GuideAI Podman to Kubernetes Migration Script
# Migrates Podman-based scaling to Kubernetes with HPA
# Date: 2025-11-08
# Usage: ./deployment/scripts/migrate-podman-to-k8s.sh [generate|deploy|destroy|status]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
K8S_DIR="$PROJECT_DIR/k8s"
COMPOSE_FILE="$PROJECT_DIR/podman-compose-scaled.yml"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check prerequisites
check_prerequisites() {
    log_info "Checking Kubernetes migration prerequisites..."

    # Check if kubectl is installed
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is not installed. Please install kubectl first."
        exit 1
    fi

    # Check if cluster is accessible
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster. Please check your kubeconfig."
        exit 1
    fi

    # Check if podman is available for manifest generation
    if ! command -v podman &> /dev/null; then
        log_warning "Podman is not available. Will create manifests manually."
    fi

    log_success "Prerequisites check passed"
}

# Create K8s directory structure
setup_k8s_directories() {
    log_info "Setting up Kubernetes directory structure..."

    mkdir -p "$K8S_DIR"/{deployments,services,configmaps,secrets,ingress,hpa}

    log_success "Kubernetes directories created"
}

# Generate Kubernetes manifests from Podman pods
generate_manifests_from_podman() {
    log_info "Generating Kubernetes manifests from Podman..."

    if ! command -v podman &> /dev/null; then
        log_warning "Podman not available, creating manifests manually..."
        create_manifests_manually
        return
    fi

    # Start Podman services if not running
    if ! podman-compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
        log_info "Starting Podman services for manifest generation..."
        podman-compose -f "$COMPOSE_FILE" up -d
        sleep 30
    fi

    # Generate manifests for each service
    local services=("behavior-service" "action-service" "run-service" "compliance-service" "agent-orchestrator")

    for service in "${services[@]}"; do
        log_info "Generating manifest for $service..."

        # Create a temporary pod for service
        local pod_name="${service}-temp"
        podman pod rm -f "$pod_name" 2>/dev/null || true

        podman pod create \
            --name "$pod_name" \
            --infra=false \
            -p 8001:8001 2>/dev/null || true

        # Generate Kubernetes manifest
        podman generate kube "$pod_name" > "$K8S_DIR/deployments/${service}.yaml" || true

        # Clean up
        podman pod rm -f "$pod_name" 2>/dev/null || true
    done

    log_success "Podman-based manifest generation completed"
}

# Create Kubernetes manifests manually
create_manifests_manually() {
    log_info "Creating Kubernetes manifests manually..."

    # Create namespace
    cat > "$K8S_DIR/namespace.yaml" << 'EOF'
apiVersion: v1
kind: Namespace
metadata:
  name: guideai-scaling
  labels:
    name: guideai-scaling
EOF

    # Behavior Service Deployment
    cat > "$K8S_DIR/deployments/behavior-service.yaml" << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: behavior-service
  namespace: guideai-scaling
  labels:
    app: behavior-service
    version: v1
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: behavior-service
  template:
    metadata:
      labels:
        app: behavior-service
        version: v1
    spec:
      containers:
      - name: behavior-service
        image: localhost/guideai-behavior:latest
        ports:
        - containerPort: 8001
        env:
        - name: BEHAVIOR_SERVICE_PORT
          value: "8001"
        - name: DATABASE_URL
          value: "postgresql://guideai_user:local_dev_pw@postgres-behavior:5432/behaviors"
        - name: REDIS_URL
          value: "redis://redis:6379/0"
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 1
            memory: 2Gi
        livenessProbe:
          httpGet:
            path: /health
            port: 8001
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8001
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: behavior-service
  namespace: guideai-scaling
  labels:
    app: behavior-service
spec:
  type: ClusterIP
  ports:
  - port: 8001
    targetPort: 8001
    protocol: TCP
  selector:
    app: behavior-service
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: behavior-service-hpa
  namespace: guideai-scaling
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: behavior-service
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
EOF

    # Action Service Deployment
    cat > "$K8S_DIR/deployments/action-service.yaml" << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: action-service
  namespace: guideai-scaling
  labels:
    app: action-service
    version: v1
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: action-service
  template:
    metadata:
      labels:
        app: action-service
        version: v1
    spec:
      containers:
      - name: action-service
        image: localhost/guideai-action:latest
        ports:
        - containerPort: 8002
        env:
        - name: ACTION_SERVICE_PORT
          value: "8002"
        - name: DATABASE_URL
          value: "postgresql://guideai_user:local_dev_pw@postgres-action:5432/guideai_action"
        - name: REDIS_URL
          value: "redis://redis:6379/1"
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 500m
            memory: 1Gi
        livenessProbe:
          httpGet:
            path: /health
            port: 8002
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8002
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: action-service
  namespace: guideai-scaling
  labels:
    app: action-service
spec:
  type: ClusterIP
  ports:
  - port: 8002
    targetPort: 8002
    protocol: TCP
  selector:
    app: action-service
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: action-service-hpa
  namespace: guideai-scaling
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: action-service
  minReplicas: 2
  maxReplicas: 6
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
EOF

    # Run Service Deployment
    cat > "$K8S_DIR/deployments/run-service.yaml" << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: run-service
  namespace: guideai-scaling
  labels:
    app: run-service
    version: v1
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: run-service
  template:
    metadata:
      labels:
        app: run-service
        version: v1
    spec:
      containers:
      - name: run-service
        image: localhost/guideai-run:latest
        ports:
        - containerPort: 8003
        env:
        - name: RUN_SERVICE_PORT
          value: "8003"
        - name: DATABASE_URL
          value: "postgresql://guideai_user:local_dev_pw@postgres-run:5432/guideai_run"
        - name: REDIS_URL
          value: "redis://redis:6379/2"
        - name: KAFKA_BOOTSTRAP_SERVERS
          value: "kafka:9092"
        resources:
          requests:
            cpu: 500m
            memory: 1Gi
          limits:
            cpu: 1
            memory: 2Gi
        livenessProbe:
          httpGet:
            path: /health
            port: 8003
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8003
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: run-service
  namespace: guideai-scaling
  labels:
    app: run-service
spec:
  type: ClusterIP
  ports:
  - port: 8003
    targetPort: 8003
    protocol: TCP
  selector:
    app: run-service
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: run-service-hpa
  namespace: guideai-scaling
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: run-service
  minReplicas: 3
  maxReplicas: 8
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
EOF

    # Compliance Service Deployment
    cat > "$K8S_DIR/deployments/compliance-service.yaml" << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: compliance-service
  namespace: guideai-scaling
  labels:
    app: compliance-service
    version: v1
spec:
  replicas: 1
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: compliance-service
  template:
    metadata:
      labels:
        app: compliance-service
        version: v1
    spec:
      containers:
      - name: compliance-service
        image: localhost/guideai-compliance:latest
        ports:
        - containerPort: 8004
        env:
        - name: COMPLIANCE_SERVICE_PORT
          value: "8004"
        - name: DATABASE_URL
          value: "postgresql://guideai_user:local_dev_pw@postgres-compliance:5432/guideai_compliance"
        - name: REDIS_URL
          value: "redis://redis:6379/3"
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 500m
            memory: 1Gi
        livenessProbe:
          httpGet:
            path: /health
            port: 8004
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8004
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: compliance-service
  namespace: guideai-scaling
  labels:
    app: compliance-service
spec:
  type: ClusterIP
  ports:
  - port: 8004
    targetPort: 8004
    protocol: TCP
  selector:
    app: compliance-service
EOF

    # Agent Orchestrator Deployment
    cat > "$K8S_DIR/deployments/agent-orchestrator.yaml" << 'EOF'
apiVersion: apps/v1
kind: Deployment
metadata:
  name: agent-orchestrator
  namespace: guideai-scaling
  labels:
    app: agent-orchestrator
    version: v1
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels:
      app: agent-orchestrator
  template:
    metadata:
      labels:
        app: agent-orchestrator
        version: v1
    spec:
      containers:
      - name: agent-orchestrator
        image: localhost/guideai-agent-orchestrator:latest
        ports:
        - containerPort: 8005
        env:
        - name: ORCHESTRATOR_PORT
          value: "8005"
        - name: DATABASE_URL
          value: "postgresql://guideai_user:local_dev_pw@postgres-orchestrator:5432/guideai_agent_orchestrator"
        - name: REDIS_URL
          value: "redis://redis:6379/4"
        resources:
          requests:
            cpu: 250m
            memory: 512Mi
          limits:
            cpu: 500m
            memory: 1Gi
        livenessProbe:
          httpGet:
            path: /health
            port: 8005
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health
            port: 8005
          initialDelaySeconds: 5
          periodSeconds: 5
---
apiVersion: v1
kind: Service
metadata:
  name: agent-orchestrator
  namespace: guideai-scaling
  labels:
    app: agent-orchestrator
spec:
  type: ClusterIP
  ports:
  - port: 8005
    targetPort: 8005
    protocol: TCP
  selector:
    app: agent-orchestrator
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: agent-orchestrator-hpa
  namespace: guideai-scaling
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: agent-orchestrator
  minReplicas: 2
  maxReplicas: 5
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
EOF

    # Create ingress for external access
    cat > "$K8S_DIR/ingress/guideai-ingress.yaml" << 'EOF'
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: guideai-ingress
  namespace: guideai-scaling
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/proxy-body-size: "10m"
    nginx.ingress.kubernetes.io/proxy-read-timeout: "300"
    nginx.ingress.kubernetes.io/proxy-send-timeout: "300"
spec:
  tls:
  - hosts:
    - guideai.local
    secretName: guideai-tls
  rules:
  - host: guideai.local
    http:
      paths:
      - path: /api/v1
        pathType: Prefix
        backend:
          service:
            name: behavior-service
            port:
              number: 8001
      - path: /actions
        pathType: Prefix
        backend:
          service:
            name: action-service
            port:
              number: 8002
      - path: /runs
        pathType: Prefix
        backend:
          service:
            name: run-service
            port:
              number: 8003
      - path: /compliance
        pathType: Prefix
        backend:
          service:
            name: compliance-service
            port:
              number: 8004
      - path: /orchestrator
        pathType: Prefix
        backend:
          service:
            name: agent-orchestrator
            port:
              number: 8005
EOF

    log_success "Manual manifest creation completed"
}

# Deploy to Kubernetes
deploy_to_k8s() {
    log_info "Deploying GuideAI to Kubernetes..."

    # Apply namespace
    kubectl apply -f "$K8S_DIR/namespace.yaml"

    # Apply all deployments
    kubectl apply -f "$K8S_DIR/deployments/"

    # Apply services
    kubectl apply -f "$K8S_DIR/deployments/" -f "$K8S_DIR/services/" || true

    # Apply HPA
    kubectl apply -f "$K8S_DIR/hpa/" || true

    # Apply ingress (if ingress controller is available)
    if kubectl get namespace ingress-nginx &> /dev/null; then
        kubectl apply -f "$K8S_DIR/ingress/"
    else
        log_warning "Ingress controller not found. Skipping ingress deployment."
        log_info "To enable ingress, install nginx-ingress controller:"
        log_info "kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.8.1/deploy/static/provider/cloud/deploy.yaml"
    fi

    # Wait for deployments to be ready
    log_info "Waiting for deployments to be ready..."
    sleep 30

    # Check deployment status
    kubectl get deployments -n guideai-scaling
    kubectl get pods -n guideai-scaling
    kubectl get services -n guideai-scaling
    kubectl get hpa -n guideai-scaling

    log_success "Deployment to Kubernetes completed"
}

# Check status in Kubernetes
check_k8s_status() {
    log_info "Checking Kubernetes deployment status..."

    echo "=== NAMESPACES ==="
    kubectl get namespaces | grep guideai || echo "No guideai namespaces found"

    echo ""
    echo "=== DEPLOYMENTS ==="
    kubectl get deployments -n guideai-scaling 2>/dev/null || echo "No deployments in guideai-scaling namespace"

    echo ""
    echo "=== PODS ==="
    kubectl get pods -n guideai-scaling 2>/dev/null || echo "No pods in guideai-scaling namespace"

    echo ""
    echo "=== SERVICES ==="
    kubectl get services -n guideai-scaling 2>/dev/null || echo "No services in guideai-scaling namespace"

    echo ""
    echo "=== HPA ==="
    kubectl get hpa -n guideai-scaling 2>/dev/null || echo "No HPA in guideai-scaling namespace"

    echo ""
    echo "=== INGRESS ==="
    kubectl get ingress -n guideai-scaling 2>/dev/null || echo "No ingress in guideai-scaling namespace"
}

# Destroy Kubernetes deployment
destroy_k8s() {
    log_warning "This will remove all GuideAI resources from Kubernetes!"
    read -p "Are you sure? [y/N]: " -n 1 -r
    echo

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        log_info "Destroying GuideAI from Kubernetes..."

        # Delete all resources
        kubectl delete -f "$K8S_DIR/ingress/" --ignore-not-found=true
        kubectl delete -f "$K8S_DIR/hpa/" --ignore-not-found=true
        kubectl delete -f "$K8S_DIR/deployments/" --ignore-not-found=true
        kubectl delete -f "$K8S_DIR/services/" --ignore-not-found=true
        kubectl delete -f "$K8S_DIR/namespace.yaml" --ignore-not-found=true

        # Clean up any remaining resources
        kubectl delete deployment,service,hpa,ingress -n guideai-scaling --all --ignore-not-found=true

        log_success "Kubernetes deployment destroyed"
    else
        log_info "Destruction cancelled"
    fi
}

# Show performance metrics
show_k8s_performance() {
    log_info "Kubernetes performance metrics..."

    echo "=== RESOURCE USAGE ==="
    kubectl top pods -n guideai-scaling 2>/dev/null || echo "Metrics server not available"

    echo ""
    echo "=== HPA STATUS ==="
    kubectl describe hpa -n guideai-scaling 2>/dev/null || echo "No HPA found"

    echo ""
    echo "=== EVENTS ==="
    kubectl get events -n guideai-scaling --sort-by='.lastTimestamp' | tail -20
}

# Main function
main() {
    local command=${1:-status}

    case $command in
        "generate")
            check_prerequisites
            setup_k8s_directories
            create_manifests_manually
            log_success "Kubernetes manifests generated in $K8S_DIR"
            ;;
        "deploy")
            check_prerequisites
            deploy_to_k8s
            ;;
        "status")
            check_k8s_status
            ;;
        "performance")
            show_k8s_performance
            ;;
        "destroy")
            destroy_k8s
            ;;
        "help"|"-h"|"--help")
            echo "Usage: $0 [command]"
            echo ""
            echo "Commands:"
            echo "  generate    - Generate Kubernetes manifests"
            echo "  deploy      - Deploy to Kubernetes cluster"
            echo "  status      - Check deployment status"
            echo "  performance - Show performance metrics"
            echo "  destroy     - Remove all resources from Kubernetes"
            echo "  help        - Show this help"
            echo ""
            echo "Prerequisites:"
            echo "  - kubectl installed and configured"
            echo "  - Access to Kubernetes cluster"
            echo "  - Docker registry access (for images)"
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
