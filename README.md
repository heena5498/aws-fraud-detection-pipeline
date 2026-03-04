# AWS-Native Real-Time Fraud Detection Pipeline

> **Production-Grade ML System**: Event-driven microservices architecture demonstrating modern software engineering, ML engineering, and AWS best practices.

[![Architecture](https://img.shields.io/badge/Architecture-Event--Driven%20Microservices-blue)](#architecture-type)
[![AWS](https://img.shields.io/badge/AWS-Serverless%20Native-orange)](#aws-services)
[![SOLID](https://img.shields.io/badge/Principles-SOLID-green)](#solid-principles)
[![Patterns](https://img.shields.io/badge/Design%20Patterns-12+-yellow)](#design-patterns)
[![Python](https://img.shields.io/badge/Python-3.11-blue)](#tech-stack)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.2-blue)](#tech-stack)

---

## Table of Contents

- [Project Goal](#-project-goal)
- [Architecture Type](#-architecture-type)
- [Design Patterns](#-design-patterns)
- [SOLID Principles](#-solid-principles)
- [Architecture Trade-offs](#-architecture-trade-offs)
- [AWS Services](#-aws-services)
- [Project Structure](#-project-structure)
- [Data Flow](#-data-flow)
- [Quick Start](#-quick-start)
- [Cost Analysis](#-cost-analysis)
- [Tech Stack](#-tech-stack)
- [Key Features](#-key-features)

---

## Project Goal

Build a **production-ready fraud detection system** that:

-  Detects fraudulent transactions in **<200ms** (p95 latency)
-  Processes **1000+ events/second** with exactly-once semantics
-  Automatically retrains when **data drift detected** (PSI > 0.25)
-  Provides **explainable predictions** with feature importance
-  Scales independently per component (Kinesis, Lambda, ECS, Glue)
-  Demonstrates **modern architecture patterns** and **SOLID principles**

---

## Architecture Type

This system is a **hybrid architecture** combining:

###  **Event-Driven Architecture (Primary)**

**Core Pattern**: Events flow through the system, triggering asynchronous processing.

```
Transaction Event → Kinesis → Lambda → S3 → EventBridge → Glue → MLflow → ECS API
```

**Key Characteristics**:
- **Event Producers**: Kinesis producer sends transaction events
- **Event Stream**: Kinesis Data Streams (1000+ events/sec)
- **Event Consumers**: Bronze Lambda, Glue jobs, Drift monitor
- **Event Triggers**: EventBridge schedules (Glue jobs, drift checks)
- **Event Sourcing**: All events stored immutably in Bronze layer

**Benefits**:
- Loose coupling between components
- Asynchronous processing (non-blocking)
- Scalability (each component scales independently)
- Fault tolerance (retry logic, dead-letter queues)

---

###  **Microservices Architecture**

Each service has a **single, well-defined responsibility**:

| Microservice | Responsibility | Technology | Scaling |
|--------------|---------------|------------|---------|
| **Data Producer** | Event generation | Python + Kinesis SDK | Manual |
| **Bronze Service** | Ingestion + validation | AWS Lambda | Auto (Kinesis trigger) |
| **Silver Service** | Feature engineering | AWS Glue (PySpark) | DPU-based |
| **Gold Service** | Training data prep | AWS Glue (PySpark) | DPU-based |
| **Scoring Service** | Real-time predictions | FastAPI on ECS Fargate | Auto (CPU/memory) |
| **Drift Monitor** | Model monitoring | AWS Lambda | Scheduled |
| **Alert Service** | Fraud notifications | DynamoDB + Lambda | Event-driven |

**Microservice Characteristics**:
-  Independent deployment (each Lambda/ECS service)
-  Decoupled via events (Kinesis, EventBridge)
-  Polyglot persistence (S3, DynamoDB, Kinesis)
-  Single responsibility per service
-  API-driven communication (REST, async events)

---

###  **Lambda Architecture**

Combines **batch** and **stream** processing:

```
┌─────────────────────────────────────────┐
│         Speed Layer (Real-time)         │
│  Kinesis → Lambda → S3 Bronze           │
│  Latency: <1 minute                     │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│         Batch Layer (Historical)        │
│  EventBridge → Glue (Silver/Gold)       │
│  Frequency: Hourly/Daily                │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│         Serving Layer (API)             │
│  FastAPI (ECS) → Predictions            │
│  Latency: <200ms                        │
└─────────────────────────────────────────┘
```

**Why Lambda Architecture?**
- **Speed Layer**: Real-time ingestion for immediate data availability
- **Batch Layer**: Accurate, complete feature engineering (joins, aggregations)
- **Serving Layer**: Optimized for low-latency reads

---

###  **Medallion Architecture (Data Engineering)**

Multi-hop architecture for **progressive data quality**:

```
Bronze (Raw) → Silver (Cleansed) → Gold (Curated)
```

| Layer | Quality | Features | Use Case |
|-------|---------|----------|----------|
| **Bronze** | Raw, validated | Schema validation, deduplication | Event log, audit trail |
| **Silver** | Cleansed, enriched | PII tokenization, velocity features, aggregates | Feature engineering |
| **Gold** | Curated, optimized | Point-in-time features, ML-ready | Model training, queries |

**Benefits**:
- Data quality improves at each layer
- Bronze acts as source of truth (replayable)
- Silver/Gold can be rebuilt from Bronze
- Separation of concerns (ingestion vs. transformation)

---

## Design Patterns

The system implements **12 design patterns**:

### 1. **Producer-Consumer Pattern**
**Location**: `src/data_producer/producer.py` → Kinesis → `src/bronze_layer/handler.py`

```python
# Producer
class KinesisProducer:
    def send_batch(self, events):  # Produces events
        self.kinesis.put_records(StreamName=stream, Records=events)

# Consumer
def lambda_handler(event, context):  # Consumes from Kinesis
    for record in event['Records']:
        process_event(record)
```

**Benefits**: Decouples data generation from processing, enables async workflows.

---

### 2. **Repository Pattern**
**Location**: `src/bronze_layer/s3_writer.py`, `src/bronze_layer/deduplicator.py`

```python
# Abstracts storage details
class S3ParquetWriter:
    def write_batch(self, events):
        df = pd.DataFrame(events)
        self.s3_client.put_object(Bucket=bucket, Key=key, Body=parquet_bytes)

class Deduplicator:
    def is_duplicate(self, transaction_id):
        response = self.table.get_item(Key={'id': transaction_id})
        return 'Item' in response
```

**Benefits**: Abstracts data access, enables testing with mocks (moto, LocalStack).

---

### 3. **Factory Pattern**
**Location**: `src/common/aws_clients.py`

```python
class AWSClients:
    def get_client(self, service_name: str):
        """Factory method for AWS clients"""
        if service_name not in self._clients:
            self._clients[service_name] = boto3.client(
                service_name, config=self.boto_config
            )
        return self._clients[service_name]
    
    @property
    def s3(self):
        return self.get_client('s3')  # Lazy initialization
```

**Benefits**: Centralized client creation, connection pooling, retry configuration.

---

### 4. **Singleton Pattern**
**Location**: `src/common/config.py`, `src/common/metrics.py`

```python
_config: Optional[Config] = None

def get_config() -> Config:
    """Singleton instance"""
    global _config
    if _config is None:
        _config = Config()
    return _config
```

**Benefits**: Single configuration instance across the application, consistent state.

---

### 5. **Strategy Pattern**
**Location**: `src/ml_training/train.py`

```python
class FraudModelTrainer:
    def train_logistic_regression(self, X, y):  # Strategy 1
        return LogisticRegression().fit(X, y)
    
    def train_xgboost(self, X, y):  # Strategy 2
        return xgb.XGBClassifier().fit(X, y)
    
    def train_lightgbm(self, X, y):  # Strategy 3
        return lgb.LGBMClassifier().fit(X, y)
```

**Benefits**: Easily swap/compare ML algorithms without changing client code.

---

### 6. **Decorator Pattern**
**Location**: `src/data_producer/schemas.py`, `src/common/metrics.py`

```python
# Pydantic field validation decorator
class TransactionEvent(BaseModel):
    @validator('amount')
    def validate_amount(cls, v):
        if v < 0.01:
            raise ValueError('Amount must be >= 0.01')
        return v

# Timing decorator
with Timer('processing_time'):
    process_data()
```

**Benefits**: Clean separation of concerns (validation, timing, logging).

---

### 7. **Observer Pattern**
**Location**: EventBridge → Lambda triggers, DynamoDB Streams

```python
# EventBridge rule observes schedule events
DriftMonitorRule:
  Schedule: cron(0 1 * * ? *)  # Daily at 1 AM
  Target: DriftMonitorLambda

# DynamoDB Streams observe table changes
AlertsTable:
  StreamViewType: NEW_AND_OLD_IMAGES
  Consumers: [AlertNotificationLambda]
```

**Benefits**: Decoupled event handling, multiple observers can react to same event.

---

### 8. **Circuit Breaker Pattern**
**Location**: Lambda retry config, Boto3 retries

```python
# Boto3 adaptive retry (built-in circuit breaker)
BotoConfig(
    retries={
        'max_attempts': 3,
        'mode': 'adaptive'  # Backs off automatically on errors
    }
)
```

**Benefits**: Prevents cascading failures, fault tolerance.

---

### 9. **Idempotency Pattern**
**Location**: `src/bronze_layer/deduplicator.py`

```python
def mark_processed(self, transaction_id: str):
    """Idempotent write using DynamoDB conditional expression"""
    self.table.put_item(
        Item={'id': transaction_id, 'processed_at': now()},
        ConditionExpression='attribute_not_exists(id)'  #  Only if NOT exists
    )
```

**Benefits**: Exactly-once processing, prevents duplicate records.

---

### 10. **CQRS (Command Query Responsibility Segregation)**
**Location**: API endpoints, DynamoDB tables

```python
# WRITE PATH (Commands)
@app.post("/api/v1/score")
async def score_transaction(txn):
    score = model.predict(txn)
    if score.is_fraud:
        save_alert(txn, score)  # Write to alerts table
    return score

# READ PATH (Queries)
@app.get("/api/v1/alerts")
async def list_alerts(status: str = None):
    return query_alerts_table(status)  # Optimized for reads
```

**Benefits**: Optimized read/write paths, independent scaling.

---

### 11. **Saga Pattern (Distributed Transactions)**
**Location**: Step Functions retraining workflow

```json
{
  "Comment": "Automated retraining saga",
  "States": {
    "RunGoldLayerJob": {"Type": "Task", "Resource": "arn:aws:glue:..."},
    "TrainModel": {"Type": "Task", "Resource": "arn:aws:lambda:..."},
    "EvaluateModel": {"Type": "Task", "Resource": "arn:aws:lambda:..."},
    "DeployIfBetter": {"Type": "Choice"},
    "RollbackOnFailure": {"Type": "Task"}
  }
}
```

**Benefits**: Manages complex workflows with compensation logic, atomic operations.

---

### 12. **Adapter Pattern**
**Location**: `src/data_producer/dataset_loader.py`

```python
# Adapter: Converts different dataset formats to unified schema
def normalize_paysim(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        'transaction_id': df['step'].astype(str) + '_' + df['nameOrig'],
        'amount': df['amount'],
        'user_id': df['nameOrig']
    })

def normalize_kaggle_cc(df: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        'transaction_id': 'kaggle_' + df.index.astype(str),
        'amount': df['Amount']
    })
```

**Benefits**: Support multiple data sources transparently.

---

##  SOLID Principles

###  **S - Single Responsibility Principle**

Each component has **ONE reason to change**:

| Component | Single Responsibility |
|-----------|----------------------|
| `validator.py` | Schema validation only |
| `deduplicator.py` | Idempotency checks only |
| `s3_writer.py` | S3 Parquet writes only |
| `config.py` | Configuration management only |
| `logger.py` | Logging only |
| `metrics.py` | Metrics emission only |

**Example**:
```python
#  GOOD: Delegated responsibilities
class BronzeLayerHandler:
    def __init__(self):
        self.validator = Validator()        # Delegates validation
        self.deduplicator = Deduplicator()  # Delegates deduplication
        self.s3_writer = S3Writer()         # Delegates storage
    
    def process(self, event):
        validated = self.validator.validate(event)
        if not self.deduplicator.is_duplicate(validated['id']):
            self.s3_writer.write(validated)
```

---

###  **O - Open/Closed Principle**

Open for extension, closed for modification:

```python
#  Can add new schema versions without modifying existing code
class TransactionEvent(BaseModel):
    schema_version: str = "1.0"
    # ... fields ...

# Future: Add v2.0 without breaking v1.0
class TransactionEventV2(TransactionEvent):
    schema_version: str = "2.0"
    new_field: Optional[str] = None

#  Can add new ML models without modifying trainer
class FraudModelTrainer:
    def run_training(self):
        self.train_logistic_regression()
        self.train_xgboost()
        self.train_lightgbm()
        # self.train_neural_network()  # Future addition
```

---

###  **L - Liskov Substitution Principle**

Subtypes are substitutable for their base types:

```python
#  JSON logger and Standard logger are substitutable
json_logger = get_logger('service', use_json=True)
std_logger = get_logger('service', use_json=False)

# Both work identically
json_logger.info("Message")  # Works
std_logger.info("Message")   # Works (same interface)

#  Real AWS clients and mocks are substitutable
s3_real = boto3.client('s3')
s3_mock = moto.mock_s3()  # Substitutable for testing
```

---

###  **I - Interface Segregation Principle**

Clients shouldn't depend on interfaces they don't use:

```python
#  GOOD: Segregated interfaces
class Validator:
    def validate(self, event): ...  # Only validation methods

class Deduplicator:
    def is_duplicate(self, id): ...  # Only deduplication methods

class S3Writer:
    def write_batch(self, events): ...  # Only S3 methods

#  Clients use only what they need
metrics = get_metrics_client()
emit_counter('requests', 1)  # Service A only needs counters
emit_timer('latency', 0.5)   # Service B only needs timers
```

---

###  **D - Dependency Inversion Principle**

Depend on abstractions, not concretions:

```python
#  HIGH-LEVEL: Lambda handler depends on abstraction
def lambda_handler(event, context):
    config = get_config()  # Abstraction (doesn't know WHERE config comes from)
    bucket = config.bronze_bucket

#  LOW-LEVEL: Implementation can change
class Config:
    # Could be env vars, Parameter Store, Secrets Manager
    bronze_bucket: str = os.getenv('BRONZE_BUCKET', 'default')

#  Business logic depends on abstract write_batch()
def save_events(events):
    writer = S3ParquetWriter(bucket='...')
    writer.write_batch(events)  # Could swap to Database, local file, etc.
```

---

##  Architecture Trade-offs

Key architectural decisions with **explicit trade-offs**:

### 1. **Kinesis vs. Apache Kafka**

**Decision**: Use AWS Kinesis Data Streams

| Aspect | Kinesis | Kafka |
|--------|---------|-------|
| **Ops Overhead** |  Fully managed | Self-managed (MSK or EC2) |
| **Cost** |  $11/month (1 shard) | $300/month (3-broker cluster) |
| **Throughput** | 1 MB/s write, 2 MB/s read |  100+ MB/s per partition |
| **Ecosystem** | Limited |  Rich (Kafka Streams, ksqlDB) |
| **AWS Integration** |  Native (Lambda, IAM, CloudWatch) | Requires MSK |

**Trade-off Accepted**: Our throughput (1000 events/sec × 1 KB = 1 MB/s) fits in 1 shard. Kafka's ecosystem not needed.

---

### 2. **ECS Fargate vs. Lambda for API**

**Decision**: Deploy FastAPI on ECS Fargate

| Aspect | ECS Fargate | Lambda |
|--------|-------------|--------|
| **Cold Starts** |  No cold starts (always warm) | 500ms-2s cold start |
| **Latency** |  <200ms p95 | p95 includes cold starts |
| **Cost** | $29/month (always running) |  $3.50/month (pay-per-use) |
| **Complexity** | Docker + ECR + ECS |  Simple ZIP upload |

**Trade-off Accepted**: We pay **8x more** for ECS but get consistent sub-200ms latency. Critical for fraud detection.

---

### 3. **DynamoDB vs. Redis for Deduplication**

**Decision**: Use DynamoDB with TTL

| Aspect | DynamoDB | Redis (ElastiCache) |
|--------|----------|---------------------|
| **Latency** |  Single-digit ms |  Sub-millisecond |
| **Persistence** |  Durable storage | In-memory (requires snapshots) |
| **Cost** |  $1.25/1M writes | $20/month (cache.t3.micro) |
| **TTL** |  Built-in (automatic cleanup) | Manual expiration |
| **Ops** |  Fully managed | Cluster management |

**Trade-off Accepted**: DynamoDB provides durability + TTL at lower cost. Sub-ms latency not required for deduplication.

---

### 4. **Glue (PySpark) vs. Lambda for Feature Engineering**

**Decision**: Use AWS Glue jobs for Silver/Gold layers

| Aspect | Glue (PySpark) | Lambda |
|--------|----------------|--------|
| **Data Volume** |  100+ GB (distributed) | 512 MB-10 GB limit |
| **Window Functions** |  Native Spark support | Manual implementation |
| **Cost** | $0.44/DPU-hour |  $0.83/1M invocations |
| **Latency** | 2-5 min (batch) |  Real-time |

**Trade-off Accepted**: Feature engineering has complex joins/aggregations. Glue handles large datasets efficiently. Runs batch (hourly), not per-event.

---

### 5. **Point-in-Time Correctness**

**Decision**: Use `event_timestamp` + watermark in Gold layer

**Problem**: Train/serve skew causes model degradation.

**Solution**:
```python
#  GOOD: Features use event_timestamp (not processing_timestamp)
df_gold = df_silver.filter(F.col('event_timestamp') <= training_cutoff)
```

**Trade-off Accepted**: Slightly more complex ETL logic, but ensures no data leakage.

---

### 6. **PII Handling: SHA256 Hashing**

**Decision**: Hash `card_id` and `user_id` in Silver layer

```python
# SHA256 + salt from Secrets Manager
def hash_pii(value: str, salt: str) -> str:
    return hashlib.sha256(f"{value}{salt}".encode()).hexdigest()
```

| Approach | Pros | Cons |
|----------|------|------|
| **SHA256 Hash** |  One-way (irreversible) | Cannot recover original |
| **Encryption** |  Reversible (with key) | Key management complexity |
| **Tokenization** |  Reversible (lookup table) | Additional service cost |

**Trade-off Accepted**: SHA256 + salt provides deterministic hashing (same ID → same hash) while protecting PII. Original IDs in Bronze (encrypted S3).

---

##  AWS Services

| Service | Purpose | Configuration |
|---------|---------|---------------|
| **Kinesis Data Streams** | Real-time event ingestion | 1 shard, 24h retention, KMS encryption |
| **Lambda** | Serverless compute (Bronze, drift, alerts) | Python 3.11, 512 MB, 60s timeout |
| **S3** | Data lake (Bronze/Silver/Gold) | SSE-S3, partitioned by date/hour |
| **Glue** | Data Catalog + ETL (PySpark) | Glue 4.0, 2 DPUs, hourly schedule |
| **Athena** | SQL queries on S3 | Pay per TB scanned |
| **DynamoDB** | Deduplication, alerts, feedback | On-demand, TTL enabled, GSI for queries |
| **Step Functions** | Orchestration (retrain workflow) | Pay per state transition |
| **EventBridge** | Scheduling + event routing | Cron schedules for Glue jobs |
| **ECS Fargate** | FastAPI scoring service | 2 tasks, 0.5 vCPU, 1 GB RAM |
| **ALB** | Load balancing for ECS | Health checks, auto-scaling triggers |
| **CloudWatch** | Logs, metrics, alarms | Structured JSON logs, custom metrics |
| **Secrets Manager** | PII salt storage | Quarterly rotation |

---

##  Project Structure

```
fraud-detection-aws/
├── README.md                           # ← You are here
├── docs/
│   ├── GETTING_STARTED.md              # Setup guide
│   ├── ARCHITECTURE_ANALYSIS.md        # Design patterns deep-dive
│   ├── ADR.md                          # Architecture Decision Records
│   └── RUNBOOK.md                      # Operations guide
│
├── src/
│   ├── data_producer/                  #  Event generation
│   │   ├── schemas.py                  # Pydantic TransactionEvent schema
│   │   ├── producer.py                 # Kinesis batch producer
│   │   └── dataset_loader.py           # PaySim/Kaggle normalizer
│   │
│   ├── bronze_layer/                   #  Lambda: Kinesis → S3
│   │   ├── handler.py                  # Lambda entry point
│   │   ├── validator.py                # Pydantic validation
│   │   ├── deduplicator.py             # DynamoDB idempotency
│   │   └── s3_writer.py                # Parquet writer (date/hour partitions)
│   │
│   ├── silver_layer/                   #  Glue: Feature engineering
│   │   └── job.py                      # PySpark: velocity + aggregates + PII hash
│   │
│   ├── gold_layer/                     #  Glue: Training data
│   │   └── job.py                      # PySpark: point-in-time features
│   │
│   ├── ml_training/                    #  Model training
│   │   └── train.py                    # LR + XGBoost + LightGBM with MLflow
│   │
│   ├── api/                            #  FastAPI scoring service
│   │   └── main.py                     # POST /score, GET /alerts, POST /feedback
│   │
│   ├── drift_monitor/                  #  Lambda: PSI calculation
│   │   └── handler.py                  # Daily drift check → trigger retrain
│   │
│   └── common/                         #  Shared utilities
│       ├── config.py                   # Environment config (singleton)
│       ├── logger.py                   # Structured JSON logging
│       ├── metrics.py                  # CloudWatch metrics client
│       └── aws_clients.py              # Boto3 factory with retry logic
│
├── infrastructure/                     #  AWS CDK (TypeScript)
│   ├── bin/app.ts                      # CDK app entry point
│   └── lib/
│       ├── kinesis-stack.ts            # Kinesis + Lambda + S3
│       ├── database-stack.ts           # DynamoDB tables
│       ├── api-stack.ts                # ECS Fargate + ALB
│       └── monitoring-stack.ts         # CloudWatch dashboards + alarms
│
├── frontend/                           #  React + TypeScript
│   └── src/
│       └── pages/
│           └── AlertsList.tsx          # Fraud alerts dashboard
│
├── tests/
│   ├── unit/                           # PyTest unit tests
│   ├── integration/                    # Integration tests with moto
│   └── load/                           # API load testing
│
├── requirements.txt                    # Python dependencies
├── Dockerfile                          # Multi-stage FastAPI image
└── docker-compose.yml                  # LocalStack for dev
```

---

##  Data Flow

```
1. DATA INGESTION
   PaySim Dataset → Python Producer → Kinesis Stream
   (1000 events/sec, partitioned by user_id)
   
2. BRONZE LAYER (Real-time)
   Kinesis → Lambda → Pydantic Validation → DynamoDB Dedupe → S3 Parquet
   (Latency: <1 minute, exactly-once processing)
   
3. SILVER LAYER (Batch)
   EventBridge (hourly) → Glue PySpark Job
   ├─ Velocity features (5m, 1h, 24h windows)
   ├─ User/merchant aggregates
   ├─ PII tokenization (SHA256 + salt)
   └─ Write to S3 (partitioned Parquet)
   
4. GOLD LAYER (Batch)
   EventBridge (daily) → Glue PySpark Job
   ├─ Point-in-time features (prevent leakage)
   ├─ Training dataset generation
   └─ Write to S3 (queryable via Athena)
   
5. ML TRAINING
   Gold S3 → Python Script → MLflow Tracking
   ├─ Logistic Regression (baseline)
   ├─ XGBoost (production model)
   ├─ LightGBM (comparison)
   └─ Best model → S3 (version controlled)
   
6. SERVING LAYER
   FastAPI (ECS Fargate) → Load Model from S3
   ├─ POST /score → Fraud probability + top features
   ├─ GET /alerts → Recent high-risk transactions
   └─ POST /feedback → Analyst decisions
   
7. MONITORING
   EventBridge (daily) → Drift Monitor Lambda
   ├─ Calculate PSI for key features (Athena query)
   ├─ If PSI > 0.25 → Trigger Step Functions (retrain)
   └─ Emit CloudWatch metrics
```

---

## Quick Start

### Prerequisites
- AWS Account with Admin access
- AWS CLI configured (`aws configure`)
- Node.js 18+ (for CDK)
- Python 3.9+
- Docker Desktop

### 1. Clone Repository
```bash
git clone https://github.com/yourusername/fraud-detection-aws.git
cd fraud-detection-aws
```

### 2. Install Dependencies
```bash
# Python
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt

# AWS CDK
cd infrastructure
npm install
cd ..
```

### 3. Deploy Infrastructure
```bash
cd infrastructure
export ENVIRONMENT=dev
cdk bootstrap  # First time only
cdk deploy --all
cd ..
```

### 4. Generate Data & Train Model
```bash
# Send events to Kinesis
python src/data_producer/producer.py \
    --dataset data/paysim.csv \
    --stream-name fraud-transactions-dev \
    --rate 100

# Run Glue jobs (wait ~5 min)
aws glue start-job-run --job-name fraud-silver-job-dev
aws glue start-job-run --job-name fraud-gold-job-dev

# Train models
python src/ml_training/train.py \
    --gold-path s3://fraud-gold-dev/training/ \
    --mlflow-uri http://localhost:5000
```

### 5. Test API
```bash
# Get ALB URL from CDK output
curl -X POST http://<ALB-URL>/api/v1/score \
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
```

### 6. Launch Frontend
```bash
cd frontend
npm install
npm start
# Open http://localhost:3000
```

**Full Guide**: See [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)

---

##  Cost Analysis

### Development Environment (~$90/month)

| Service | Specification | Monthly Cost |
|---------|--------------|--------------|
| **Kinesis** | 1 shard × 730 hr | $11.00 |
| **S3** | 10 GB storage + 10 GB transfer | $1.50 |
| **DynamoDB** | On-demand (1M writes) | $1.25 |
| **Lambda** | 1M invocations, 512 MB, 60s | $0.83 |
| **Glue** | 2 DPU-hours/day × 30 days | $26.40 |
| **ECS Fargate** | 2 tasks × 0.5 vCPU × 730 hr | $29.20 |
| **ALB** | 730 hr + 1 GB processed | $17.00 |
| **CloudWatch** | 5 GB logs + 10 metrics | $3.50 |
| **Total** | | **~$90/month** |

### Production Environment (~$400-500/month)

- Scale Kinesis to 5 shards
- ECS auto-scaling to 10 tasks
- DynamoDB provisioned capacity
- Reserved Capacity for predictable loads

**Cost Optimization**:
- S3 Intelligent Tiering (30% savings on old data)
- Glue job consolidation (combine Silver/Gold)
- Lambda provisioned concurrency (eliminate cold starts)
- Spot instances for ML training

---

## Tech Stack

### Backend
- **Language**: Python 3.11
- **API**: FastAPI 0.108
- **ML**: scikit-learn, XGBoost, LightGBM
- **Data**: Pandas, PyArrow (Parquet)
- **Validation**: Pydantic 2.5

### Frontend
- **Framework**: React 18 + TypeScript 5.2
- **UI**: Material-UI (MUI)
- **Charts**: Recharts
- **API**: Axios with typed client

### Infrastructure
- **IaC**: AWS CDK (TypeScript)
- **Containers**: Docker multi-stage builds
- **AWS Services**: Kinesis, Lambda, Glue, ECS, S3, DynamoDB, Athena

### ML Ops
- **Tracking**: MLflow 2.9
- **Drift**: PSI (Population Stability Index)
- **Orchestration**: Step Functions
- **Monitoring**: CloudWatch + custom metrics

### Testing
- **Unit**: PyTest + moto (AWS mocking)
- **Integration**: LocalStack
- **Load**: Locust (API testing)

---

## Key Features

### 1. **Exactly-Once Processing**
- DynamoDB idempotency table with conditional writes
- 24-hour TTL for automatic cleanup
- Composite key: `transaction_id#event_id`

### 2. **Real-Time Feature Engineering**
- Velocity windows: 5m, 1h, 24h
- User aggregates: lifetime transactions, average amount
- Merchant stats: fraud rate, transaction count

### 3. **PII Protection**
- SHA256 hashing with salt (Secrets Manager)
- Original IDs in Bronze (S3 encrypted)
- Hashed IDs in Silver/Gold

### 4. **Point-in-Time Correctness**
- Event timestamp (not processing timestamp)
- Prevents train/serve skew
- `asof_join` in Spark for historical features

### 5. **Automated Drift Detection**
- Daily PSI calculation (7 key features)
- Athena queries for current data vs. baseline
- Step Functions retraining workflow

### 6. **Explainable AI**
- Top contributing features per prediction
- SHAP values (optional)
- Feature importance from XGBoost

### 7. **Auto-Scaling**
- Kinesis: 1-10 shards based on throughput
- ECS: 2-10 tasks based on CPU/memory
- DynamoDB: On-demand (auto-scales)

---

## Success Metrics

| Metric | Target | Implementation |
|--------|--------|----------------|
| **Latency (p95)** | <200ms | ECS Fargate (no cold starts) |
| **Throughput** | 1000 events/sec | 1 Kinesis shard |
| **Accuracy (PR-AUC)** | >0.80 | XGBoost with class balancing |
| **False Positive Rate** | <1% | Threshold tuning (precision@90% recall) |
| **Uptime** | 99.9% | Multi-AZ ECS, health checks |
| **Data Freshness** | <5 min | Hourly Glue jobs, real-time Bronze |

---

## Documentation

- **[GETTING_STARTED.md](docs/GETTING_STARTED.md)**: Step-by-step setup guide
- **[ARCHITECTURE_ANALYSIS.md](docs/ARCHITECTURE_ANALYSIS.md)**: Design patterns deep-dive
- **[ADR.md](docs/ADR.md)**: Architecture Decision Records with trade-offs
- **[RUNBOOK.md](docs/RUNBOOK.md)**: Operations guide for production
- **[API Reference](http://localhost:8000/docs)**: Auto-generated OpenAPI/Swagger UI

---

## Learning Outcomes

This project demonstrates:

 **Event-Driven Microservices**: Kinesis, Lambda, EventBridge, async processing  
 **SOLID Principles**: Single responsibility, dependency inversion, interface segregation  
 **Design Patterns**: 12+ patterns (Factory, Singleton, Strategy, CQRS, Saga, etc.)  
 **Data Engineering**: Medallion architecture (Bronze/Silver/Gold), PySpark at scale  
 **ML Engineering**: Feature engineering, MLflow tracking, drift monitoring  
 **Cloud Architecture**: AWS serverless, IaC with CDK, cost optimization  
 **API Development**: FastAPI, Pydantic validation, async endpoints  
 **Frontend**: React + TypeScript, typed API client, Material-UI  
 **DevOps**: Docker, multi-stage builds, CI/CD-ready  
 **Observability**: Structured logging, CloudWatch metrics, alarms  

---

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## License

MIT License - see [LICENSE](LICENSE) file

---

##  Contact

**Heena Khan** - hkhan520@umd.edu

Project Link: [https://github.com/yourusername/fraud-detection-aws](https://github.com/yourusername/fraud-detection-aws)

---

## Acknowledgments

- **Dataset**: [PaySim Synthetic Financial Dataset](https://www.kaggle.com/datasets/ealaxi/paysim1)
- **Architecture**: AWS Well-Architected Framework
- **ML Best Practices**: Google's ML Engineering guidelines
- **Design Patterns**: Gang of Four (GoF) + Cloud Patterns

---

