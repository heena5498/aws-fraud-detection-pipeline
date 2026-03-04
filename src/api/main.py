"""
FastAPI Fraud Detection Scoring Service
Deployed on ECS Fargate for low-latency predictions.

Endpoints:
- POST /api/v1/score - Score a single transaction
- GET /api/v1/health - Health check
- GET /api/v1/alerts - List recent alerts
- POST /api/v1/feedback - Submit analyst feedback
"""

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
import uvicorn
import boto3
import joblib
import mlflow
import numpy as np
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.logger import get_logger
from common.config import get_config
from common.metrics import emit_counter, emit_timer, Timer

logger = get_logger(__name__)
config = get_config()

# Initialize FastAPI
app = FastAPI(
    title="Fraud Detection API",
    description="Real-time fraud scoring service",
    version="1.0.0"
)

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Request/Response Models ====================

class TransactionRequest(BaseModel):
    """Transaction scoring request."""
    transaction_id: str
    amount: float = Field(gt=0, description="Transaction amount")
    user_id: str
    merchant_id: str
    merchant_category: str
    transaction_type: str
    country: str
    currency: str = "USD"
    timestamp: Optional[datetime] = None
    
    @validator('timestamp', pre=True, always=True)
    def set_timestamp(cls, v):
        return v or datetime.now()
    
    class Config:
        schema_extra = {
            "example": {
                "transaction_id": "txn_001",
                "amount": 99.99,
                "user_id": "user_123",
                "merchant_id": "merchant_456",
                "merchant_category": "online_retail",
                "transaction_type": "purchase",
                "country": "US",
                "currency": "USD"
            }
        }


class ScoreResponse(BaseModel):
    """Fraud score response."""
    transaction_id: str
    fraud_probability: float = Field(ge=0, le=1)
    is_fraud: bool
    risk_level: str  # low, medium, high
    top_features: List[Dict[str, float]]
    model_version: str
    scored_at: datetime
    
    class Config:
        schema_extra = {
            "example": {
                "transaction_id": "txn_001",
                "fraud_probability": 0.85,
                "is_fraud": True,
                "risk_level": "high",
                "top_features": [
                    {"feature": "amount_vs_user_avg_ratio", "value": 5.2},
                    {"feature": "user_txn_count_5m", "value": 10.0}
                ],
                "model_version": "xgboost-v1.2",
                "scored_at": "2026-03-03T14:30:00Z"
            }
        }


class AlertResponse(BaseModel):
    """Alert details."""
    alert_id: str
    transaction_id: str
    fraud_probability: float
    amount: float
    user_id: str
    merchant_id: str
    created_at: datetime
    status: str  # pending, reviewed, confirmed_fraud, confirmed_legitimate


class FeedbackRequest(BaseModel):
    """Analyst feedback on alert."""
    alert_id: str
    is_fraud: bool
    analyst_id: str
    notes: Optional[str] = None


# ==================== Model Management ====================

class ModelLoader:
    """Lazy-load ML model from S3."""
    
    def __init__(self):
        self.model = None
        self.model_version = None
        self.feature_names = None
        self.s3_client = boto3.client('s3')
    
    def load_model(self):
        """Load latest model from S3."""
        if self.model is not None:
            return self.model
        
        logger.info("Loading model from S3...")
        
        # Download model from S3
        bucket = config.models_bucket
        key = 'production/model.pkl'
        
        local_path = '/tmp/model.pkl'
        self.s3_client.download_file(bucket, key, local_path)
        
        # Load model
        self.model = joblib.load(local_path)
        self.model_version = 'xgboost-v1.0'  # Read from metadata
        
        logger.info(f"Loaded model: {self.model_version}")
        
        return self.model
    
    def predict_proba(self, features: np.ndarray) -> float:
        """Get fraud probability."""
        if self.model is None:
            self.load_model()
        
        proba = self.model.predict_proba(features)[0, 1]
        return float(proba)


model_loader = ModelLoader()


# ==================== Feature Engineering ====================

def extract_features(txn: TransactionRequest) -> np.ndarray:
    """
    Extract features from transaction request.
    
    In production, this would:
    1. Hash user_id and merchant_id (match training)
    2. Query DynamoDB for velocity features
    3. Query feature store for user/merchant aggregates
    
    For now, using placeholder values.
    """
    # Placeholder: In production, fetch from feature store
    features = {
        'amount': txn.amount,
        'user_txn_count_5m': 2.0,
        'user_total_amount_5m': 150.0,
        'user_avg_amount_5m': 75.0,
        'user_txn_count_1h': 5.0,
        'user_total_amount_1h': 450.0,
        'user_avg_amount_1h': 90.0,
        'user_txn_count_24h': 15.0,
        'user_total_amount_24h': 1200.0,
        'user_avg_amount_24h': 80.0,
        'user_lifetime_txn_count': 100.0,
        'user_lifetime_total_amount': 8000.0,
        'user_lifetime_avg_amount': 80.0,
        'merchant_txn_count': 500.0,
        'merchant_total_amount': 40000.0,
        'merchant_fraud_count': 5.0,
        'merchant_fraud_rate': 0.01,
        'amount_vs_user_avg_ratio': txn.amount / 80.0,
        'hour_of_day': txn.timestamp.hour,
        'day_of_week': txn.timestamp.weekday() + 1,
        'is_weekend': 1 if txn.timestamp.weekday() >= 5 else 0,
    }
    
    # Convert to numpy array (order matters!)
    feature_vector = np.array([list(features.values())])
    
    return feature_vector


