"""
Drift Monitoring Lambda
Daily PSI (Population Stability Index) calculation to detect data drift.

Triggers:
- EventBridge cron (daily at 1 AM UTC)

Actions:
- Calculate PSI for key features
- If PSI > threshold, publish SNS alert for retraining
"""

import boto3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common.logger import get_logger
from common.config import get_config
from common.metrics import emit_metric, emit_counter

logger = get_logger(__name__)
config = get_config()


def calculate_psi(baseline: pd.Series, current: pd.Series, bins: int = 10) -> float:
    """
    Calculate Population Stability Index (PSI).
    
    PSI measures distribution drift:
    - PSI < 0.1: No significant change
    - 0.1 ≤ PSI < 0.25: Moderate change (investigate)
    - PSI ≥ 0.25: Significant change (retrain model)
    
    Args:
        baseline: Baseline feature distribution
        current: Current feature distribution
        bins: Number of bins for discretization
    
    Returns:
        PSI score
    """
    # Create bins based on baseline quantiles
    breakpoints = np.percentile(baseline, np.linspace(0, 100, bins + 1))
    breakpoints = np.unique(breakpoints)  # Remove duplicates
    
    if len(breakpoints) < 2:
        logger.warning(f"Insufficient unique values for binning")
        return 0.0
    
    # Bin both distributions
    baseline_binned = pd.cut(baseline, bins=breakpoints, include_lowest=True, duplicates='drop')
    current_binned = pd.cut(current, bins=breakpoints, include_lowest=True, duplicates='drop')
    
    # Calculate proportions
    baseline_props = baseline_binned.value_counts(normalize=True, dropna=False)
    current_props = current_binned.value_counts(normalize=True, dropna=False)
    
    # Align indices
    baseline_props, current_props = baseline_props.align(current_props, fill_value=0.0001)
    
    # PSI formula: sum((Current% - Baseline%) * ln(Current% / Baseline%))
    psi = ((current_props - baseline_props) * np.log(current_props / baseline_props)).sum()
    
    return abs(psi)


def load_baseline_stats(s3_bucket: str, s3_key: str) -> pd.DataFrame:
    """Load baseline feature statistics from S3."""
    s3 = boto3.client('s3')
    
    local_path = '/tmp/baseline_stats.parquet'
    s3.download_file(s3_bucket, s3_key, local_path)
    
    df = pd.read_parquet(local_path)
    logger.info(f"Loaded baseline stats: {len(df)} records")
    
    return df


def load_current_data(s3_bucket: str, s3_prefix: str, lookback_days: int = 1) -> pd.DataFrame:
    """Load recent data for drift detection."""
    # Query Athena for recent data
    athena = boto3.client('athena')
    
    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=lookback_days)
    
    query = f"""
    SELECT
        amount,
        user_txn_count_1h,
        user_avg_amount_1h,
        merchant_fraud_rate,
        amount_vs_user_avg_ratio,
        hour_of_day,
        day_of_week
    FROM "{config.glue_database}"."transactions"
    WHERE year = {end_date.year}
      AND month = {end_date.month:02d}
      AND day >= {start_date.day:02d}
      AND day <= {end_date.day:02d}
    """
    
    # Execute query
    response = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={'Database': config.glue_database},
        ResultConfiguration={'OutputLocation': f's3://{s3_bucket}/athena-results/'}
    )
    
    query_id = response['QueryExecutionId']
    
    # Wait for completion
    import time
    while True:
        status = athena.get_query_execution(QueryExecutionId=query_id)
        state = status['QueryExecution']['Status']['State']
        
        if state == 'SUCCEEDED':
            break
        elif state in ['FAILED', 'CANCELLED']:
            raise Exception(f"Query failed: {state}")
        
        time.sleep(2)
    
    # Download results
    result_location = status['QueryExecution']['ResultConfiguration']['OutputLocation']
    result_key = result_location.replace(f's3://{s3_bucket}/', '')
    
    local_path = '/tmp/current_data.csv'
    s3 = boto3.client('s3')
    s3.download_file(s3_bucket, result_key, local_path)
    
    df = pd.read_csv(local_path)
    logger.info(f"Loaded current data: {len(df)} records")
    
    return df


