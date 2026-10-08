# Real-Time Fraud Detection Pipeline

An end-to-end machine learning system that learns what fraudulent card transactions look like and scores new transactions as they stream in.

It covers the full lifecycle: data generation, a Bronze/Silver/Gold ETL pipeline, model training with experiment tracking, a REST scoring API secured with OIDC, Kafka-based streaming, and drift monitoring. It also includes a cloud design for AWS written as infrastructure-as-code.

![Python](https://img.shields.io/badge/Python-3.11+-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-REST%20API-009688) ![XGBoost](https://img.shields.io/badge/XGBoost-ML-orange) ![Kafka](https://img.shields.io/badge/Apache%20Kafka-Streaming-black) ![Keycloak](https://img.shields.io/badge/Keycloak-OIDC-4d4d4d) ![AWS CDK](https://img.shields.io/badge/AWS%20CDK-IaC-FF9900)

---

## Key Features

**Data engineering**
- **Medallion ETL pipeline:** Bronze (schema validation with Pandera, deduplication, Parquet storage), then Silver (feature engineering), then Gold (model-ready datasets and a versioned feature list).
- **41 engineered fraud signals:** time-of-day and night-time flags, rolling velocity windows (1h / 6h / 24h / 7d transaction counts and spend), how far an amount is from the user's and merchant's typical behaviour, country-change and "impossible travel" flags.
- **Time-based train/test split** to avoid training on data from the future.

**Machine learning**
- **XGBoost classifier** with configurable alternatives (Logistic Regression, LightGBM) selected from `config.yaml`.
- **Class-imbalance handling** with SMOTE, because only about 2% of transactions are fraud.
- **MLflow experiment tracking:** parameters, metrics, feature importance and model artifacts are logged for every run.
- **Drift monitoring** using the Population Stability Index (PSI), with low/medium/high thresholds that signal when to retrain.

**Serving and streaming**
- **FastAPI scoring service:** single and batch prediction endpoints, request validation with Pydantic, risk tiers (VERY_LOW to HIGH), health check, auto-generated OpenAPI docs.
- **Load tested:** about 1,000 predictions/sec with p95 latency under 100 ms on a laptop with 4 workers. The Kafka streaming path was measured separately (see [Performance](#performance)).
- **Kafka streaming:** a producer simulates live card transactions; a consumer scores each one through the API, raises alerts for high-risk transactions, and tracks precision and recall in real time.
- **OIDC authentication:** analyst-facing endpoints need a JWT from Keycloak. The API checks the signature (keys found through OIDC discovery), issuer, audience and expiry. Machine-to-machine scoring stays separate from human login.

**Cloud design (AWS, infrastructure-as-code)**
- AWS CDK (TypeScript) stacks for Kinesis, Lambda, DynamoDB, ECS Fargate behind an Application Load Balancer, and CloudWatch.
- Service code for each stage in `src/`: a Kinesis ingestion Lambda with idempotent deduplication, PySpark Glue jobs with salted SHA-256 PII hashing, and a drift-monitor Lambda that starts retraining through Step Functions.

---

## Architecture

### Local system (runs end to end with Docker)

```
 OFFLINE: learning                                ONLINE: scoring
 ─────────────────                                ───────────────
 scripts/download_data.py                         streaming/producer.py
   (100k synthetic transactions)                    (simulated card swipes)
        │                                                 │
        v                                                 v
 etl/bronze_layer.py   validate + dedupe          Kafka topic "transactions-raw"
        v                                                 │
 etl/silver_layer.py   feature engineering                v
        v                                         streaming/consumer.py
 etl/gold_layer.py     train/test + feature list          │  HTTP POST /predict
        v                                                 v
 ml/train.py           XGBoost + MLflow ───────>  api/main.py (FastAPI)
        │              fraud_model.pkl              loads model, builds features,
        v                                           returns probability + risk level
 ml/drift_monitor.py   PSI drift report                   │
                                                          v
                                                  HIGH/MEDIUM risk -> data/alerts/*.csv

                       Keycloak (OIDC) ──JWT──> protected analyst endpoints
```

### AWS design (in `src/` and `infrastructure/`)

```
Producer -> Kinesis -> Bronze Lambda -> S3 (Parquet) -> Glue Silver/Gold (PySpark) -> Training
                         │ dedupe                                                     │
                         v                                                            v
                      DynamoDB                    ALB -> ECS Fargate (FastAPI, autoscaling 2-10 tasks)
                                                           │
                                                           v
                                         DynamoDB (alerts, analyst feedback)
                     CloudWatch dashboards + alarms  |  Drift Lambda -> Step Functions retrain
```

---

## Model Results

From the logged MLflow run (XGBoost, test set of 20,000 transactions, decision threshold 0.5):

| Metric | Value |
|---|---|
| ROC-AUC | 0.993 |
| Recall (fraud caught) | 90.0% |
| Precision | 53.5% |
| F1 | 0.67 |
| False positive rate | 1.6% |

**These offline numbers are inflated, and the live stream shows it.** Two reasons:
- **Synthetic data:** fraud was generated with strong patterns such as late-night timing and online/travel merchants. That's why `is_night_time` is the top feature.
- **Label leakage in `merchant_fraud_rate`** (the #2 feature). The Silver layer computes it over the full dataset, including each row's own label. In the test set, 100% of fraud rows have a merchant fraud rate above 1%, compared with 33% of legitimate rows. At serving time the API uses a fixed placeholder value, so this signal disappears.

**Live result:** scoring 5,700 streamed transactions through Kafka gave **recall of 1.7%** (2 of 116 frauds caught) and precision of 11.8%. That gap between offline and live performance is a training/serving skew problem, and fixing it is the top item on the roadmap. Any real deployment would also need the decision threshold tuned to the business cost of a missed fraud versus a blocked legitimate customer.

---

## Tech Stack

| Area | Tools |
|---|---|
| Language | Python, TypeScript |
| Data & features | pandas, NumPy, PyArrow / Parquet, Pandera, PySpark (AWS Glue) |
| Machine learning | XGBoost, LightGBM, scikit-learn, imbalanced-learn (SMOTE), MLflow |
| API | FastAPI, Pydantic, Uvicorn |
| Auth | OIDC with Keycloak, PyJWT |
| Streaming | Apache Kafka (Confluent images), kafka-python |
| Infrastructure | Docker, Docker Compose, AWS CDK |
| AWS (designed) | Kinesis, Lambda, S3, Glue, DynamoDB, ECS Fargate, ALB, CloudWatch, Step Functions, Secrets Manager |
| Frontend (in progress) | React, TypeScript, Material UI |
| Testing | pytest |

---

## Quick Start

**Prerequisites:** Python 3.11+, Docker.

```bash
# 1. Install dependencies and create the data directories
make setup

# 2. Build the dataset and the model
make data        # generate 100,000 synthetic transactions
make etl         # Bronze -> Silver -> Gold
make train       # train XGBoost, log the run to MLflow, save ml/models/fraud_model.pkl

# 3. Start infrastructure (Kafka, Keycloak, MLflow, Postgres)
docker-compose up -d

# 4. Run the scoring service and the stream (separate terminals)
make api         # http://localhost:8000/docs
make producer    # stream transactions into Kafka
make consumer    # score them in real time and write alerts
```

| Service | URL |
|---|---|
| API docs (Swagger) | http://localhost:8000/docs |
| Kafka UI | http://localhost:8081 |
| Keycloak | http://localhost:8180 (admin / admin, local only) |
| MLflow UI | run `mlflow ui`, then open http://localhost:5000 |

### Calling a protected endpoint

```bash
TOKEN=$(curl -s -X POST http://localhost:8180/realms/fraud-detection/protocol/openid-connect/token \
  -d grant_type=password -d client_id=fraud-analyst-ui -d username=analyst -d password=analyst \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/model/info
```

The password login above is for local testing only. A browser frontend would use the Authorization Code flow with PKCE, which the `fraud-analyst-ui` client is set up for.

---

## API Reference

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| GET | `/health` | None | Service status and whether the model is loaded |
| POST | `/predict` | None (machine caller) | Score one transaction |
| POST | `/predict/batch` | None (machine caller) | Score up to 100 transactions |
| GET | `/model/info` | OIDC bearer token | Model type and feature metadata |

**Example request** to `POST /predict`:
```json
{
  "transaction_id": "txn_001",
  "user_id": "user_42",
  "merchant_id": "merchant_77",
  "amount": 2500.00,
  "timestamp": "2026-10-07 02:13:00",
  "merchant_category": "online",
  "country": "US"
}
```

**Example response:**
```json
{
  "transaction_id": "txn_001",
  "fraud_probability": 0.3329,
  "is_fraud": false,
  "risk_level": "LOW",
  "top_features": {
    "amount_x_hour": 5000.0,
    "amount": 2500.0,
    "amount_rounded": 2500.0,
    "total_amount_1h": 2500.0,
    "total_amount_24h": 2500.0
  },
  "timestamp": "2026-10-08T01:49:17.499570"
}
```

---

## Performance

Measured with [scripts/benchmark_api.py](scripts/benchmark_api.py), which sends concurrent `POST /predict` requests with randomized transactions. Machine: Apple M3 laptop (8 cores), with the load generator running on the same machine.

| Setup | Concurrent clients | Throughput | p50 | p95 | p99 |
|---|---|---|---|---|---|
| 1 Uvicorn worker | 1 | 327 req/s | 3.0 ms | 3.3 ms | 3.5 ms |
| 1 Uvicorn worker | 20 | 351 req/s | 55.4 ms | 68.2 ms | 90.2 ms |
| 4 Uvicorn workers | 20 | 731 req/s | 17.0 ms | 83.8 ms | 150.2 ms |
| 4 Uvicorn workers | 50 | 999 req/s | 43.6 ms | 95.2 ms | 109.8 ms |

What the numbers show:
- A single prediction (feature building plus XGBoost inference) takes about **3 ms**.
- One worker is limited by CPU. Extra concurrent clients only add queueing time, because model inference is CPU-bound and blocks that worker's event loop.
- Throughput scales with worker processes. With 4 workers (the Dockerfile default) the API handles about **1,000 requests/sec with p95 under 100 ms**.
- These numbers cover the API's own work only. User and merchant history are placeholders today, so a production deployment that looks up features from an online store (Redis or DynamoDB) would add that lookup time to each request.

```bash
uvicorn api.main:app --port 8000 --workers 4
python scripts/benchmark_api.py --requests 5000 --concurrency 50
```

### Streaming pipeline (Kafka)

Measured with Kafka in Docker (1 broker, topic `transactions-raw` with 1 partition) and the API running with 4 workers:

| Stage | Measured rate | What limits it |
|---|---|---|
| Producer (`streaming/producer.py --rate 2000`) | 383 msg/s | Waits for Kafka to confirm each message before sending the next (`future.get()`) |
| Consumer (`streaming/consumer.py`, draining a 5,700-message backlog) | 264 msg/s | Scores one message at a time with a blocking HTTP call; with 1 partition, only one consumer in the group can read |

The streaming path is limited by the client code, not by Kafka or the API. The API can handle about 4 times more than the consumer currently sends. Ways to scale it: send without waiting for each confirmation, score in batches through `/predict/batch` or concurrent requests, and add partitions so several consumers can share the work.

**Delivery guarantee:** the consumer uses Kafka's auto-commit, which marks a message as done on a timer whether or not it has been scored. So delivery is at-least-once or at-most-once, not exactly-once. Getting exactly-once would need manual commits after scoring plus idempotent alert writes.

---

## Project Structure

```
├── api/                 FastAPI scoring service (main.py) and OIDC verification (auth.py)
├── etl/                 Bronze, Silver and Gold pipeline layers
├── ml/                  Model training (train.py) and PSI drift monitoring
├── streaming/           Kafka producer and real-time scoring consumer
├── scripts/             Synthetic dataset generation and API load testing
├── keycloak/            Keycloak realm (client and test user), imported at startup
├── src/                 AWS service code: Lambda handlers, Glue jobs, shared AWS utilities
├── infrastructure/      AWS CDK app (Kinesis, DynamoDB, ECS/ALB, monitoring stacks)
├── frontend/            React alerts dashboard (in progress)
├── notebooks/           Exploratory data analysis
├── tests/               pytest suite (pipeline, prediction, authentication)
├── docs/                Architecture decision records and design notes
├── config.yaml          Central configuration: paths, features, model, API, Kafka, auth
├── docker-compose.yml   Kafka, Zookeeper, Kafka UI, Keycloak, MLflow, Postgres
└── Makefile             One-command workflows (setup, etl, train, api, producer, consumer, test)
```

---

## Engineering Decisions

- **Medallion layers instead of one script.** Each stage writes its output to disk, so a bad feature-engineering change can be re-run from Bronze without regenerating or re-ingesting data.
- **Kafka between producer and scorer.** The transaction source doesn't wait for scoring, and traffic spikes queue up instead of overloading the API.
- **Time-based split.** A random split would let the model learn from future transactions, which inflates offline metrics for a problem that is time-dependent by nature.
- **Precision/recall over accuracy.** With 2% fraud, a model that never flags anything is 98% "accurate". Recall and false-positive rate are the metrics that matter.
- **The model defines its own input schema.** The API reads the trained model's `feature_names_in_` and one-hot encodes requests the same way training does. Serving can't drift away from the columns the model was trained on, and a regression test ([tests/test_predict.py](tests/test_predict.py)) guards this.
- **Auth split by caller type.** Human endpoints use OIDC (Keycloak). The high-throughput scoring path is meant for trusted services, so an interactive login isn't put in the way of every transaction.

More detail is in [docs/ADR.md](docs/ADR.md) and [docs/ARCHITECTURE_ANALYSIS.md](docs/ARCHITECTURE_ANALYSIS.md).

---

## Status and Roadmap

| Component | Status |
|---|---|
| ETL pipeline, model training, MLflow tracking | Working locally |
| FastAPI service, OIDC authentication, Kafka streaming | Working locally |
| AWS service code and CDK stacks | Written, not yet deployed |
| React alerts dashboard | In progress |

**Next steps**
- Remove label leakage: compute `merchant_fraud_rate` and other aggregates using only transactions *before* each row (point-in-time features), then retrain and compare offline and live metrics.
- Raise streaming throughput: async producer sends, batched or concurrent scoring in the consumer, more topic partitions.
- Commit Kafka offsets manually after scoring for stronger delivery guarantees.
- Replace placeholder user and merchant history at serving time with an online feature store (for example Redis or DynamoDB), so velocity features are real at scoring time.
- Store predictions and alerts in a database instead of CSV files.
- Add CI/CD (GitHub Actions: tests, Docker build, CDK deploy using OIDC federation to AWS).
- Explain individual predictions with SHAP values.
