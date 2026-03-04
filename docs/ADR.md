# Architecture Decision Records (ADRs)

Document key architectural decisions for the AWS-Native Fraud Detection Pipeline.

---

## ADR-001: Use AWS Kinesis Instead of Apache Kafka

**Status**: Accepted  
**Date**: 2026-03-03  
**Deciders**: Architecture Team

### Context
Need a streaming platform for real-time transaction ingestion with 1000+ events/sec throughput.

### Decision
Use **AWS Kinesis Data Streams** instead of self-managed Apache Kafka.

### Rationale
**Pros of Kinesis:**
- Fully managed (no cluster operations, auto-scaling)
- Native AWS integration (Lambda triggers, IAM, CloudWatch)
- Cost-effective at our scale (1 shard = $11/month vs. 3-broker Kafka cluster ~$300/month)
- Built-in data retention (24 hours default, up to 365 days)
- Encryption at rest (KMS) and in transit (TLS 1.2)

**Cons:**
- Less throughput per shard (1 MB/sec write, 2 MB/sec read) vs. Kafka partitions
- Proprietary AWS service (vendor lock-in)
- Limited ecosystem compared to Kafka (no Kafka Streams, ksqlDB)

**Trade-off Accepted:**
Our throughput requirement (1000 events/sec × 1 KB = 1 MB/sec) fits within 1 shard. Kafka's superior throughput and ecosystem are not needed.

### Consequences
- Reduced operational burden (no Kafka cluster management)
- Lower costs in dev/staging environments
- Tighter AWS coupling (migration to Kafka would require code changes)

### Alternatives Considered
1. **Apache Kafka on MSK**: ~$300/month for 3 brokers, overkill for our scale
2. **Amazon SQS**: Not suitable for streaming use case (no ordering guarantees, 14-day max retention)

---

## ADR-002: Deploy FastAPI on ECS Fargate Instead of Lambda

**Status**: Accepted  
**Date**: 2026-03-03

### Context
Need to deploy a fraud scoring API with <200ms p95 latency and 1000 RPS peak throughput.

### Decision
Use **ECS Fargate** with Application Load Balancer instead of AWS Lambda.

### Rationale
**Why NOT Lambda:**
- Cold start penalty (500ms-2s) exceeds latency budget
- 512 MB memory limit requires careful model optimization
- 15-minute max execution time not an issue for API, but cold starts are

**Why ECS Fargate:**
- Always warm (no cold starts)
- Predictable latency (p95 < 200ms achieved in testing)
- Flexible resource allocation (1 vCPU, 2 GB RAM per task)
- Native load balancing (ALB with health checks)
- Docker container portability (run locally or on any cloud)

**Cost Comparison (10 tasks, 0.5 vCPU, 1 GB RAM):**
- ECS Fargate: $29/month (0.5 vCPU × $0.04 × 730hr)
- Lambda (1M requests, 512 MB, 200ms avg): $3.50/month

**Trade-off:**
We pay **8x more** for ECS but get consistent sub-200ms latency. For a production fraud detection system, this is acceptable.

### Consequences
- Higher baseline cost (ECS runs 24/7)
- More complex deployment (Docker build, ECR, ECS task definitions)
- Better observability (CloudWatch Container Insights)

### Alternatives Considered
1. **Lambda + Provisioned Concurrency**: Still has warm-up time, costs ~$350/month for 10 instances
2. **API Gateway + Lambda**: Same cold start issues
3. **EC2 behind ALB**: Cheaper but requires OS patching, security updates

---

## ADR-003: Use DynamoDB for Deduplication Instead of Redis

**Status**: Accepted  
**Date**: 2026-03-03

### Context
Need idempotent event processing (exactly-once semantics) for Kinesis → S3 pipeline.

### Decision
Use **DynamoDB** with conditional writes for deduplication, not Redis or in-memory cache.

### Rationale
**DynamoDB Advantages:**
- **Serverless**: No cluster management (vs. ElastiCache Redis)
- **Conditional writes**: `PutItem` with `attribute_not_exists` ensures atomicity
- **TTL**: Auto-delete old records (24-hour retention) without manual cleanup
- **Cost**: On-demand $1.25/1M writes vs. ElastiCache ~$15/month (t3.micro)

**Redis Disadvantages:**
- Requires cluster setup (single point of failure if not replicated)
- Manual TTL implementation
- Overkill for simple key existence checks

