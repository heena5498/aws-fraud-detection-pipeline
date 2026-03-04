# Fraud Detection ML Model Drift Monitoring
# Population Stability Index (PSI) calculation

import pandas as pd
import numpy as np
from pathlib import Path
import yaml
from typing import Dict, List
from loguru import logger
from datetime import datetime


class DriftMonitor:
    """Monitor model and data drift using PSI."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize drift monitor."""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.gold_path = Path(self.config['data']['gold_path'])
        
        logger.info("Drift Monitor initialized")
    
    def calculate_psi(
        self, 
        expected: pd.Series, 
        actual: pd.Series, 
        n_bins: int = 10
    ) -> float:
        """
        Calculate Population Stability Index (PSI).
        
        PSI measures distribution shift between two datasets.
        - PSI < 0.1: No significant drift
        - 0.1 <= PSI < 0.25: Moderate drift, investigate
        - PSI >= 0.25: Significant drift, retrain model
        """
        # Create bins based on expected distribution
        bins = np.percentile(expected, np.linspace(0, 100, n_bins + 1))
        bins = np.unique(bins)  # Remove duplicates
        
        # Bin both distributions
        expected_counts = pd.cut(expected, bins=bins, include_lowest=True).value_counts()
        actual_counts = pd.cut(actual, bins=bins, include_lowest=True).value_counts()
        
        # Calculate percentages
        expected_pct = expected_counts / len(expected)
        actual_pct = actual_counts / len(actual)
        
        # Avoid division by zero
        expected_pct = expected_pct.replace(0, 0.0001)
        actual_pct = actual_pct.replace(0, 0.0001)
        
        # Calculate PSI
        psi = np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct))
        
        return psi
    
    def monitor_features(
        self, 
        baseline_df: pd.DataFrame, 
        current_df: pd.DataFrame,
        feature_cols: List[str]
    ) -> Dict[str, float]:
        """Monitor drift for multiple features."""
        logger.info("Calculating PSI for features...")
        
        psi_scores = {}
        for feature in feature_cols:
            if feature in baseline_df.columns and feature in current_df.columns:
                # Only calculate for numeric features
                if pd.api.types.is_numeric_dtype(baseline_df[feature]):
                    psi = self.calculate_psi(
                        baseline_df[feature].dropna(),
                        current_df[feature].dropna()
                    )
                    psi_scores[feature] = psi
        
        return psi_scores
    
    def get_drift_level(self, psi: float) -> str:
        """Determine drift level based on PSI thresholds."""
        thresholds = self.config['monitoring']['psi']
        
        if psi < thresholds['low_drift']:
            return "NO_DRIFT"
        elif psi < thresholds['medium_drift']:
            return "LOW_DRIFT"
        elif psi < thresholds['high_drift']:
            return "MEDIUM_DRIFT"
        else:
            return "HIGH_DRIFT"
    
    def generate_drift_report(self, psi_scores: Dict[str, float]):
        """Generate drift monitoring report."""
        logger.info("=" * 60)
        logger.info("DRIFT MONITORING REPORT")
        logger.info("=" * 60)
        
        # Sort by PSI (highest drift first)
        sorted_scores = sorted(psi_scores.items(), key=lambda x: x[1], reverse=True)
        
        drift_summary = {
            'NO_DRIFT': 0,
            'LOW_DRIFT': 0,
            'MEDIUM_DRIFT': 0,
            'HIGH_DRIFT': 0
        }
        
        logger.info(f"{'Feature':<40} {'PSI':>10} {'Status':>15}")
        logger.info("-" * 65)
        
        for feature, psi in sorted_scores[:20]:  # Top 20
            drift_level = self.get_drift_level(psi)
            drift_summary[drift_level] += 1
            
            # Color coding for terminal
            if drift_level == 'HIGH_DRIFT':
                status_symbol = "🔴"
            elif drift_level == 'MEDIUM_DRIFT':
                status_symbol = "🟡"
            elif drift_level == 'LOW_DRIFT':
                status_symbol = "🟢"
            else:
                status_symbol = "✓"
            
            logger.info(f"{feature:<40} {psi:>10.4f} {status_symbol} {drift_level:>14}")
        
        logger.info("=" * 60)
        logger.info("SUMMARY")
        logger.info(f"No Drift:     {drift_summary['NO_DRIFT']}")
        logger.info(f"Low Drift:    {drift_summary['LOW_DRIFT']}")
        logger.info(f"Medium Drift: {drift_summary['MEDIUM_DRIFT']}")
        logger.info(f"High Drift:   {drift_summary['HIGH_DRIFT']}")
        logger.info("=" * 60)
        
        # Recommendation
        if drift_summary['HIGH_DRIFT'] > 0 or drift_summary['MEDIUM_DRIFT'] > 5:
            logger.warning("⚠️  RECOMMENDATION: Model retraining recommended")
        elif drift_summary['MEDIUM_DRIFT'] > 0:
            logger.info("ℹ️  RECOMMENDATION: Monitor closely, retraining may be needed soon")
        else:
            logger.info("✓ RECOMMENDATION: No action needed")
        
        return drift_summary


def main():
    """Run drift monitoring."""
    logger.info("Starting drift monitoring...")
    
    monitor = DriftMonitor()
    
    # Load baseline (training) data
    gold_path = Path(monitor.config['data']['gold_path'])
    train_files = sorted(gold_path.glob("train_*.parquet"))
    
    if not train_files:
        logger.error("No training data found")
        return
    
    baseline_df = pd.read_parquet(train_files[-1])
    logger.info(f"Loaded baseline data: {len(baseline_df):,} samples")
    
    # In practice, you'd load recent production data
    # For demo, we'll use test data as "current" data
    test_files = sorted(gold_path.glob("test_*.parquet"))
    if not test_files:
        logger.error("No test data found")
        return
    
    current_df = pd.read_parquet(test_files[-1])
    logger.info(f"Loaded current data: {len(current_df):,} samples")
    
    # Get feature columns
    feature_cols = [col for col in baseline_df.columns if col != 'is_fraud']
    
    # Monitor drift
    psi_scores = monitor.monitor_features(baseline_df, current_df, feature_cols)
    
    # Generate report
    drift_summary = monitor.generate_drift_report(psi_scores)


if __name__ == "__main__":
    main()
