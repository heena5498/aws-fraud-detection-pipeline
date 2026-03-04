# Getting Started Guide

Complete setup instructions for the AWS-Native Fraud Detection Pipeline.

---

## Prerequisites

### Required Tools
1. **AWS Account** with Admin access
2. **AWS CLI** (v2.13+)
   ```bash
   aws --version
   aws configure  # Set credentials
   ```

3. **Node.js** (v18+) and npm
   ```bash
   node --version  # Should be 18.x or higher
   npm --version
   ```

4. **Python** (3.9 - 3.11)
   ```bash
   python3 --version
   python3 -m venv --help  # Verify venv module
   ```

5. **Docker Desktop** (for local API testing)
   ```bash
   docker --version
   docker-compose --version
   ```

6. **Git**
   ```bash
   git --version
   ```

---

## Step 1: Clone Repository

```bash
git clone https://github.com/yourusername/fraud-detection-aws.git
cd fraud-detection-aws
```

---

## Step 2: Python Environment Setup

```bash
# Create virtual environment
python3 -m venv venv

# Activate (macOS/Linux)
source venv/bin/activate

# Activate (Windows)
venv\Scripts\activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt

# Verify installation
python -c "import pandas, numpy, sklearn, xgboost, fastapi; print('✓ All packages installed')"
```

---

## Step 3: AWS CDK Setup

```bash
cd infrastructure

# Install Node dependencies
npm install

# Install AWS CDK CLI globally
npm install -g aws-cdk

# Verify CDK
cdk --version  # Should be 2.104+

# Bootstrap CDK (FIRST TIME ONLY)
cdk bootstrap aws://ACCOUNT-ID/us-east-1

# Return to project root
cd ..
```

---

## Step 4: Environment Configuration

Create `.env` file in project root:

```bash
cat > .env << 'EOF'
# AWS Configuration
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=123456789012  # Replace with your account ID
ENVIRONMENT=dev

# S3 Buckets (CDK will create these)
BRONZE_BUCKET=fraud-bronze-dev
SILVER_BUCKET=fraud-silver-dev
GOLD_BUCKET=fraud-gold-dev
MODELS_BUCKET=fraud-models-dev

# DynamoDB Tables
DEDUPE_TABLE_NAME=fraud-dedupe-dev
ALERTS_TABLE_NAME=fraud-alerts-dev
FEEDBACK_TABLE_NAME=fraud-feedback-dev

# Kinesis
KINESIS_STREAM_NAME=fraud-transactions-dev

# API Configuration
FRAUD_THRESHOLD=0.7
PSI_THRESHOLD=0.25

# MLflow (local or EC2)
MLFLOW_TRACKING_URI=http://localhost:5000

# Logging
LOG_LEVEL=INFO
EOF

# Load environment variables
source .env  # macOS/Linux
# Or manually set on Windows
```

---

## Step 5: Deploy AWS Infrastructure

```bash
cd infrastructure

# Set environment variable
export ENVIRONMENT=dev

# Preview what will be deployed
cdk diff

# Deploy all stacks
cdk deploy --all --require-approval never

# This deploys:
# - FraudKinesisStack-dev: Kinesis stream, Bronze Lambda, S3 buckets
# - FraudDatabaseStack-dev: DynamoDB tables
# - FraudApiStack-dev: ECS Fargate + ALB
# - FraudMonitoringStack-dev: CloudWatch dashboards

# Deployment takes ~10-15 minutes
```

**Expected Output:**
```
  FraudKinesisStack-dev
Outputs:
FraudKinesisStack-dev.StreamName = fraud-transactions-dev
FraudKinesisStack-dev.BronzeBucketName = fraud-bronze-dev

  FraudDatabaseStack-dev
Outputs:
FraudDatabaseStack-dev.DedupeTableName = fraud-dedupe-dev
FraudDatabaseStack-dev.AlertsTableName = fraud-alerts-dev

  FraudApiStack-dev
Outputs:
FraudApiStack-dev.ApiUrl = http://fraud-api-XXXXX.us-east-1.elb.amazonaws.com/api/v1

  FraudMonitoringStack-dev
```