def get_top_features(model, features: np.ndarray, top_k: int = 5) -> List[Dict[str, float]]:
    """Get top contributing features (placeholder)."""
    # In production, use SHAP values
    feature_names = [
        'amount', 'user_txn_count_5m', 'user_total_amount_5m',
        'amount_vs_user_avg_ratio', 'merchant_fraud_rate'
    ]
    
    return [
        {"feature": name, "value": float(features[0][i])}
        for i, name in enumerate(feature_names[:top_k])
    ]


def determine_risk_level(probability: float) -> str:
    """Map probability to risk level."""
    if probability >= config.fraud_probability_threshold:
        return "high"
    elif probability >= 0.3:
        return "medium"
    else:
        return "low"


# ==================== API Endpoints ====================

@app.get("/api/v1/health")
async def health_check():
    """Health check endpoint for ALB target group."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "model_loaded": model_loader.model is not None
    }


@app.post("/api/v1/score", response_model=ScoreResponse)
async def score_transaction(txn: TransactionRequest):
    """
    Score a transaction for fraud.
    
    Returns fraud probability and risk assessment.
    """
    with Timer('score_transaction', dimensions={'endpoint': 'score'}):
        try:
            logger.info(f"Scoring transaction: {txn.transaction_id}")
            
            # Extract features
            features = extract_features(txn)
            
            # Get prediction
            fraud_probability = model_loader.predict_proba(features)
            
            # Determine risk
            is_fraud = fraud_probability >= config.fraud_probability_threshold
            risk_level = determine_risk_level(fraud_probability)
            
            # Get top features
            top_features = get_top_features(model_loader.model, features)
            
            # Emit metrics
            emit_counter('transactions_scored', 1)
            if is_fraud:
                emit_counter('fraud_detected', 1)
            
            response = ScoreResponse(
                transaction_id=txn.transaction_id,
                fraud_probability=fraud_probability,
                is_fraud=is_fraud,
                risk_level=risk_level,
                top_features=top_features,
                model_version=model_loader.model_version,
                scored_at=datetime.now()
            )
            
            # If high risk, create alert in DynamoDB
            if is_fraud:
                save_alert(txn, response)
            
            return response
        
        except Exception as e:
            logger.error(f"Scoring failed: {e}", exc_info=True)
            emit_counter('scoring_errors', 1)
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/alerts", response_model=List[AlertResponse])
async def list_alerts(
    status: Optional[str] = None,
    limit: int = 50
):
    """List recent fraud alerts."""
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(config.alerts_table)
        
        # Query alerts (most recent first)
        if status:
            response = table.query(
                IndexName='status-created_at-index',
                KeyConditionExpression='#status = :status',
                ExpressionAttributeNames={'#status': 'status'},
                ExpressionAttributeValues={':status': status},
                Limit=limit,
                ScanIndexForward=False
            )
        else:
            response = table.scan(Limit=limit)
        
        alerts = [
            AlertResponse(**item)
            for item in response.get('Items', [])
        ]
        
        return alerts
    
    except Exception as e:
        logger.error(f"Failed to list alerts: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/feedback")
async def submit_feedback(feedback: FeedbackRequest):
    """Submit analyst feedback on alert."""
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(config.feedback_table)
        
        item = {
            'alert_id': feedback.alert_id,
            'is_fraud': feedback.is_fraud,
            'analyst_id': feedback.analyst_id,
            'notes': feedback.notes,
            'submitted_at': datetime.now().isoformat()
        }
        
        table.put_item(Item=item)
        
        logger.info(f"Feedback saved: {feedback.alert_id}")
        emit_counter('feedback_submitted', 1)
        
        return {"status": "success", "alert_id": feedback.alert_id}
    
    except Exception as e:
        logger.error(f"Failed to save feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Helper Functions ====================

def save_alert(txn: TransactionRequest, score: ScoreResponse):
    """Save high-risk alert to DynamoDB."""
    try:
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(config.alerts_table)
        
        alert = {
            'alert_id': f"alert_{txn.transaction_id}",
            'transaction_id': txn.transaction_id,
            'fraud_probability': str(score.fraud_probability),  # Decimal for DynamoDB
            'amount': str(txn.amount),
            'user_id': txn.user_id,
            'merchant_id': txn.merchant_id,
            'created_at': datetime.now().isoformat(),
            'status': 'pending'
        }
        
        table.put_item(Item=alert)
        logger.info(f"Alert created: {alert['alert_id']}")
    
    except Exception as e:
        logger.error(f"Failed to save alert: {e}", exc_info=True)


# ==================== Startup/Shutdown ====================

@app.on_event("startup")
async def startup_event():
    """Load model on startup."""
    logger.info("Starting Fraud Detection API...")
    model_loader.load_model()
    logger.info("API ready")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Shutting down Fraud Detection API...")


# Main entry point
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