**Design:**
```
DynamoDB Table: fraud-dedupe-dev
Partition Key: composite_key (transaction_id#event_id)
TTL Attribute: expires_at (current_time + 24h)
```

**Deduplication Logic:**
```python
try:
    dynamodb.put_item(
        Item={'composite_key': f"{txn_id}#{event_id}", 'processed_at': now()},
        ConditionExpression='attribute_not_exists(composite_key)'
    )
    return False  # Not duplicate
except ConditionalCheckFailedException:
    return True  # Duplicate detected
```

### Consequences
- Slightly higher latency (10ms DynamoDB vs. 1ms Redis)
- Simpler architecture (one less service to manage)
- Lower cost at our scale

### Alternatives Considered
1. **Redis in ElastiCache**: Faster but adds ~$180/year cost + operational burden
2. **In-memory deduplication**: Lost on Lambda restart
3. **S3 head_object checks**: Too slow (50-100ms), high cost

---

## ADR-004: Use PySpark (Glue) for Feature Engineering, Not Pandas

**Status**: Accepted  
**Date**: 2026-03-03

### Context
Need to compute velocity features (5m/1h/24h windows) and user/merchant aggregates over 10M+ transactions.

### Decision
Use **AWS Glue with PySpark** for Silver/Gold layer transformations instead of Pandas in Lambda.

### Rationale
**Why PySpark:**
- **Scalability**: Distributed processing (Glue auto-scales to 10 DPUs)
- **Window functions**: Native support for sliding/tumbling windows
- **Partitioned reads**: Efficiently read Bronze Parquet with predicate pushdown
- **Cost**: $0.44/DPU-hour, 2 DPU-hours/day = $26/month

**Pandas Limitations:**
- Single-threaded (cannot process 10M rows efficiently)
- Memory-bound (Lambda max 10 GB not enough for large datasets)
- Complex window logic requires custom groupby/rolling operations

**Example PySpark Velocity Window:**
```python
from pyspark.sql import Window
window_spec = (
    Window.partitionBy('user_id')
    .orderBy(col('timestamp').cast('long'))
    .rangeBetween(-300, 0)  # Last 5 minutes
)
df = df.withColumn(
    'user_txn_count_5m',
    count('transaction_id').over(window_spec) - 1  # Exclude current
)
```

### Consequences
- Learning curve (PySpark SQL API vs. Pandas)
- Job startup time (2-3 minutes Glue cold start)
- Better for batch, not real-time (acceptable for our daily ETL)

### Alternatives Considered
1. **Pandas in Lambda**: Works for <1M rows, fails at scale
2. **EMR Spark**: More flexible but requires cluster management (~$500/month)
3. **Athena + CTAS**: SQL-based, but less flexible for complex transformations

---

## ADR-005: Use Logistic Regression as Baseline, XGBoost as Production Model

**Status**: Accepted  
**Date**: 2026-03-03

### Context
Need a fraud detection model with high recall (catch 90%+ frauds) and explainability.

### Decision
Train three models:
1. **Logistic Regression**: Baseline (interpretable, fast)
2. **XGBoost**: Production candidate (best performance)
3. **LightGBM**: Comparison benchmark

Select model based on **PR-AUC** (prioritizes precision/recall over ROC-AUC for imbalanced data).

### Rationale
**Why Logistic Regression as Baseline:**
- Interpretable (linear coefficients)
- Fast to train (<1 min) and predict (<10ms)
- Good for establishing performance floor

**Why XGBoost for Production:**
- Handles non-linear patterns (user behavior, merchant risk)
- Built-in handling of imbalanced data (`scale_pos_weight`)
- Feature importance via SHAP
- Industry standard (used by Stripe, PayPal)

**Model Comparison (Expected):**
| Model               | PR-AUC | ROC-AUC | Training Time |
|---------------------|--------|---------|---------------|
| Logistic Regression | 0.65   | 0.78    | 30s           |
| XGBoost             | 0.82   | 0.91    | 5m            |
| LightGBM            | 0.80   | 0.90    | 3m            |

**Decision Criteria:**
- If XGBoost PR-AUC > Logistic Regression by >0.10, deploy XGBoost
- If performance is similar, prefer Logistic Regression (explainability)

