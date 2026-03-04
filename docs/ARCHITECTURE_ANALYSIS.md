# Architecture Analysis: Design Patterns & Principles

## 🏛️ Architecture Type

This fraud detection system is a **hybrid architecture** combining multiple paradigm patterns:

### Primary: **Event-Driven Architecture (EDA)**
- **Event Producers**: Kinesis producer sends transaction events
- **Event Stream**: Kinesis Data Streams acts as event backbone
- **Event Consumers**: Bronze Lambda, Glue jobs react to events
- **Event Triggers**: EventBridge schedules (Glue jobs, drift monitoring)
- **Event Sourcing**: All events stored in Bronze layer (immutable log)

### Secondary: **Microservices Architecture**
Each service has a single, well-defined responsibility:

| Microservice | Responsibility | Technology |
|--------------|---------------|------------|
| **Data Producer** | Event generation | Python + Kinesis SDK |
| **Bronze Service** | Ingestion + validation | Lambda |
| **Silver Service** | Feature engineering | Glue PySpark |
| **Gold Service** | Training data prep | Glue PySpark |
| **Scoring Service** | Real-time predictions | FastAPI on ECS |
| **Drift Monitor** | Model monitoring | Lambda + Athena |
| **Alert Service** | Fraud notifications | DynamoDB Streams |

**Microservice Characteristics**:
- ✅ Independent deployment (each Lambda/ECS service)
- ✅ Decoupled via events (Kinesis, EventBridge)
- ✅ Polyglot persistence (S3, DynamoDB, Kinesis)
- ✅ Single responsibility per service
- ✅ API-driven communication (FastAPI REST)

### Tertiary: **Lambda Architecture**
Combines batch and stream processing:

```
┌─────────────────────────────────────────┐
│         Speed Layer (Stream)            │
│  Kinesis → Lambda → Bronze S3           │
│  (Real-time, <1 min latency)            │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│         Batch Layer                     │
│  EventBridge → Glue (Silver/Gold)       │
│  (Hourly/Daily batch processing)        │
└─────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────┐
│         Serving Layer                   │
│  FastAPI → Model → Predictions          │
│  (Real-time API, <200ms)                │
└─────────────────────────────────────────┘
```

### Data Engineering: **Medallion Architecture**
Multi-hop architecture for data quality:

- **Bronze** (Raw): Validated events, Parquet format
- **Silver** (Cleansed): Features, PII tokenized, aggregates
- **Gold** (Curated): Point-in-time training data, optimized for ML

---

## 🎨 Design Patterns Implemented

### 1. **Producer-Consumer Pattern**
**Location**: `src/data_producer/producer.py` → Kinesis → `src/bronze_layer/handler.py`

```python
# Producer
class KinesisProducer:
    def send_batch(self, events):  # Produces events
        self.kinesis.put_records(...)

# Consumer
def lambda_handler(event, context):  # Consumes from Kinesis
    for record in event['Records']:
        process_event(record)
```

**Benefits**: Decouples data generation from processing

---

### 2. **Repository Pattern**
**Location**: `src/bronze_layer/s3_writer.py`, `src/bronze_layer/deduplicator.py`

```python
# S3 as data repository
class S3ParquetWriter:
    def write_batch(self, events):  # Abstracts storage details
        df = pd.DataFrame(events)
        table = pa.Table.from_pandas(df)
        pq.write_table(table, buffer)
        self.s3_client.put_object(...)

# DynamoDB as deduplication repository
class Deduplicator:
    def is_duplicate(self, transaction_id):  # Abstracts query logic
        response = self.table.get_item(Key=...)
        return 'Item' in response
```

**Benefits**: Abstracts data access, enables testing with mocks

---

### 3. **Factory Pattern**
**Location**: `src/common/aws_clients.py`

```python
class AWSClients:
    def get_client(self, service_name: str):
        """Factory method for AWS service clients"""
        if service_name not in self._clients:
            self._clients[service_name] = boto3.client(
                service_name,
                config=self.boto_config  # Shared configuration
            )
        return self._clients[service_name]
    
    @property
    def s3(self):
        return self.get_client('s3')  # Factory creates lazily
```

