#!/bin/bash
# Hybrid Flink Architecture - Cloud Cleanup
# Removes AWS resources created for cloud deployment

set -e

echo "🧹 Cleaning up GuideAI Hybrid Flink - Cloud Infrastructure"
echo "=========================================================="

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

# Load configuration
load_config() {
    log_info "Loading configuration for cleanup..."

    if [ -f "$CONFIG_FILE" ]; then
        set -a
        source "$CONFIG_FILE"
        set +a
        log_success "Configuration loaded"
    else
        log_error "Configuration file not found: $CONFIG_FILE"
        exit 1
    fi
}

# Confirm cleanup
confirm_cleanup() {
    log_warning "This will delete AWS resources for the GuideAI telemetry pipeline!"
    log_info "Resources to be deleted:"
    echo "  - Kinesis Data Analytics application: guideai-telemetry-kpi"
    echo "  - S3 bucket: $S3_BUCKET"
    echo "  - CloudWatch dashboard: GuideAI-Telemetry-KPI"
    echo "  - IAM role: guideai-kinesis-analytics-role"
    echo ""
    read -p "Are you sure you want to continue? (yes/no): " -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
        log_info "Cleanup cancelled by user"
        exit 0
    fi
}

# Stop Kinesis application
stop_kinesis_app() {
    log_info "Stopping Kinesis Data Analytics application..."

    local APP_NAME="guideai-telemetry-kpi"
    local AWS_REGION=${AWS_REGION:-us-east-1}

    # Check if application exists
    if aws kinesisanalyticsv2 describe-application \
        --application-name $APP_NAME \
        --region $AWS_REGION &> /dev/null; then

        # Check if application is running
        APP_STATUS=$(aws kinesisanalyticsv2 describe-application \
            --application-name $APP_NAME \
            --region $AWS_REGION \
            --query 'ApplicationDetail.ApplicationStatus.Status' \
            --output text)

        if [ "$APP_STATUS" = "RUNNING" ] || [ "$APP_STATUS" = "STARTING" ]; then
            log_info "Stopping application..."
            aws kinesisanalyticsv2 stop-application \
                --application-name $APP_NAME \
                --region $AWS_REGION
            log_success "Application stop request submitted"
        else
            log_info "Application is not running (status: $APP_STATUS)"
        fi

        # Delete application
        log_info "Deleting Kinesis Data Analytics application..."
        aws kinesisanalyticsv2 delete-application \
            --application-name $APP_NAME \
            --application-configuration-delete-failover-config '{"ApplicationRestoreConfiguration": {"ApplicationRestoreType": "SKIP_RESTORE_FROM_SNAPSHOT"}}' \
            --region $AWS_REGION
        log_success "Application deleted"
    else
        log_info "Application not found - skipping deletion"
    fi
}

# Delete S3 bucket
delete_s3_bucket() {
    log_info "Deleting S3 bucket: $S3_BUCKET"

    local AWS_REGION=${AWS_REGION:-us-east-1}

    # Check if bucket exists
    if aws s3 ls s3://$S3_BUCKET &> /dev/null; then
        # Empty bucket first
        log_info "Emptying S3 bucket..."
        aws s3 rm s3://$S3_BUCKET --recursive --region $AWS_REGION

        # Delete bucket
        log_info "Deleting S3 bucket..."
        aws s3 rb s3://$S3_BUCKET --force --region $AWS_REGION
        log_success "S3 bucket deleted"
    else
        log_info "S3 bucket not found - skipping deletion"
    fi
}

# Delete CloudWatch dashboard
delete_cloudwatch_dashboard() {
    log_info "Deleting CloudWatch dashboard..."

    local AWS_REGION=${AWS_REGION:-us-east-1}

    aws cloudwatch delete-dashboards \
        --dashboard-names GuideAI-Telemetry-KPI \
        --region $AWS_REGION || log_info "Dashboard not found or already deleted"

    log_success "CloudWatch dashboard deleted"
}