### Consequences
- Need SHAP for XGBoost explanations (adds 50ms latency)
- Retraining takes 5-10 minutes (acceptable for daily schedule)

### Alternatives Considered
1. **Neural Networks**: Overkill for tabular data, need large dataset
2. **Random Forest**: Slower than XGBoost, similar performance
3. **CatBoost**: Great for categorical features but less industry adoption

---

## ADR-006: Use MLflow for Experiment Tracking, Not SageMaker

**Status**: Accepted  
**Date**: 2026-03-03

### Context
Need to track model experiments, hyperparameters, metrics, and artifacts.

### Decision
Use **MLflow** (open-source) hosted on EC2, not Amazon SageMaker.

### Rationale
**MLflow Advantages:**
- **Open-source**: No vendor lock-in (portable to any cloud)
- **Simple**: Tracks experiments with `mlflow.log_param()`, `mlflow.log_metric()`
- **S3 artifact store**: Models saved to S3 (same as SageMaker)
- **Cost**: EC2 t3.medium (~$30/month) vs. SageMaker Experiments (no direct cost, but tied to SageMaker)

**SageMaker Experiments Disadvantages:**
- Tighter AWS coupling
- Requires SageMaker SDK (more complex than MLflow)
- Not needed since we're training locally/EC2 (not using SageMaker Training Jobs)

**Setup:**
```bash
# EC2 instance (t3.medium)
mlflow server \
    --backend-store-uri postgresql://mlflow:password@localhost/mlflow \
    --default-artifact-root s3://fraud-models-dev/mlflow-artifacts/ \
    --host 0.0.0.0
```

### Consequences
- Manual MLflow server management (EC2, PostgreSQL)
- Need to handle backups (RDS automated backups)

### Alternatives Considered
1. **SageMaker Experiments**: More integrated but proprietary
2. **Weights & Biases**: Excellent UI but adds external dependency
3. **Neptune.ai**: Similar to W&B, not needed for our scale

---

## ADR-007: Use SHA256 Tokenization for PII, Not Encryption

**Status**: Accepted  
**Date**: 2026-03-03

### Context
Need to protect user PII (user_id, merchant_id) while maintaining ability to join across datasets.

### Decision
Use **SHA256 hashing with secret salt** instead of AES encryption.

### Rationale
**Tokenization Requirements:**
- Deterministic (same user_id → same token)
- One-way (cannot reverse to original value)
- Collision-resistant
- Maintains join capability (Bronze → Silver → Gold)

**SHA256 with Salt:**
```python
import hashlib
salt = secrets_manager.get_secret('fraud-pii-salt')
hashed_user_id = hashlib.sha256(f"{user_id}{salt}".encode()).hexdigest()
```

**Why NOT Encryption (AES):**
- Reversible (requires key management, risk of exposure)
- Slower (encryption + decryption overhead)
- Not needed (we never need original user_id in analytics)

**Security Considerations:**
- Salt rotated quarterly (requires backfill with new hashes)
- Salt stored in AWS Secrets Manager (auto-rotation supported)
- Rainbow table attacks prevented by unique salt

### Consequences
- **Cannot reverse**: Analytics team sees hashed IDs only
- **Salt rotation complexity**: Must re-hash all historical data
- **Join capability preserved**: Same user → same hash

### Alternatives Considered
1. **AES-256 Encryption**: Reversible but unnecessary
2. **Format-Preserving Encryption**: Maintains structure but slower
3. **Pseudonymization Service**: Centralized token vault (adds latency)

---

## Summary Table

| ADR | Decision | Primary Reason |
|-----|----------|----------------|
| 001 | Kinesis over Kafka | Fully managed, cost-effective at scale |
| 002 | ECS Fargate over Lambda | Eliminate cold starts for <200ms latency |
| 003 | DynamoDB deduplication | Serverless, conditional writes, TTL |
| 004 | PySpark (Glue) for features | Distributed window functions, scalability |
| 005 | XGBoost as production model | Best PR-AUC for imbalanced data |
| 006 | MLflow over SageMaker | Open-source, portable, simple |
| 007 | SHA256 tokenization | One-way, deterministic, join-preserving |

---

## Future ADRs to Consider
- **ADR-008**: Real-time feature store (DynamoDB Streams → feature cache)
- **ADR-009**: Multi-region deployment strategy
- **ADR-010**: Model A/B testing framework