**Benefits**: Centralized client creation, connection pooling

---

### 4. **Singleton Pattern**
**Location**: `src/common/config.py`, `src/common/metrics.py`, `src/common/logger.py`

```python
# Global singleton instance
_config: Optional[Config] = None

def get_config() -> Config:
    """Get singleton config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config
```

**Benefits**: Single configuration instance, consistent state

---

### 5. **Strategy Pattern**
**Location**: `src/ml_training/train.py`

```python
class FraudModelTrainer:
    def train_logistic_regression(self, X, y):
        """Strategy 1: Simple baseline"""
        model = LogisticRegression(...)
        return model.fit(X, y)
    
    def train_xgboost(self, X, y):
        """Strategy 2: Production model"""
        model = xgb.XGBClassifier(...)
        return model.fit(X, y)
    
    def train_lightgbm(self, X, y):
        """Strategy 3: Alternative"""
        model = lgb.LGBMClassifier(...)
        return model.fit(X, y)
```

**Benefits**: Easily swap/compare ML algorithms

---

### 6. **Decorator Pattern**
**Location**: `src/data_producer/schemas.py`, `src/common/metrics.py`

```python
# Pydantic decorators for validation
class TransactionEvent(BaseModel):
    @validator('amount')
    def validate_amount(cls, v):  # Decorates field validation
        if v < 0.01:
            raise ValueError('Amount must be >= 0.01')
        return v

# Timing decorator
class Timer:
    """Context manager decorator for timing"""
    def __enter__(self):
        self.start_time = datetime.now()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (datetime.now() - self.start_time).total_seconds()
        emit_timer(self.metric_name, elapsed)

# Usage
with Timer('ProcessingTime'):
    process_data()
```

**Benefits**: Clean separation of concerns (validation, timing)

---

### 7. **Observer Pattern**
**Location**: EventBridge → Lambda triggers

```yaml
# EventBridge rules observe schedule events
DriftMonitorRule:
  Schedule: cron(0 1 * * ? *)  # Daily at 1 AM
  Target: DriftMonitorLambda   # Notifies observer

# DynamoDB Streams observe table changes
AlertsTableStream:
  ViewType: NEW_AND_OLD_IMAGES
  Consumers:
    - AlertNotificationLambda  # Observers react to changes
```

**Benefits**: Decoupled event handling, extensible

---

### 8. **Circuit Breaker Pattern**
**Location**: Lambda retry configuration, Boto3 retries

```typescript
// CDK Lambda configuration
new lambda.Function(this, 'BronzeLayerFunction', {
  retryAttempts: 3,  // Circuit breaker on failures
  onFailure: new SqsDestination(dlq)  // Dead letter queue
});
```

```python
# Boto3 adaptive retry mode (built-in circuit breaker)
BotoConfig(
    retries={
        'max_attempts': 3,
        'mode': 'adaptive'  # Backs off automatically
    }
)
```

**Benefits**: Fault tolerance, prevents cascading failures

---

### 9. **Idempotency Pattern**
**Location**: `src/bronze_layer/deduplicator.py`

```python
def mark_processed(self, transaction_id: str, event_id: str):
    """Idempotent write using DynamoDB conditional expression"""
    try:
        self.table.put_item(
            Item={
                'composite_key': f"{transaction_id}#{event_id}",
                'processed_at': datetime.now().isoformat(),
                'expires_at': int(time.time()) + 86400  # 24h TTL
            },
            ConditionExpression='attribute_not_exists(composite_key)'
        )
        return True
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            return False  # Already processed (idempotent)
```

**Benefits**: Exactly-once processing, prevents duplicates

---

### 10. **CQRS (Command Query Responsibility Segregation)**
**Location**: API endpoints, DynamoDB tables

```python
# WRITE PATH (Commands)
@app.post("/api/v1/score")
async def score_transaction(txn: TransactionRequest):
    """Command: Score and store alert"""
    score = model.predict(txn)
    if score.is_fraud:
        save_alert(txn, score)  # Write to alerts table
    return score

# READ PATH (Queries)
@app.get("/api/v1/alerts")
async def list_alerts(status: str = None):
    """Query: Read from alerts table (optimized for reads)"""
    return query_alerts_table(status)
```

