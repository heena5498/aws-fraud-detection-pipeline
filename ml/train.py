"""
ML Training Pipeline
===================
Train fraud detection models with MLflow tracking
"""

import pandas as pd
import numpy as np
import yaml
import joblib
import mlflow
import mlflow.sklearn
import mlflow.xgboost
from pathlib import Path
from typing import Tuple, Dict
from loguru import logger
from datetime import datetime

# ML libraries
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier

# Metrics
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, confusion_matrix, classification_report,
    precision_recall_curve, roc_curve
)

# Handling imbalance
from imblearn.over_sampling import SMOTE
from imblearn.under_sampling import RandomUnderSampler


class FraudModelTrainer:
    """Train and evaluate fraud detection models."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize trainer with configuration."""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.gold_path = Path(self.config['data']['gold_path'])
        self.model_path = Path("ml/models")
        self.model_path.mkdir(parents=True, exist_ok=True)
        
        # Setup MLflow
        mlflow.set_tracking_uri(self.config['mlflow']['tracking_uri'])
        mlflow.set_experiment(self.config['mlflow']['experiment_name'])
        
        logger.info("Model Trainer initialized")
    
    def load_data(self) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        """Load train/test data from Gold layer."""
        logger.info("Loading train/test data from Gold layer...")
        
        # Get most recent train/test files
        train_files = sorted(self.gold_path.glob("train_*.parquet"))
        test_files = sorted(self.gold_path.glob("test_*.parquet"))
        
        if not train_files or not test_files:
            raise FileNotFoundError("Train/test files not found in Gold layer")
        
        train_df = pd.read_parquet(train_files[-1])
        test_df = pd.read_parquet(test_files[-1])
        
        # Separate features and target
        X_train = train_df.drop(columns=['is_fraud'])
        y_train = train_df['is_fraud']
        X_test = test_df.drop(columns=['is_fraud'])
        y_test = test_df['is_fraud']
        
        logger.info(f"Train: {len(X_train):,} samples, Test: {len(X_test):,} samples")
        logger.info(f"Features: {len(X_train.columns)}")
        logger.info(f"Fraud rate - Train: {y_train.mean():.2%}, Test: {y_test.mean():.2%}")
        
        # Encode categorical variables
        X_train, X_test = self.encode_categorical_features(X_train, X_test)
        
        return X_train, X_test, y_train, y_test
    
    def encode_categorical_features(self, X_train: pd.DataFrame, X_test: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Encode categorical features using one-hot encoding."""
        logger.info("Encoding categorical features...")
        
        # Identify categorical columns
        categorical_cols = X_train.select_dtypes(include=['object']).columns.tolist()
        
        if categorical_cols:
            logger.info(f"Found {len(categorical_cols)} categorical columns: {categorical_cols}")
            
            # One-hot encode
            X_train = pd.get_dummies(X_train, columns=categorical_cols, drop_first=True)
            X_test = pd.get_dummies(X_test, columns=categorical_cols, drop_first=True)
            
            # Align columns (in case test has different categories)
            X_train, X_test = X_train.align(X_test, join='left', axis=1, fill_value=0)
            
            logger.info(f"✓ After encoding: {len(X_train.columns)} features")
        
        return X_train, X_test
    
    def handle_class_imbalance(
        self, 
        X_train: pd.DataFrame, 
        y_train: pd.Series
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """Handle class imbalance using SMOTE or undersampling."""
        strategy = self.config['ml']['sampling_strategy']
        
        if strategy == 'none':
            logger.info("No resampling applied")
            return X_train, y_train
        
        logger.info(f"Applying {strategy} for class imbalance...")
        original_fraud_rate = y_train.mean()
        
        if strategy == 'smote':
            sampler = SMOTE(random_state=self.config['ml']['random_state'])
        elif strategy == 'undersample':
            sampler = RandomUnderSampler(random_state=self.config['ml']['random_state'])
        else:
            logger.warning(f"Unknown sampling strategy: {strategy}. Skipping.")
            return X_train, y_train
        
        X_resampled, y_resampled = sampler.fit_resample(X_train, y_train)
        
        logger.info(f"Before: {len(y_train):,} samples ({original_fraud_rate:.2%} fraud)")
        logger.info(f"After: {len(y_resampled):,} samples ({y_resampled.mean():.2%} fraud)")
        
        return X_resampled, y_resampled
    
    def get_model(self, model_type: str):
        """Get model instance based on configuration."""
        if model_type == 'logistic':
            return LogisticRegression(
                random_state=self.config['ml']['random_state'],
                max_iter=1000,
                class_weight='balanced'
            )
        
        elif model_type == 'xgboost':
            params = self.config['ml']['xgboost']
            return XGBClassifier(
                random_state=self.config['ml']['random_state'],
                **params
            )
        
        elif model_type == 'lightgbm':
            params = self.config['ml']['lightgbm']
            return LGBMClassifier(
                random_state=self.config['ml']['random_state'],
                verbose=-1,
                **params
            )
        
        else:
            raise ValueError(f"Unknown model type: {model_type}")
    
    def evaluate_model(
        self,
        model,
        X_test: pd.DataFrame,
        y_test: pd.Series,
        threshold: float = 0.5
    ) -> Dict:
        """Evaluate model performance."""
        logger.info("Evaluating model...")
        
        # Predictions
        y_pred_proba = model.predict_proba(X_test)[:, 1]
        y_pred = (y_pred_proba >= threshold).astype(int)
        
        # Metrics
        metrics = {
            'accuracy': accuracy_score(y_test, y_pred),
            'precision': precision_score(y_test, y_pred, zero_division=0),
            'recall': recall_score(y_test, y_pred, zero_division=0),
            'f1': f1_score(y_test, y_pred, zero_division=0),
            'auc_roc': roc_auc_score(y_test, y_pred_proba),
        }
        
        # Confusion matrix
        cm = confusion_matrix(y_test, y_pred)
        tn, fp, fn, tp = cm.ravel()
        
        metrics.update({
            'true_negatives': int(tn),
            'false_positives': int(fp),
            'false_negatives': int(fn),
            'true_positives': int(tp),
            'false_positive_rate': fp / (fp + tn) if (fp + tn) > 0 else 0,
        })
        
        # Log metrics
        logger.info("=" * 60)
        logger.info("MODEL EVALUATION RESULTS")
        logger.info("=" * 60)
        logger.info(f"Accuracy:  {metrics['accuracy']:.4f}")
        logger.info(f"Precision: {metrics['precision']:.4f}")
        logger.info(f"Recall:    {metrics['recall']:.4f}")
        logger.info(f"F1-Score:  {metrics['f1']:.4f}")
        logger.info(f"AUC-ROC:   {metrics['auc_roc']:.4f}")
        logger.info(f"FPR:       {metrics['false_positive_rate']:.4f}")
        logger.info("=" * 60)
        logger.info(f"Confusion Matrix:")
        logger.info(f"  TN: {tn:,}  FP: {fp:,}")
        logger.info(f"  FN: {fn:,}  TP: {tp:,}")
        logger.info("=" * 60)
        
        return metrics
    
    def get_feature_importance(self, model, feature_names) -> pd.DataFrame:
        """Get feature importance from model."""
        if hasattr(model, 'feature_importances_'):
            importance_df = pd.DataFrame({
                'feature': feature_names,
                'importance': model.feature_importances_
            }).sort_values('importance', ascending=False)
            
            logger.info("\nTop 10 Most Important Features:")
            logger.info(importance_df.head(10).to_string(index=False))
            
            return importance_df
        else:
            logger.info("Model does not support feature importance")
            return None
    
    def train_and_evaluate(self):
        """Full training pipeline with MLflow tracking."""
        logger.info("=" * 60)
        logger.info("STARTING MODEL TRAINING")
        logger.info("=" * 60)
        
        # Load data
        X_train, X_test, y_train, y_test = self.load_data()
        
        # Handle class imbalance
        X_train_sampled, y_train_sampled = self.handle_class_imbalance(X_train, y_train)
        
        # Get model
        model_type = self.config['ml']['model_type']
        logger.info(f"Training {model_type} model...")
        
        with mlflow.start_run(run_name=f"{model_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"):
            # Log parameters
            mlflow.log_param("model_type", model_type)
            mlflow.log_param("n_train_samples", len(X_train_sampled))
            mlflow.log_param("n_test_samples", len(X_test))
            mlflow.log_param("n_features", X_train.shape[1])
            mlflow.log_param("sampling_strategy", self.config['ml']['sampling_strategy'])
            
            # Train model
            model = self.get_model(model_type)
            model.fit(X_train_sampled, y_train_sampled)
            logger.info("✓ Model training complete")
            
            # Evaluate
            metrics = self.evaluate_model(model, X_test, y_test)
            
            # Log metrics to MLflow
            for metric_name, metric_value in metrics.items():
                if isinstance(metric_value, (int, float)):
                    mlflow.log_metric(metric_name, metric_value)
            
            # Feature importance
            importance_df = self.get_feature_importance(model, X_train.columns)
            if importance_df is not None:
                importance_path = self.model_path / "feature_importance.csv"
                importance_df.to_csv(importance_path, index=False)
                mlflow.log_artifact(str(importance_path))
            
            # Save model
            model_filename = f"fraud_model_{model_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pkl"
            model_path = self.model_path / model_filename
            joblib.dump(model, model_path)
            logger.info(f"✓ Model saved: {model_path}")
            
            # Log model to MLflow
            if model_type == 'xgboost':
                mlflow.xgboost.log_model(model, "model")
            else:
                mlflow.sklearn.log_model(model, "model")
            
            # Save as default model for inference
            default_model_path = self.model_path / "fraud_model.pkl"
            joblib.dump(model, default_model_path)
            logger.info(f"✓ Default model updated: {default_model_path}")
        
        logger.info("=" * 60)
        logger.info("✓ TRAINING COMPLETE")
        logger.info("=" * 60)
        
        return model, metrics


def main():
    """Run model training pipeline."""
    trainer = FraudModelTrainer()
    model, metrics = trainer.train_and_evaluate()


if __name__ == "__main__":
    main()