Copy the `ApiUrl` from output!

---

## Step 6: Download Dataset

```bash
# Download PaySim dataset from Kaggle
# Option 1: Manual download from https://www.kaggle.com/datasets/ealaxi/paysim1
# Place in: data/PS_20174392719_1491204439457_log.csv

# Option 2: Use Kaggle API
pip install kaggle
kaggle datasets download -d ealaxi/paysim1
unzip paysim1.zip -d data/

# Verify
ls -lh data/PS_*.csv
# Should see ~470 MB file
```

---

## Step 7: Produce Events to Kinesis

```bash
# From project root
python src/data_producer/producer.py \
    --dataset data/PS_20174392719_1491204439457_log.csv \
    --stream-name fraud-transactions-dev \
    --rate 100 \
    --limit 10000

# This will:
# 1. Read PaySim dataset
# 2. Normalize to Pydantic schema
# 3. Send to Kinesis at 100 events/second
# 4. Stop after 10,000 events
```

**Expected Output:**
```
[Producer] Loading dataset...
[Producer] Loaded 6,362,620 transactions
[Producer] Sending to Kinesis: fraud-transactions-dev
[Producer] Rate limit: 100 events/sec
Progress: 1000/10000 (10.0%) | Rate: 98.5 events/sec
Progress: 2000/10000 (20.0%) | Rate: 99.2 events/sec
...
[Producer] Complete: 10,000 events sent
[Producer] Errors: 0
```

---

## Step 8: Verify Bronze Layer Ingestion

```bash
# Check CloudWatch Logs
aws logs tail /aws/lambda/fraud-bronze-dev --follow

# Should see:
# {"timestamp": "2026-03-03T14:30:00Z", "level": "INFO", "message": "Processing batch of 100 Kinesis records"}
# {"timestamp": "2026-03-03T14:30:01Z", "level": "INFO", "message": "Wrote 98 records to S3", "records": 98}

# Check S3
aws s3 ls s3://fraud-bronze-dev/transactions/ --recursive --human-readable | head

# Should see Parquet files:
# fraud-bronze-dev/transactions/year=2024/month=01/day=15/hour=10/batch_20260303_143001.parquet
```

---

## Step 9: Run Glue Jobs (Feature Engineering)

### Create Glue Database
```bash
aws glue create-database --database-input '{"Name": "fraud_detection_dev"}'
```

### Create Silver Layer Glue Job
```bash
aws glue create-job \
    --name fraud-silver-job-dev \
    --role GlueServiceRole \
    --command '{"Name": "glueetl", "ScriptLocation": "s3://fraud-models-dev/scripts/silver_layer.py", "PythonVersion": "3"}' \
    --default-arguments '{
        "--job-language": "python",
        "--bronze_bucket": "fraud-bronze-dev",
        "--silver_bucket": "fraud-silver-dev",
        "--environment": "dev",
        "--pii_salt_secret": "fraud-pii-salt"
    }' \
    --glue-version 4.0

# Upload script to S3
aws s3 cp src/silver_layer/job.py s3://fraud-models-dev/scripts/silver_layer.py

# Run job
aws glue start-job-run --job-name fraud-silver-job-dev
```

### Create Gold Layer Glue Job
```bash
aws glue create-job \
    --name fraud-gold-job-dev \
    --role GlueServiceRole \
    --command '{"Name": "glueetl", "ScriptLocation": "s3://fraud-models-dev/scripts/gold_layer.py", "PythonVersion": "3"}' \
    --default-arguments '{
        "--job-language": "python",
        "--silver_bucket": "fraud-silver-dev",
        "--gold_bucket": "fraud-gold-dev",
        "--training_start_date": "2024-01-01",
        "--training_end_date": "2024-01-31",
        "--environment": "dev"
    }' \
    --glue-version 4.0

# Upload script
aws s3 cp src/gold_layer/job.py s3://fraud-models-dev/scripts/gold_layer.py

# Run job
aws glue start-job-run --job-name fraud-gold-job-dev
```