**Separate tables for different access patterns**:
- **Alerts Table**: Optimized for reads (GSI on status)
- **Feedback Table**: Optimized for writes (time-series)
- **Dedupe Table**: Optimized for fast lookups (TTL)

**Benefits**: Optimized read/write paths, scalability

---

### 11. **Saga Pattern** (Distributed Transactions)
**Location**: Step Functions retraining workflow

```json
{
  "Comment": "Automated model retraining saga",
  "StartAt": "RunGoldLayerJob",
  "States": {
    "RunGoldLayerJob": {
      "Type": "Task",
      "Resource": "arn:aws:glue:...:job/fraud-gold-job",
      "Next": "WaitForJobCompletion",
      "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "RollbackNotification"}]
    },
    "WaitForJobCompletion": {
      "Type": "Wait",
      "Seconds": 300,
      "Next": "TrainModel"
    },
    "TrainModel": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:...:function:model-trainer",
      "Next": "EvaluateModel",
      "Retry": [{"ErrorEquals": ["States.ALL"], "MaxAttempts": 3}]
    },
    "EvaluateModel": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:...:function:model-evaluator",
      "Next": "DeployIfBetter"
    },
    "DeployIfBetter": {
      "Type": "Choice",
      "Choices": [{
        "Variable": "$.pr_auc",
        "NumericGreaterThan": 0.8,
        "Next": "DeployModel"
      }],
      "Default": "SkipDeployment"
    },
    "DeployModel": {
      "Type": "Task",
      "Resource": "arn:aws:lambda:...:function:model-deployer",
      "End": true
    },
    "RollbackNotification": {
      "Type": "Task",
      "Resource": "arn:aws:sns:...:topic/ml-team",
      "End": true
    }
  }
}
```

**Benefits**: Manages complex workflows with compensation logic

---

### 12. **Adapter Pattern**
**Location**: Dataset normalizers

```python
# Adapter: Converts different dataset formats to unified schema
def normalize_paysim(df: pd.DataFrame) -> pd.DataFrame:
    """Adapter for PaySim dataset"""
    return pd.DataFrame({
        'transaction_id': df['step'].astype(str) + '_' + df['nameOrig'],
        'amount': df['amount'],
        'user_id': df['nameOrig'],
        'merchant_id': df['nameDest'],
        # ... map PaySim schema to TransactionEvent
    })

def normalize_kaggle_cc(df: pd.DataFrame) -> pd.DataFrame:
    """Adapter for Kaggle Credit Card dataset"""
    return pd.DataFrame({
        'transaction_id': 'kaggle_' + df.index.astype(str),
        'amount': df['Amount'],
        # ... map Kaggle schema to TransactionEvent
    })
```

**Benefits**: Support multiple data sources transparently

---

## 🔧 SOLID Principles

### ✅ **S - Single Responsibility Principle**

Each component has ONE reason to change:

| Component | Single Responsibility |
|-----------|----------------------|
| `validator.py` | Schema validation only |
| `deduplicator.py` | Idempotency checks only |
| `s3_writer.py` | S3 Parquet writes only |
| `producer.py` | Kinesis event production only |
| `config.py` | Configuration management only |
| `logger.py` | Logging only |
| `metrics.py` | Metrics emission only |

**Example**:
```python
# BAD: Multiple responsibilities
class BronzeProcessor:
    def process(self, event):
        self.validate(event)      # Validation
        self.dedupe(event)        # Deduplication
        self.write_s3(event)      # Storage
        self.log(event)           # Logging
        self.emit_metrics(event)  # Metrics

# GOOD: Single responsibility (our implementation)
class BronzeLayerHandler:
    def __init__(self):
        self.validator = Validator()        # Delegates validation
        self.deduplicator = Deduplicator()  # Delegates deduplication
        self.s3_writer = S3Writer()         # Delegates storage
        self.logger = get_logger(__name__)  # Delegates logging
    
    def process(self, event):
        validated = self.validator.validate(event)
        if not self.deduplicator.is_duplicate(validated['id']):
            self.s3_writer.write(validated)
```