# Delete IAM role
delete_iam_role() {
    log_info "Deleting IAM role..."

    local ROLE_NAME="guideai-kinesis-analytics-role"

    # Check if role exists
    if aws iam get-role --role-name $ROLE_NAME &> /dev/null; then

        # Detach policies
        aws iam detach-role-policy \
            --role-name $ROLE_NAME \
            --policy-arn arn:aws:iam::aws:policy/service-role/AmazonKinesisAnalyticsFullAccess \
            2>/dev/null || log_info "Policy already detached or not found"

        # Delete role
        aws iam delete-role --role-name $ROLE_NAME
        log_success "IAM role deleted: $ROLE_NAME"
    else
        log_info "IAM role not found - skipping deletion"
    fi
}

# Clean up local files
cleanup_local_files() {
    log_info "Cleaning up local files..."

    # Remove log files
    if [ -d "data/logs" ]; then
        rm -f data/logs/flink-dev.pid
        log_info "Local PID files removed"
    fi

    # Remove temporary files
    rm -f /tmp/trust-policy.json /tmp/app-config.json /tmp/dashboard.json
    log_info "Temporary files removed"
}

# Final validation
final_validation() {
    log_info "Validating cleanup..."

    local AWS_REGION=${AWS_REGION:-us-east-1}
    local errors=0

    # Check if application still exists
    if aws kinesisanalyticsv2 describe-application \
        --application-name guideai-telemetry-kpi \
        --region $AWS_REGION &> /dev/null; then
        log_warning "Kinesis application still exists - manual cleanup may be required"
        ((errors++))
    else
        log_success "Kinesis application: Deleted"
    fi

    # Check if S3 bucket still exists
    if aws s3 ls s3://$S3_BUCKET &> /dev/null; then
        log_warning "S3 bucket still exists - manual cleanup may be required"
        ((errors++))
    else
        log_success "S3 bucket: Deleted"
    fi

    # Check if IAM role still exists
    if aws iam get-role --role-name guideai-kinesis-analytics-role &> /dev/null; then
        log_warning "IAM role still exists - manual cleanup may be required"
        ((errors++))
    else
        log_success "IAM role: Deleted"
    fi

    if [ $errors -eq 0 ]; then
        log_success "All resources cleaned up successfully"
        return 0
    else
        log_warning "Some resources may require manual cleanup"
        return 1
    fi
}

# Show summary
show_summary() {
    echo ""
    echo "🧹 Cloud Cleanup Summary"
    echo "======================="
    echo ""
    echo "✅ Resources that were cleaned up:"
    echo "   - Kinesis Data Analytics application"
    echo "   - S3 bucket and all contents"
    echo "   - CloudWatch dashboard"
    echo "   - IAM role and policies"
    echo "   - Local temporary files"
    echo ""
    echo "🔄 What remains:"
    echo "   - Local development environment (docker-compose)"
    echo "   - TimescaleDB data (if any)"
    echo "   - Configuration files"
    echo ""
    echo "🛑 To stop local environment:"
    echo "   docker compose -f docker-compose.telemetry.yml down"
    echo ""
    echo "📝 For future deployments:"
    echo "   ./deployment/scripts/hybrid-deploy-cloud.sh"
    echo ""
    echo "🧹 For local cleanup:"
    echo "   docker compose -f docker-compose.telemetry.yml down -v"
}

# Main execution
main() {
    echo "Starting cloud cleanup at: $(date)"
    echo "Working directory: $(pwd)"
    echo ""

    load_config
    confirm_cleanup
    stop_kinesis_app
    delete_s3_bucket
    delete_cloudwatch_dashboard
    delete_iam_role
    cleanup_local_files
    final_validation
    show_summary

    echo ""
    log_success "Cloud cleanup completed successfully!"
    log_info "Time taken: $(($(date +%s) - $(date -d "$(echo 'Starting cloud cleanup at: ')" +%s))) seconds"
}

# Script entry point
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