**Monitor Jobs:**
```bash
aws glue get-job-run --job-name fraud-silver-job-dev --run-id jr_XXXXX
```

---

## Step 10: Train Models

### Option 1: Local Training
```bash
# Start MLflow server (in separate terminal)
mlflow server \
    --backend-store-uri sqlite:///mlflow.db \
    --default-artifact-root s3://fraud-models-dev/mlflow-artifacts/ \
    --host 0.0.0.0 \
    --port 5000

# Open MLflow UI: http://localhost:5000

# Train models
python src/ml_training/train.py \
    --gold-path s3://fraud-gold-dev/training/ \
    --mlflow-uri http://localhost:5000
```

### Option 2: EC2 Training (For Large Datasets)
```bash
# Launch EC2 instance (t3.xlarge, 4 vCPU, 16 GB RAM)
aws ec2 run-instances \
    --image-id ami-0c55b159cbfafe1f0 \
    --instance-type t3.xlarge \
    --key-name my-key-pair \
    --security-group-ids sg-XXXXX \
    --iam-instance-profile Name=MLflowInstanceProfile

# SSH and run training
ssh -i my-key-pair.pem ec2-user@<instance-ip>
# ... setup Python environment ...
python src/ml_training/train.py --gold-path s3://fraud-gold-dev/training/
```

**Expected Training Output:**
```
=== Training Results ===

logistic_regression:
  PR-AUC: 0.6521
  ROC-AUC: 0.7845
  Precision: 0.6102
  Recall: 0.7234

xgboost:
  PR-AUC: 0.8234
  ROC-AUC: 0.9123
  Precision: 0.7856
  Recall: 0.8512

lightgbm:
  PR-AUC: 0.8102
  ROC-AUC: 0.9089
  Precision: 0.7645
  Recall: 0.8423

 Best model: xgboost
```

### Deploy Model to S3
```bash
# After training, find best model in MLflow UI
# Download and upload to production location
aws s3 cp /path/to/best-model.pkl s3://fraud-models-dev/production/model.pkl
```

---

## Step 11: Test FastAPI Service

### Check ECS Service Status
```bash
# Get task status
aws ecs describe-services \
    --cluster fraud-cluster-dev \
    --services fraud-api-dev \
    --query 'services[0].runningCount'

# Should return: 2 (desired count)
```

### Test Health Endpoint
```bash
ALB_URL="http://fraud-api-XXXXX.us-east-1.elb.amazonaws.com"

curl $ALB_URL/api/v1/health

# Expected:
# {"status": "healthy", "timestamp": "2026-03-03T14:30:00Z", "model_loaded": true}
```

### Test Scoring Endpoint
```bash
curl -X POST $ALB_URL/api/v1/score \
    -H "Content-Type: application/json" \
    -d '{
        "transaction_id": "test_001",
        "amount": 999.99,
        "user_id": "user_123",
        "merchant_id": "merchant_456",
        "merchant_category": "online_retail",
        "transaction_type": "purchase",
        "country": "US"
    }'

# Expected:
# {
#   "transaction_id": "test_001",
#   "fraud_probability": 0.85,
#   "is_fraud": true,
#   "risk_level": "high",
#   "top_features": [...],
#   "model_version": "xgboost-v1.0",
#   "scored_at": "2026-03-03T14:30:00Z"
# }
```

---

## Step 12: Run Frontend

```bash
cd frontend

# Install dependencies
npm install

# Create .env.local
cat > .env.local << EOF
REACT_APP_API_URL=http://fraud-api-XXXXX.us-east-1.elb.amazonaws.com
EOF

# Start development server
npm start

# Open browser: http://localhost:3000
```

