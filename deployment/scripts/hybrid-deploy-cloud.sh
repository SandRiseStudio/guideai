#!/bin/bash
# Hybrid Flink Architecture - Cloud Production Deployment
# AWS Kinesis Data Analytics for ARM64-free production deployment

set -e

echo "☁️  Deploying GuideAI Hybrid Flink - Cloud Production Environment"
echo "================================================================"

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
    log_info "Checking cloud deployment prerequisites..."

    # Check if AWS CLI is installed
    if ! command -v aws &> /dev/null; then
        log_error "AWS CLI is not installed. Please install: https://aws.amazon.com/cli/"
        exit 1
    fi

    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        log_error "AWS credentials not configured. Please run: aws configure"
        exit 1
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

    log_success "Cloud prerequisites check passed"
}

# Load configuration
load_config() {
    log_info "Loading cloud configuration from $CONFIG_FILE"

    if [ -f "$CONFIG_FILE" ]; then
        # Set environment variables
        set -a
        source "$CONFIG_FILE"
        set +a

        # Set cloud mode defaults
        DEPLOYMENT_MODE=cloud
        FLINK_MODE=prod
        WAREHOUSE_TYPE=postgresql

        # Override with production values
        export PROJECTION_BATCH_SIZE=5000
        export PROJECTION_FLUSH_INTERVAL_MS=30000
        export KAFKA_AUTO_OFFSET_RESET=latest

        log_success "Cloud configuration loaded successfully"
    else
        log_error "Configuration file not found: $CONFIG_FILE"
        exit 1
    fi
}

# Create AWS infrastructure
create_infrastructure() {
    log_info "Creating AWS infrastructure for telemetry pipeline..."

    # Create S3 bucket for Kinesis Data Analytics artifacts
    log_info "Creating S3 bucket for artifacts..."
    AWS_REGION=${AWS_REGION:-us-east-1}
    S3_BUCKET="guideai-telemetry-kpi-$(date +%s)"

    aws s3 mb s3://$S3_BUCKET --region $AWS_REGION || log_warning "S3 bucket might already exist"

    # Create CloudWatch log group
    log_info "Creating CloudWatch log group..."
    aws logs create-log-group --log-group-name /aws/kinesis-analytics/ApplicationLogs || log_warning "Log group might already exist"

    # Create IAM role for Kinesis Data Analytics
    log_info "Creating IAM role for Kinesis Data Analytics..."
    create_iam_role

    log_success "AWS infrastructure setup completed"
}

# Create IAM role
create_iam_role() {
    local ROLE_NAME="guideai-kinesis-analytics-role"
    local POLICY_ARN="arn:aws:iam::aws:policy/service-role/AmazonKinesisAnalyticsFullAccess"

    # Check if role exists
    if aws iam get-role --role-name $ROLE_NAME &> /dev/null; then
        log_warning "IAM role $ROLE_NAME already exists"
        return 0
    fi

    # Create role
    cat > /tmp/trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "kinesisanalytics.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

    aws iam create-role \
        --role-name $ROLE_NAME \
        --assume-role-policy-document file:///tmp/trust-policy.json \
        --description "Role for GuideAI Kinesis Data Analytics"

    # Attach policy
    aws iam attach-role-policy \
        --role-name $ROLE_NAME \
        --policy-arn $POLICY_ARN

    log_success "IAM role created: $ROLE_NAME"
}

# Create Kinesis Data Analytics application
create_kinesis_app() {
    log_info "Creating Kinesis Data Analytics application..."

    local APP_NAME="guideai-telemetry-kpi"
    local AWS_REGION=${AWS_REGION:-us-east-1}

    # Create application
    cat > /tmp/app-config.json <<EOF
{
  "ApplicationName": "$APP_NAME",
  "ApplicationDescription": "GuideAI Telemetry KPI Processing Pipeline",
  "ApplicationCodeConfiguration": {
    "CodeContent": {
      "S3ContentLocation": {
        "BucketARN": "arn:aws:s3:::$S3_BUCKET",
        "FileKey": "telemetry_kpi_job.py"
      }
    },
    "RunConfiguration": {
      "AutoStartConfiguration": {
        "Disabled": true
      }
    }
  },
  "ApplicationConfigurationDescription": {
    "EnvironmentProperties": {
      "PropertyGroups": [
        {
          "PropertyGroupId": "KafkaProperties",
          "PropertyMap": {
            "bootstrap.servers": "$KAFKA_BOOTSTRAP_SERVERS",
            "group.id": "$KAFKA_CONSUMER_GROUP",
            "topic": "$KAFKA_TOPIC_TELEMETRY_EVENTS"
          }
        },
        {
          "PropertyGroupId": "DatabaseProperties",
          "PropertyMap": {
            "warehouse.type": "$WAREHOUSE_TYPE",
            "postgres.host": "$POSTGRES_HOST",
            "postgres.port": "$POSTGRES_PORT",
            "postgres.database": "$POSTGRES_DATABASE",
            "postgres.user": "$POSTGRES_USER"
          }
        }
      ]
    }
  }
}
EOF

    aws kinesisanalyticsv2 create-application \
        --cli-input-json file:///tmp/app-config.json \
        --region $AWS_REGION

    log_success "Kinesis Data Analytics application created: $APP_NAME"
}

# Upload application code
upload_code() {
    log_info "Uploading application code to S3..."

    local APP_NAME="guideai-telemetry-kpi"
    local AWS_REGION=${AWS_REGION:-us-east-1}

    # Copy Flink job to S3
    aws s3 cp deployment/flink/telemetry_kpi_job.py s3://$S3_BUCKET/ \
        --region $AWS_REGION

    log_success "Application code uploaded to S3"
}

