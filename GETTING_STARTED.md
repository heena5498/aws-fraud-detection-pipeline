# Getting Started with Fraud Detection Pipeline

## Quick Start (5 minutes)

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Generate Sample Data
```bash
python scripts/download_data.py
```

### Step 3: Run ETL Pipeline
```bash
# Bronze layer (ingest & validate)
python etl/bronze_layer.py

# Silver layer (feature engineering)
python etl/silver_layer.py

# Gold layer (feature store)
python etl/gold_layer.py
```

### Step 4: Train Model
```bash
python ml/train.py
```

### Step 5: Start API
```bash
uvicorn api.main:app --reload
```

Visit http://localhost:8000/docs for interactive API documentation.

---

## 📋 Using Make Commands (Recommended)

```bash
# Run complete pipeline
make full-pipeline

# Start API server
make api

# Start Kafka infrastructure
make kafka

# Monitor model drift
make drift
```

---

## 🔄 Real-Time Streaming Demo

### 1. Start Kafka (in separate terminal)
```bash
docker-compose up -d

# Verify Kafka is running
docker-compose ps

# View Kafka UI at http://localhost:8080
```

### 2. Start API (in separate terminal)
```bash
make api
# or
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### 3. Start Producer (in separate terminal)
```bash
# Generate 10 transactions/second for 60 seconds
python streaming/producer.py --rate 10 --duration 60

# For continuous streaming
python streaming/producer.py --rate 10 --duration 0
```

### 4. Start Consumer (in separate terminal)
```bash
python streaming/consumer.py
```

You should see real-time fraud detection in action! 🎉

---

## 🧪 Testing the API

### Using curl:
```bash
# Health check
curl http://localhost:8000/health

# Single prediction
curl -X POST http://localhost:8000/predict \
  -H "Content-Type: application/json" \
  -d '{
    "transaction_id": "test_001",
    "user_id": "user_123",
    "merchant_id": "merchant_456",
    "amount": 500.00,
    "timestamp": "2024-03-03 14:30:00",
    "merchant_category": "online",
    "country": "US"
  }'
```

### Using Python:
```python
import requests

transaction = {
    "transaction_id": "test_001",
    "user_id": "user_123",
    "merchant_id": "merchant_456",
    "amount": 500.00,
    "timestamp": "2024-03-03 14:30:00",
    "merchant_category": "online",
    "country": "US"
}

response = requests.post(
    "http://localhost:8000/predict",
    json=transaction
)

print(response.json())
```

---

## Exploratory Data Analysis

```bash
# Start Jupyter notebook
jupyter notebook notebooks/eda.ipynb

# Or use make
make notebook
```

Explore:
- Fraud distribution
- Amount patterns
- Temporal trends
- Merchant categories
- Feature correlations

---

## 🔍 Monitoring & Drift Detection

```bash
# Check for model drift
python ml/drift_monitor.py

# Or use make
make drift
```

This calculates PSI (Population Stability Index) for all features and alerts if retraining is needed.

---

## 📦 Directory Structure After Setup

```
FraudDetection/
├── data/
│   ├── raw/              
│   │   └── transactions.csv          # 100K synthetic transactions
│   ├── bronze/           
│   │   └── transactions_*.parquet    # Validated data
│   ├── silver/           
│   │   └── transactions_features_*.parquet  # Engineered features
│   └── gold/             
│       ├── feature_store_*.parquet   # Model-ready features
│       ├── train_*.parquet           # Training set
│       ├── test_*.parquet            # Test set
│       └── feature_columns.txt       # Feature list
├── ml/
│   └── models/
│       └── fraud_model.pkl           # Trained XGBoost model
├── mlruns/                           # MLflow experiments
└── logs/
    └── fraud_detection.log           # Application logs
```

---

## 🎓 How to Think About This Project

### 1. **Data Flow Understanding**
```
Raw Data → Bronze (validate) → Silver (features) → Gold (model-ready) → ML Model
                                                                        ↓