**Frontend Features:**
- **Alerts List**: View all high-risk transactions
- **Alert Detail**: Detailed view with feature explanations
- **Feedback**: Submit analyst decisions (fraud/legitimate)

---

## Step 13: Monitor System

### CloudWatch Dashboard
```bash
# Open CloudWatch console
echo "https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=fraud-detection-dev"
```

### View Logs
```bash
# Bronze Lambda logs
aws logs tail /aws/lambda/fraud-bronze-dev --follow

# ECS API logs
aws logs tail /ecs/fraud-api --follow --filter-pattern '"ERROR"'

# Glue job logs
aws logs tail /aws-glue/jobs/output --follow
```

### Check Metrics
```bash
# Kinesis throughput
aws cloudwatch get-metric-statistics \
    --namespace AWS/Kinesis \
    --metric-name IncomingRecords \
    --dimensions Name=StreamName,Value=fraud-transactions-dev \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 300 \
    --statistics Sum

# API latency
aws cloudwatch get-metric-statistics \
    --namespace AWS/ApplicationELB \
    --metric-name TargetResponseTime \
    --dimensions Name=LoadBalancer,Value=app/fraud-api-XXXXX \
    --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%S) \
    --end-time $(date -u +%Y-%m-%dT%H:%M:%S) \
    --period 60 \
    --statistics Average
```

---

## Troubleshooting

### Issue: Lambda Function Errors
```bash
# Check logs
aws logs tail /aws/lambda/fraud-bronze-dev --follow

# Common causes:
# 1. Missing permissions (check IAM role)
# 2. S3 bucket not found (verify environment variables)
# 3. DynamoDB table not created (check CFN stack)
```

### Issue: ECS Tasks Not Starting
```bash
# Check task definition
aws ecs describe-task-definition --task-definition fraud-api-dev:1

# Check service events
aws ecs describe-services --cluster fraud-cluster-dev --services fraud-api-dev \
    --query 'services[0].events[0:5]'

# Common causes:
# 1. Docker image build failed (check CodeBuild logs)
# 2. Health check failing (verify /api/v1/health endpoint)
# 3. IAM role missing permissions
```

### Issue: Glue Job Fails
```bash
# Check job run details
aws glue get-job-run --job-name fraud-silver-job-dev --run-id jr_XXXXX

# View error message
aws logs tail /aws-glue/jobs/error --follow

# Common causes:
# 1. S3 bucket not found (verify --bronze_bucket argument)
# 2. Python dependencies missing (add to Glue job --extra-py-files)
# 3. Out of memory (increase DPU count)
```

---

## Clean Up (To Avoid Charges)

```bash
cd infrastructure

# Destroy all resources
cdk destroy --all

# Confirm deletion of S3 buckets (if not already empty)
aws s3 rm s3://fraud-bronze-dev --recursive
aws s3 rm s3://fraud-silver-dev --recursive
aws s3 rm s3://fraud-gold-dev --recursive
aws s3 rm s3://fraud-models-dev --recursive

# Delete Glue jobs
aws glue delete-job --job-name fraud-silver-job-dev
aws glue delete-job --job-name fraud-gold-job-dev

# Delete Glue database
aws glue delete-database --name fraud_detection_dev
```

---

## Next Steps

1. **Enhance Models**: Experiment with hyperparameters in MLflow
2. **Add Drift Monitoring**: Deploy drift monitoring Lambda (see `src/drift_monitor/handler.py`)
3. **Set Up Retraining**: Create Step Functions workflow for automated retraining
4. **Production Deployment**: 
   - Set `ENVIRONMENT=prod`
   - Increase Kinesis shards (10+)
   - Enable DynamoDB auto-scaling
   - Add Route53 custom domain
   - Configure SSL/TLS certificates

---

## Support

- **Documentation**: See `docs/` folder
- **Issues**: Open GitHub issue
- **Architecture Decisions**: See `docs/ADR.md`

---

**You're all set!**  Your AWS-native fraud detection pipeline is now running.
