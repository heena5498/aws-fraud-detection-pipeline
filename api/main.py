"""
FastAPI Inference Service
=========================
Real-time fraud detection API
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict
import joblib
import pandas as pd
import numpy as np
from pathlib import Path
import yaml
from loguru import logger
from datetime import datetime
import uvicorn

# Initialize FastAPI app
app = FastAPI(
    title="Fraud Detection API",
    description="Real-time fraud detection for card transactions",
    version="1.0.0"
)

# CORS middleware for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load configuration
with open("config.yaml", 'r') as f:
    config = yaml.safe_load(f)

# Global variables for model and feature columns
model = None
feature_columns = None
feature_store = None


class Transaction(BaseModel):
    """Transaction input schema."""
    transaction_id: str
    user_id: str
    merchant_id: str
    amount: float = Field(..., gt=0, description="Transaction amount (must be positive)")
    timestamp: str
    merchant_category: Optional[str] = None
    country: Optional[str] = None
    
    # Pre-computed features (optional, for testing)
    hour_of_day: Optional[int] = Field(None, ge=0, le=23)
    day_of_week: Optional[int] = Field(None, ge=0, le=6)
    transaction_count_1h: Optional[int] = None
    transaction_count_24h: Optional[int] = None
    
    @validator('timestamp')
    def validate_timestamp(cls, v):
        """Validate timestamp format."""
        try:
            pd.to_datetime(v)
            return v
        except:
            raise ValueError("Invalid timestamp format. Use ISO format (e.g., '2024-01-01 12:00:00')")


class FraudPrediction(BaseModel):
    """Fraud prediction output schema."""
    transaction_id: str
    fraud_probability: float
    is_fraud: bool
    risk_level: str
    top_features: Dict[str, float]
    timestamp: str


class BatchTransactionRequest(BaseModel):
    """Batch prediction request."""
    transactions: List[Transaction]


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    model_loaded: bool
    model_path: str
    timestamp: str


@app.on_event("startup")
async def load_model():
    """Load model and feature columns on startup."""
    global model, feature_columns, feature_store
    
    logger.info("Loading fraud detection model...")
    
    # Load model
    model_path = Path(config['api']['model_path'])
    if not model_path.exists():
        logger.error(f"Model not found at {model_path}")
        logger.info("Please train a model first using: python ml/train.py")
        return
    
    model = joblib.load(model_path)
    logger.info(f"✓ Model loaded from {model_path}")
    
    # Load feature columns
    feature_cols_path = Path(config['data']['gold_path']) / "feature_columns.txt"
    if feature_cols_path.exists():
        with open(feature_cols_path, 'r') as f:
            feature_columns = [line.strip() for line in f.readlines()]
        logger.info(f"✓ Loaded {len(feature_columns)} feature columns")
    else:
        logger.warning("Feature columns file not found. Using model's expected features.")
        feature_columns = None
    
    logger.info("✓ API ready for predictions")


def engineer_features(transaction: Transaction) -> pd.DataFrame:
    """
    Engineer features for a single transaction.
    In production, you'd look up historical features from a feature store.
    For demo, we'll compute basic features.
    """
    # Parse timestamp
    ts = pd.to_datetime(transaction.timestamp)
    
    features = {
        # Temporal features
        'hour_of_day': transaction.hour_of_day or ts.hour,
        'day_of_week': transaction.day_of_week or ts.dayofweek,
        'day_of_month': ts.day,
        'month': ts.month,
        'is_weekend': int(ts.dayofweek >= 5),
        'is_night_time': int((ts.hour >= 22) or (ts.hour <= 6)),
        
        # Amount features
        'amount': transaction.amount,
        'amount_log': np.log1p(transaction.amount),
        'amount_rounded': (transaction.amount // 100) * 100,
        'is_high_amount': int(transaction.amount > 1000),  # Simplified threshold
        
        # Velocity features (would come from feature store in production)
        'transaction_count_1h': transaction.transaction_count_1h or 1,
        'transaction_count_24h': transaction.transaction_count_24h or 1,
        'total_amount_1h': transaction.amount,  # Simplified
        'total_amount_24h': transaction.amount,  # Simplified
        'avg_amount_7d': transaction.amount,  # Simplified
        'unique_merchants_24h': 1,  # Simplified
        
        # Mock features (would come from feature store)
        'time_since_last_transaction': 1.0,
        'merchant_avg_amount': transaction.amount,
        'merchant_std_amount': 0.0,
        'merchant_transaction_count': 100,
        'merchant_fraud_rate': 0.01,
        'amount_deviation_from_merchant': 0.0,
        'user_avg_amount': transaction.amount,
        'user_std_amount': 0.0,
        'user_total_transactions': 10,
        'user_unique_merchants': 5,
        'amount_deviation_from_user': 0.0,
        'is_unusual_amount': 0,
        'country_mismatch': 0,
        'suspected_geo_fraud': 0,
        'amount_x_hour': transaction.amount * ts.hour,
        'amount_x_weekend': transaction.amount * int(ts.dayofweek >= 5),
        'velocity_amount_ratio': 1 / (transaction.amount + 1),
    }
    
    # Add missing features from feature_columns
    if feature_columns:
        for col in feature_columns:
            if col not in features:
                features[col] = 0  # Default value for missing features
    
    return pd.DataFrame([features])


def get_risk_level(probability: float) -> str:
    """Determine risk level based on fraud probability."""
    if probability >= 0.8:
        return "HIGH"
    elif probability >= 0.5:
        return "MEDIUM"
    elif probability >= 0.3:
        return "LOW"
    else:
        return "VERY_LOW"


def get_top_features(features: pd.DataFrame, n_top: int = 5) -> Dict[str, float]:
    """Get top contributing features (simplified version)."""
    # In production, use SHAP or model-specific feature importance
    # For now, return top features by absolute value
    feature_values = features.iloc[0].to_dict()
    sorted_features = sorted(feature_values.items(), key=lambda x: abs(x[1]), reverse=True)
    return dict(sorted_features[:n_top])


@app.get("/", response_model=Dict)
async def root():
    """Root endpoint."""
    return {
        "message": "Fraud Detection API",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "predict": "/predict (POST)",
            "batch_predict": "/predict/batch (POST)",
            "docs": "/docs"
        }
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy" if model is not None else "model_not_loaded",
        model_loaded=model is not None,
        model_path=str(config['api']['model_path']),
        timestamp=datetime.now().isoformat()
    )


@app.post("/predict", response_model=FraudPrediction)
async def predict_fraud(transaction: Transaction):
    """Predict fraud for a single transaction."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded. Please check server logs.")
    
    try:
        # Engineer features
        features = engineer_features(transaction)
        
        # Ensure feature order matches training
        if feature_columns:
            features = features[feature_columns]
        
        # Make prediction
        fraud_probability = float(model.predict_proba(features)[0, 1])
        is_fraud = fraud_probability >= config['ml']['evaluation']['optimal_threshold']
        risk_level = get_risk_level(fraud_probability)
        
        # Get top contributing features
        top_features = get_top_features(features)
        
        logger.info(f"Prediction for {transaction.transaction_id}: {fraud_probability:.4f} (risk: {risk_level})")
        
        return FraudPrediction(
            transaction_id=transaction.transaction_id,
            fraud_probability=round(fraud_probability, 4),
            is_fraud=is_fraud,
            risk_level=risk_level,
            top_features=top_features,
            timestamp=datetime.now().isoformat()
        )
    
    except Exception as e:
        logger.error(f"Prediction error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")


@app.post("/predict/batch", response_model=List[FraudPrediction])
async def batch_predict_fraud(request: BatchTransactionRequest):
    """Predict fraud for multiple transactions."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    # Check batch size limit
    max_batch = config['api']['max_batch_size']
    if len(request.transactions) > max_batch:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size exceeds maximum of {max_batch}"
        )
    
    predictions = []
    for txn in request.transactions:
        try:
            pred = await predict_fraud(txn)
            predictions.append(pred)
        except Exception as e:
            logger.error(f"Failed to predict {txn.transaction_id}: {str(e)}")
            # Continue with other transactions
    
    return predictions


@app.get("/model/info")
async def model_info():
    """Get model information."""
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    return {
        "model_type": type(model).__name__,
        "n_features": len(feature_columns) if feature_columns else "unknown",
        "feature_columns": feature_columns[:10] if feature_columns else [],  # First 10
        "model_path": str(config['api']['model_path'])
    }


def start_server():
    """Start the FastAPI server."""
    uvicorn.run(
        "api.main:app",
        host=config['api']['host'],
        port=config['api']['port'],
        reload=True,
        log_level="info"
    )


if __name__ == "__main__":
    start_server()