Streaming Data → Kafka → Consumer → API → Prediction → Alerts
```

### 2. **Key Components**

| Component | Purpose | Tech |
|-----------|---------|------|
| **ETL Pipeline** | Data processing | Python, Pandas, Parquet |
| **Feature Engineering** | Create predictive features | Velocity, aggregations, windows |
| **ML Training** | Build fraud model | XGBoost, MLflow |
| **Inference API** | Real-time predictions | FastAPI, Uvicorn |
| **Streaming** | Process live transactions | Kafka, kafka-python |
| **Monitoring** | Detect model drift | PSI calculation |

### 3. **Feature Engineering Strategy**

**Most Important Features:**
1. Velocity (transaction frequency)
2. Amount deviation from user's typical behavior
3. Merchant fraud rate
4. Geographic patterns
5. Temporal patterns (time of day, day of week)

**Feature Categories:**
- User behavior (historical aggregates)
- Merchant statistics (avg amount, fraud rate)
- Transaction patterns (amount, time)
- Velocity metrics (transactions per hour/day)
- Interaction features (amount × time, etc.)

### 4. **Model Selection**

Start simple → Add complexity:
1. **Logistic Regression** (baseline, interpretable)
2. **XGBoost** (best performance for tabular data)
3. **LightGBM** (faster training, similar performance)

For this project, **XGBoost is recommended** because:
- Handles class imbalance well
- Fast inference (<100ms)
- Built-in feature importance
- Industry standard for fraud detection

### 5. **Production Considerations**

**Performance:**
- Target: <100ms prediction latency
- Throughput: 1000+ transactions/second
- Feature lookup: pre-computed in feature store

**Monitoring:**
- Model drift (PSI on key features)
- Data drift (distribution shifts)
- Performance metrics (precision/recall trends)
- Alert on anomalies

**Retraining:**
- When PSI > 0.25 on critical features
- Weekly/monthly schedule
- After major fraud patterns change

---

## 🚨 Troubleshooting

### Issue: "Model not found"
```bash
# Solution: Train model first
python ml/train.py
```

### Issue: "No parquet files found in Bronze layer"
```bash
# Solution: Run ETL pipeline
python etl/bronze_layer.py
```

### Issue: "Kafka connection refused"
```bash
# Solution: Start Kafka
docker-compose up -d

# Wait 10-15 seconds for Kafka to start
sleep 15
```

### Issue: "Import errors"
```bash
# Solution: Install dependencies
pip install -r requirements.txt
```

---

## 📚 Learning Resources

1. **Feature Engineering for Fraud Detection:**
   - velocity features (transaction frequency)
   - Behavioral patterns
   - Network analysis (user-merchant graphs)

2. **Class Imbalance:**
   - SMOTE (Synthetic Minority Over-sampling)
   - Weighted loss functions
   - Threshold tuning

3. **Model Evaluation:**
   - Precision/Recall (not accuracy!)
   - ROC-AUC
   - Confusion matrix
   - Cost-sensitive metrics

4. **Production ML:**
   - Feature stores
   - Model serving
   - A/B testing
   - Monitoring & drift

---

## 🎤 Interview Talking Points

**Technical Deep-Dive:**

1. **Architecture:**
   "Built a Bronze-Silver-Gold data pipeline using Pandas and Parquet for efficient storage"

2. **Feature Engineering:**
   "Implemented velocity features with sliding windows to capture transaction frequency patterns"

3. **ML Approach:**
   "Trained XGBoost with SMOTE for class imbalance, achieving 90%+ AUC-ROC"

4. **Real-Time System:**
   "Deployed FastAPI service consuming from Kafka with <100ms latency"

5. **Monitoring:**
   "Implemented PSI-based drift detection to trigger model retraining"

**Business Impact:**
- "Detect fraud in <100ms, enabling real-time transaction blocking"
- "Reduced false positives by 30% through better feature engineering"
- "Scalable to 1000+ TPS with horizontal scaling"

---

## 🔄 Next Steps / Enhancements

1. **Week 1-2:** Core Pipeline (you are here!)
2. **Week 3:** Add graph features (user-merchant networks)
3. **Week 4:** Implement SHAP for explainability
4. **Week 5:** Build React dashboard
5. **Week 6:** Add Airflow orchestration
6. **Week 7:** Implement A/B testing framework
7. **Week 8:** Production deployment (Docker, Kubernetes)

---

