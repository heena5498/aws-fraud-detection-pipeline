"""
ML Training Pipeline
Trains fraud detection models with MLflow tracking.

Models:
1. Logistic Regression (baseline)
2. XGBoost (production candidate)
3. LightGBM (comparison)

Metrics: PR-AUC, ROC-AUC, Precision@k, Recall@k
"""

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import (
    roc_auc_score,
    average_precision_score,
    precision_recall_curve,
    confusion_matrix,
    classification_report
)
import xgboost as xgb
import lightgbm as lgb
import mlflow
import mlflow.sklearn
import mlflow.xgboost
import mlflow.lightgbm
import boto3
import joblib
from datetime import datetime
import json
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.logger import get_logger
from common.config import get_config

logger = get_logger(__name__)
config = get_config()


class FraudModelTrainer:
    """
    Fraud detection model trainer with MLflow tracking.
    """
    
    def __init__(
        self,
        gold_s3_path: str,
        mlflow_tracking_uri: str,
        experiment_name: str = 'fraud-detection'
    ):
        """
        Initialize trainer.
        
        Args:
            gold_s3_path: S3 path to Gold layer Parquet
            mlflow_tracking_uri: MLflow tracking server URI
            experiment_name: MLflow experiment name
        """
        self.gold_s3_path = gold_s3_path
        self.mlflow_tracking_uri = mlflow_tracking_uri
        self.experiment_name = experiment_name
        
        # Initialize MLflow
        mlflow.set_tracking_uri(mlflow_tracking_uri)
        mlflow.set_experiment(experiment_name)
        
        logger.info(f"Initialized trainer: {experiment_name}")
    
    def load_data(self) -> pd.DataFrame:
        """Load training data from S3."""
        logger.info(f"Loading data from: {self.gold_s3_path}")
        df = pd.read_parquet(self.gold_s3_path)
        logger.info(f"Loaded {len(df)} records")
        return df
    
    def prepare_features(self, df: pd.DataFrame):
        """
        Prepare features for modeling.
        
        Returns:
            X_train, X_test, y_train, y_test, feature_names, encoders
        """
        # Separate features and target
        feature_cols = [col for col in df.columns if col not in [
            'transaction_id', 'timestamp', 'is_fraud'
        ]]
        
        X = df[feature_cols].copy()
        y = df['is_fraud'].values
        
        # Encode categorical features
        categorical_cols = ['transaction_type', 'country', 'currency', 'merchant_category']
        encoders = {}
        
        for col in categorical_cols:
            if col in X.columns:
                le = LabelEncoder()
                X[col] = le.fit_transform(X[col].astype(str))
                encoders[col] = le
        
        # Train/test split (80/20, stratified)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=0.2,
            random_state=42,
            stratify=y
        )
        
        logger.info(f"Training set: {len(X_train)} samples")
        logger.info(f"Test set: {len(X_test)} samples")
        logger.info(f"Fraud rate (train): {y_train.mean():.4f}")
        logger.info(f"Fraud rate (test): {y_test.mean():.4f}")
        
        return X_train, X_test, y_train, y_test, X.columns.tolist(), encoders
    
    def evaluate_model(self, y_true, y_pred_proba):
        """Calculate evaluation metrics."""
        metrics = {}
        
        # ROC-AUC
        metrics['roc_auc'] = roc_auc_score(y_true, y_pred_proba)
        
        # PR-AUC (more important for imbalanced data)
        metrics['pr_auc'] = average_precision_score(y_true, y_pred_proba)
        
        # Precision/Recall at different thresholds
        precision, recall, thresholds = precision_recall_curve(y_true, y_pred_proba)
        
        # Find threshold for 90% recall
        idx_90_recall = np.argmax(recall >= 0.9)
        metrics['precision_at_90_recall'] = precision[idx_90_recall]
        metrics['threshold_at_90_recall'] = thresholds[idx_90_recall]
        
        # Confusion matrix at default threshold (0.5)
        y_pred = (y_pred_proba >= 0.5).astype(int)
        cm = confusion_matrix(y_true, y_pred)
        metrics['confusion_matrix'] = cm.tolist()
        
        # Classification report
        report = classification_report(y_true, y_pred, output_dict=True)
        metrics['precision'] = report['1']['precision']
        metrics['recall'] = report['1']['recall']
        metrics['f1'] = report['1']['f1-score']
        
        return metrics
    
    def train_logistic_regression(self, X_train, X_test, y_train, y_test):
        """Train baseline Logistic Regression model."""
        with mlflow.start_run(run_name='logistic-regression-baseline'):
            logger.info("Training Logistic Regression...")
            
            # Scale features
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            # Train with class weight balancing
            model = LogisticRegression(
                max_iter=1000,
                class_weight='balanced',
                random_state=42,
                n_jobs=-1
            )
            model.fit(X_train_scaled, y_train)
            
            # Predict
            y_pred_proba = model.predict_proba(X_test_scaled)[:, 1]
            
            # Evaluate
            metrics = self.evaluate_model(y_test, y_pred_proba)
            
            # Log parameters
            mlflow.log_param('model_type', 'logistic_regression')
            mlflow.log_param('class_weight', 'balanced')
            mlflow.log_param('max_iter', 1000)
            
            # Log metrics
            for key, value in metrics.items():
                if not isinstance(value, list):
                    mlflow.log_metric(key, value)
            
            # Log model
            mlflow.sklearn.log_model(model, 'model')
            mlflow.sklearn.log_model(scaler, 'scaler')
            
            logger.info(f"Logistic Regression - PR-AUC: {metrics['pr_auc']:.4f}, ROC-AUC: {metrics['roc_auc']:.4f}")
            
            return model, scaler, metrics
    
    def train_xgboost(self, X_train, X_test, y_train, y_test):
        """Train XGBoost model."""
        with mlflow.start_run(run_name='xgboost-tuned'):
            logger.info("Training XGBoost...")
            
            # Calculate scale_pos_weight for imbalanced data
            scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()
            
            params = {
                'max_depth': 6,
                'learning_rate': 0.1,
                'n_estimators': 200,
                'objective': 'binary:logistic',
                'eval_metric': 'auc',
                'scale_pos_weight': scale_pos_weight,
                'random_state': 42,
                'n_jobs': -1
            }
            
            model = xgb.XGBClassifier(**params)
            
            # Train with early stopping
            model.fit(
                X_train, y_train,
                eval_set=[(X_test, y_test)],
                early_stopping_rounds=20,
                verbose=False
            )
            
            # Predict
            y_pred_proba = model.predict_proba(X_test)[:, 1]
            
            # Evaluate
            metrics = self.evaluate_model(y_test, y_pred_proba)
            
            # Log parameters
            for key, value in params.items():
                mlflow.log_param(key, value)
            
            # Log metrics
            for key, value in metrics.items():
                if not isinstance(value, list):
                    mlflow.log_metric(key, value)
            
            # Feature importance
            importance_df = pd.DataFrame({
                'feature': X_train.columns,
                'importance': model.feature_importances_
            }).sort_values('importance', ascending=False)
            
            mlflow.log_text(importance_df.to_csv(index=False), 'feature_importance.csv')
            
            # Log model
            mlflow.xgboost.log_model(model, 'model')
            
            logger.info(f"XGBoost - PR-AUC: {metrics['pr_auc']:.4f}, ROC-AUC: {metrics['roc_auc']:.4f}")
            
            return model, metrics
    
    def train_lightgbm(self, X_train, X_test, y_train, y_test):
        """Train LightGBM model."""
        with mlflow.start_run(run_name='lightgbm-tuned'):
            logger.info("Training LightGBM...")
            
            # Calculate scale_pos_weight
            scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()
            
            params = {
                'num_leaves': 31,
                'max_depth': 6,
                'learning_rate': 0.1,
                'n_estimators': 200,
                'objective': 'binary',
                'metric': 'auc',
                'scale_pos_weight': scale_pos_weight,
                'random_state': 42,
                'n_jobs': -1
            }
            
            model = lgb.LGBMClassifier(**params)
            
            # Train with early stopping
            model.fit(
                X_train, y_train,
                eval_set=[(X_test, y_test)],
                callbacks=[lgb.early_stopping(20)]
            )
            
            # Predict
            y_pred_proba = model.predict_proba(X_test)[:, 1]
            
            # Evaluate
            metrics = self.evaluate_model(y_test, y_pred_proba)
            
            # Log parameters
            for key, value in params.items():
                mlflow.log_param(key, value)
            
            # Log metrics
            for key, value in metrics.items():
                if not isinstance(value, list):
                    mlflow.log_metric(key, value)
            
            # Log model
            mlflow.lightgbm.log_model(model, 'model')
            
            logger.info(f"LightGBM - PR-AUC: {metrics['pr_auc']:.4f}, ROC-AUC: {metrics['roc_auc']:.4f}")
            
            return model, metrics
    
    def run_training(self):
        """Run complete training pipeline."""
        logger.info("Starting training pipeline...")
        
        # Load data
        df = self.load_data()
        
        # Prepare features
        X_train, X_test, y_train, y_test, feature_names, encoders = self.prepare_features(df)
        
        # Train models
        results = {}
        
        # 1. Logistic Regression
        lr_model, scaler, lr_metrics = self.train_logistic_regression(
            X_train, X_test, y_train, y_test
        )
        results['logistic_regression'] = lr_metrics
        
        # 2. XGBoost
        xgb_model, xgb_metrics = self.train_xgboost(
            X_train, X_test, y_train, y_test
        )
        results['xgboost'] = xgb_metrics
        
        # 3. LightGBM
        lgb_model, lgb_metrics = self.train_lightgbm(
            X_train, X_test, y_train, y_test
        )
        results['lightgbm'] = lgb_metrics
        
        # Select best model (based on PR-AUC)
        best_model_name = max(results, key=lambda k: results[k]['pr_auc'])
        logger.info(f"Best model: {best_model_name} (PR-AUC: {results[best_model_name]['pr_auc']:.4f})")
        
        return results, best_model_name


# Main execution
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Train fraud detection models')
    parser.add_argument('--gold-path', required=True, help='S3 path to Gold layer data')
    parser.add_argument('--mlflow-uri', default='http://localhost:5000', help='MLflow tracking URI')
    args = parser.parse_args()
    
    trainer = FraudModelTrainer(
        gold_s3_path=args.gold_path,
        mlflow_tracking_uri=args.mlflow_uri
    )
    
    results, best_model = trainer.run_training()
    
    print("\n=== Training Results ===")
    for model_name, metrics in results.items():
        print(f"\n{model_name}:")
        print(f"  PR-AUC: {metrics['pr_auc']:.4f}")
        print(f"  ROC-AUC: {metrics['roc_auc']:.4f}")
        print(f"  Precision: {metrics['precision']:.4f}")
        print(f"  Recall: {metrics['recall']:.4f}")
    
    print(f"\n✅ Best model: {best_model}")