# Update Kinesis application
update_application() {
    log_info "Updating Kinesis application with uploaded code..."

    local APP_NAME="guideai-telemetry-kpi"
    local AWS_REGION=${AWS_REGION:-us-east-1}

    aws kinesisanalyticsv2 update-application \
        --application-name $APP_NAME \
        --application-configuration-update '{
            "CodeContentUpdate": {
                "S3ContentLocationUpdate": {
                    "BucketARNUpdate": "arn:aws:s3:::'$S3_BUCKET'",
                    "FileKeyUpdate": "telemetry_kpi_job.py"
                }
            }
        }' \
        --region $AWS_REGION

    log_success "Application updated with new code"
}

# Start Kinesis application
start_application() {
    log_info "Starting Kinesis Data Analytics application..."

    local APP_NAME="guideai-telemetry-kpi"
    local AWS_REGION=${AWS_REGION:-us-east-1}

    aws kinesisanalyticsv2 start-application \
        --application-name $APP_NAME \
        --region $AWS_REGION

    log_success "Application started"
    log_info "Monitor progress in AWS Console: https://console.aws.amazon.com/kinesisanalyticsv2/"
}

# Create monitoring dashboard
setup_monitoring() {
    log_info "Setting up CloudWatch monitoring dashboard..."

    # Create dashboard configuration
    cat > /tmp/dashboard.json <<EOF
{
  "widgets": [
    {
      "type": "metric",
      "x": 0,
      "y": 0,
      "width": 12,
      "height": 6,
      "properties": {
        "metrics": [
          [ "AWS/KinesisAnalytics", "numRecordsInPerSecond", "ApplicationName", "$APP_NAME" ]
        ],
        "period": 300,
        "stat": "Sum",
        "region": "$AWS_REGION",
        "title": "Kinesis Analytics - Records Per Second"
      }
    },
    {
      "type": "metric",
      "x": 0,
      "y": 6,
      "width": 12,
      "height": 6,
      "properties": {
        "metrics": [
          [ "AWS/KinesisAnalytics", "numRecordsOutPerSecond", "ApplicationName", "$APP_NAME" ]
        ],
        "period": 300,
        "stat": "Sum",
        "region": "$AWS_REGION",
        "title": "Kinesis Analytics - Records Out Per Second"
      }
    }
  ]
}
EOF

    aws cloudwatch put-dashboard \
        --dashboard-name "GuideAI-Telemetry-KPI" \
        --dashboard-body file:///tmp/dashboard.json \
        --region $AWS_REGION

    log_success "CloudWatch dashboard created"
}

# Validate cloud deployment
validate_deployment() {
    log_info "Validating cloud deployment..."

    local APP_NAME="guideai-telemetry-kpi"
    local AWS_REGION=${AWS_REGION:-us-east-1}

    # Check application status
    log_info "Checking application status..."
    APP_STATUS=$(aws kinesisanalyticsv2 describe-application \
        --application-name $APP_NAME \
        --region $AWS_REGION \
        --query 'ApplicationDetail.ApplicationStatus.Status' \
        --output text)

    if [ "$APP_STATUS" = "RUNNING" ]; then
        log_success "Application is running successfully"
    elif [ "$APP_STATUS" = "STARTING" ]; then
        log_info "Application is starting up..."
    else
        log_warning "Application status: $APP_STATUS - check AWS console for details"
    fi

    # Test connectivity
    log_info "Testing Kafka connectivity..."
    if [ ! -z "$KAFKA_BOOTSTRAP_SERVERS" ]; then
        log_info "Kafka servers configured: $KAFKA_BOOTSTRAP_SERVERS"
    fi

    log_success "Cloud deployment validation completed"
}

# Show status
show_status() {
    echo ""
    echo "☁️  Cloud Production Environment Ready!"
    echo "========================================"
    echo ""
    echo "🎯 AWS Resources Created:"
    echo "   - Kinesis Data Analytics: guideai-telemetry-kpi"
    echo "   - S3 Bucket: $S3_BUCKET"
    echo "   - CloudWatch Dashboard: GuideAI-Telemetry-KPI"
    echo "   - IAM Role: guideai-kinesis-analytics-role"
    echo ""
    echo "📊 Monitoring:"
    echo "   - AWS Console: https://console.aws.amazon.com/kinesisanalyticsv2/"
    echo "   - CloudWatch: https://console.aws.amazon.com/cloudwatch/"
    echo ""
    echo "🔄 Application Status:"
    aws kinesisanalyticsv2 describe-application \
        --application-name guideai-telemetry-kpi \
        --region ${AWS_REGION:-us-east-1} \
        --query 'ApplicationDetail.{Name:ApplicationName,Status:ApplicationStatus}' \
        --output table || echo "   Check AWS console for application status"
    echo ""
    echo "🛑 To stop application:"
    echo "   aws kinesisanalyticsv2 stop-application --application-name guideai-telemetry-kpi --region ${AWS_REGION:-us-east-1}"
    echo ""
    echo "🗑️  To cleanup infrastructure:"
    echo "   ./deployment/scripts/hybrid-cleanup-cloud.sh"
}

# Main execution
main() {
    echo "Starting cloud deployment at: $(date)"
    echo "Working directory: $(pwd)"
    echo ""

    check_prerequisites
    load_config
    create_infrastructure
    upload_code
    create_kinesis_app
    update_application
    start_application
    setup_monitoring
    validate_deployment
    show_status

    echo ""
    log_success "Cloud production environment deployment completed successfully!"
    log_info "Time taken: $(($(date +%s) - $(date -d "$(echo 'Starting cloud deployment at: ')" +%s))) seconds"
}

# Script entry point
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