---

### ✅ **O - Open/Closed Principle**

Open for extension, closed for modification:

**Example 1: Schema Versioning**
```python
# Can add new schema versions without modifying existing code
class TransactionEvent(BaseModel):
    schema_version: str = "1.0"
    # ... fields ...

# Future: Add v2.0 without breaking v1.0
class TransactionEventV2(TransactionEvent):
    schema_version: str = "2.0"
    new_field: Optional[str] = None
```

**Example 2: ML Model Strategies**
```python
# Can add new models without modifying FraudModelTrainer
class FraudModelTrainer:
    def run_training(self):
        # Open for extension: add new methods
        self.train_logistic_regression()
        self.train_xgboost()
        self.train_lightgbm()
        # self.train_neural_network()  # Future addition
```

**Example 3: Configuration Extension**
```python
# Environment variables can be added without code changes
class Config:
    # Existing config
    bronze_bucket: str = os.getenv('BRONZE_BUCKET', 'default')
    
    # New config added later (doesn't break existing code)
    enable_encryption: bool = os.getenv('ENABLE_ENCRYPTION', 'true') == 'true'
```

---

### ✅ **L - Liskov Substitution Principle**

Subtypes must be substitutable for their base types:

**Example: Logger Substitution**
```python
# Abstract logger interface (implicit in Python)
def get_logger(name: str, use_json: bool = True):
    logger = logging.getLogger(name)
    
    if use_json:
        handler.setFormatter(JSONFormatter())  # JSON logger
    else:
        handler.setFormatter(StandardFormatter())  # Standard logger
    
    return logger

# Both formatters are substitutable
json_logger = get_logger('service', use_json=True)
std_logger = get_logger('service', use_json=False)

# Both work identically
json_logger.info("Message")  # Works
std_logger.info("Message")   # Works (same interface)
```

**Example: AWS Clients**
```python
# Any AWS client can be substituted
clients = get_aws_clients()

# All follow same boto3 interface
s3 = clients.s3        # Can substitute with mock_s3
dynamo = clients.dynamodb  # Can substitute with mock_dynamodb

# LocalStack mocks are substitutable
import moto
with moto.mock_s3():
    s3_client = boto3.client('s3')  # Mock is substitutable for real client
```

---

### ✅ **I - Interface Segregation Principle**

Clients shouldn't depend on interfaces they don't use:

**Example 1: Focused Interfaces**
```python
# BAD: Fat interface
class DataProcessor:
    def validate(self, event): ...
    def deduplicate(self, event): ...
    def write_s3(self, event): ...
    def write_dynamodb(self, event): ...
    def send_sns(self, event): ...
    def update_cache(self, event): ...
    # Client must implement all even if only needs validate()

# GOOD: Segregated interfaces (our implementation)
class Validator:
    def validate(self, event): ...  # Only validation methods

class Deduplicator:
    def is_duplicate(self, id): ...  # Only deduplication methods
    def mark_processed(self, id): ...

class S3Writer:
    def write_batch(self, events): ...  # Only S3 methods
```

**Example 2: Metrics Client**
```python
# Focused interface - clients use only what they need
metrics = get_metrics_client()

# Service A only needs counters
emit_counter('requests', 1)

# Service B only needs timers
with Timer('processing_time'):
    process_data()

# Service C only needs gauges
emit_gauge('queue_size', 42)
```

---

### ✅ **D - Dependency Inversion Principle**

Depend on abstractions, not concretions:

**Example 1: Configuration Abstraction**
```python
# HIGH-LEVEL: Lambda handler
def lambda_handler(event, context):
    config = get_config()  # Depends on abstraction
    
    # Doesn't know WHERE config comes from:
    # - Environment variables? ✓
    # - AWS Parameter Store? Could be
    # - Secrets Manager? Could be
    bucket = config.bronze_bucket

# LOW-LEVEL: Config implementation
class Config:
    bronze_bucket: str = os.getenv('BRONZE_BUCKET', 'default')
    # Implementation details hidden from handler
```