def detect_drift(baseline_df: pd.DataFrame, current_df: pd.DataFrame) -> dict:
    """
    Detect drift across all features.
    
    Returns:
        Dict with PSI scores and drift status
    """
    feature_cols = [
        'amount',
        'user_txn_count_1h',
        'user_avg_amount_1h',
        'merchant_fraud_rate',
        'amount_vs_user_avg_ratio',
        'hour_of_day',
        'day_of_week'
    ]
    
    psi_scores = {}
    drift_detected = False
    
    for feature in feature_cols:
        if feature not in baseline_df.columns or feature not in current_df.columns:
            logger.warning(f"Feature {feature} not found in data")
            continue
        
        psi = calculate_psi(
            baseline_df[feature].dropna(),
            current_df[feature].dropna()
        )
        
        psi_scores[feature] = psi
        
        # Log PSI to CloudWatch
        emit_metric(f'psi_{feature}', psi, 'None')
        
        logger.info(f"PSI for {feature}: {psi:.4f}")
        
        # Check threshold
        if psi >= config.psi_threshold:
            logger.warning(f"Drift detected for {feature}: PSI={psi:.4f}")
            drift_detected = True
    
    # Overall metrics
    max_psi = max(psi_scores.values())
    avg_psi = np.mean(list(psi_scores.values()))
    
    emit_metric('psi_max', max_psi, 'None')
    emit_metric('psi_avg', avg_psi, 'None')
    
    if drift_detected:
        emit_counter('drift_detected', 1)
    
    return {
        'psi_scores': psi_scores,
        'max_psi': max_psi,
        'avg_psi': avg_psi,
        'drift_detected': drift_detected,
        'threshold': config.psi_threshold
    }


def trigger_retraining(drift_report: dict):
    """Trigger Step Functions retraining workflow."""
    sf_client = boto3.client('stepfunctions')
    
    state_machine_arn = os.environ.get('RETRAIN_STATE_MACHINE_ARN')
    
    if not state_machine_arn:
        logger.warning("Retrain state machine ARN not configured")
        return
    
    execution_input = {
        'drift_report': drift_report,
        'triggered_at': datetime.now().isoformat(),
        'reason': 'drift_detection'
    }
    
    response = sf_client.start_execution(
        stateMachineArn=state_machine_arn,
        input=json.dumps(execution_input)
    )
    
    logger.info(f"Started retraining workflow: {response['executionArn']}")


def lambda_handler(event, context):
    """
    Lambda handler for drift monitoring.
    
    Event: EventBridge scheduled event
    """
    logger.info("Starting drift monitoring...")
    
    try:
        # Load baseline stats
        baseline_df = load_baseline_stats(
            config.gold_bucket,
            'feature_stats/baseline/part-00000.parquet'
        )
        
        # Load current data
        current_df = load_current_data(
            config.silver_bucket,
            'transactions',
            lookback_days=1
        )
        
        # Detect drift
        drift_report = detect_drift(baseline_df, current_df)
        
        logger.info(f"Drift detection complete: {drift_report}")
        
        # Trigger retraining if needed
        if drift_report['drift_detected']:
            logger.warning("Significant drift detected - triggering retraining")
            trigger_retraining(drift_report)
        
        return {
            'statusCode': 200,
            'body': json.dumps(drift_report, default=str)
        }
    
    except Exception as e:
        logger.error(f"Drift monitoring failed: {e}", exc_info=True)
        emit_counter('drift_monitor_errors', 1)
        
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


# For local testing
if __name__ == "__main__":
    # Simulate EventBridge event
    event = {}
    context = None
    
    result = lambda_handler(event, context)
    print(json.dumps(result, indent=2))