**Example 2: Storage Abstraction**
```python
# HIGH-LEVEL: Business logic
def save_events(events):
    writer = S3ParquetWriter(bucket='...')
    writer.write_batch(events)  # Depends on abstraction (write_batch)

# LOW-LEVEL: Storage implementation
class S3ParquetWriter:
    def write_batch(self, events):
        # Could swap implementation:
        # - S3 Parquet (current)
        # - S3 JSON
        # - Database
        # - Local file system
        # Business logic doesn't care!
```

**Example 3: AWS Clients Abstraction**
```python
# HIGH-LEVEL: Business logic
def process_data():
    clients = get_aws_clients()  # Abstraction
    s3 = clients.s3
    s3.put_object(...)

# LOW-LEVEL: Implementation can change
# - Real AWS (production)
# - LocalStack (development)
# - Moto (testing)
# Business logic unchanged!
```

---

## 🏗️ Architecture Summary

### **NOT Monolithic** ❌
This is NOT a monolithic architecture because:
- Multiple independently deployable services (Lambda, ECS, Glue)
- Decoupled via events (Kinesis, EventBridge)
- Polyglot data stores (S3, DynamoDB, Kinesis)
- Scalable components (each scales independently)

### **NOT Traditional Client-Server** ❌
While FastAPI is client-server, the overall system is:
- Event-driven (Kinesis as message bus)
- Asynchronous processing (Lambda, Glue)
- Distributed state (S3, DynamoDB)

### **YES: Event-Driven Microservices** ✅
Primary characteristics:
- **Event-Driven**: Events trigger processing (Kinesis, EventBridge)
- **Microservices**: Independent, single-purpose services
- **Serverless**: Lambdas, managed services (no server management)
- **Lambda Architecture**: Batch + stream processing
- **Medallion**: Layered data quality (Bronze/Silver/Gold)

---

## 📊 Architecture Decision Comparison

| Characteristic | This System | Monolithic | Traditional Microservices |
|----------------|-------------|------------|---------------------------|
| **Deployment** | Independent per service ✓ | Single deployment ✗ | Independent ✓ |
| **Scaling** | Per-service auto-scaling ✓ | Entire app scales ✗ | Per-service ✓ |
| **Communication** | Events + REST ✓ | In-process ✗ | REST/gRPC ✓ |
| **Data** | Polyglot persistence ✓ | Shared database ✗ | Polyglot ✓ |
| **Fault Isolation** | Service failures isolated ✓ | Single point of failure ✗ | Isolated ✓ |
| **Technology** | Python + TypeScript + PySpark ✓ | Single stack ✗ | Polyglot ✓ |
| **Serverless** | Heavy use (Lambda, Glue) ✓ | N/A | Optional |
| **Event-Driven** | Core pattern ✓ | N/A | Optional |

---

## 🎯 Key Takeaways

This fraud detection system is a **modern, cloud-native architecture** that:

1. **Follows Event-Driven Microservices pattern** with serverless components
2. **Implements 12+ design patterns** (Producer-Consumer, Repository, Factory, Singleton, Strategy, Decorator, Observer, Circuit Breaker, Idempotency, CQRS, Saga, Adapter)
3. **Adheres to all 5 SOLID principles** with clean separation of concerns
4. **Uses Lambda Architecture** for real-time + batch processing
5. **Implements Medallion Architecture** for data quality progression
6. **Enables independent scaling** of each component (ECS, Lambda, Glue)
7. **Supports fault tolerance** via circuit breakers, retries, and dead-letter queues
8. **Ensures exactly-once processing** through idempotency patterns

---

## 📚 References

- **Design Patterns**: Gang of Four (GoF) patterns adapted for cloud
- **SOLID Principles**: Robert C. Martin (Uncle Bob)
- **Event-Driven Architecture**: Martin Fowler
- **Lambda Architecture**: Nathan Marz
- **Medallion Architecture**: Databricks
- **AWS Well-Architected Framework**: Operational excellence, security, reliability, performance, cost optimization

