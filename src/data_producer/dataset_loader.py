"""
Dataset loader for PaySim or Kaggle credit card fraud datasets.
Handles different schema formats and provides unified output.
"""

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


def load_dataset(file_path: str) -> pd.DataFrame:
    """
    Load and normalize fraud detection dataset.
    
    Supports:
    - PaySim (https://www.kaggle.com/datasets/ealaxi/paysim1)
    - Kaggle Credit Card Fraud (https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud)
    - Custom synthetic data
    
    Returns DataFrame with normalized schema:
        - transaction_id
        - timestamp
        - amount
        - user_id
        - merchant_id
        - merchant_category
        - country
        - is_fraud
    """
    logger.info(f"Loading dataset from {file_path}")
    
    # Load CSV
    df = pd.read_csv(file_path)
    
    # Detect dataset type and normalize
    if 'nameOrig' in df.columns:
        # PaySim dataset
        logger.info("Detected PaySim dataset format")
        df_norm = normalize_paysim(df)
    
    elif 'Time' in df.columns and 'V1' in df.columns:
        # Kaggle Credit Card Fraud dataset
        logger.info("Detected Kaggle Credit Card Fraud dataset format")
        df_norm = normalize_kaggle_cc(df)
    
    elif 'transaction_id' in df.columns:
        # Already normalized or custom dataset
        logger.info("Dataset appears to be pre-normalized")
        df_norm = df
    
    else:
        raise ValueError(
            f"Unknown dataset format. Expected PaySim, Kaggle CC, or normalized format. "
            f"Columns: {df.columns.tolist()}"
        )
    
    # Validate required columns
    required = ['transaction_id', 'timestamp', 'amount', 'user_id', 'is_fraud']
    missing = set(required) - set(df_norm.columns)
    if missing:
        raise ValueError(f"Missing required columns after normalization: {missing}")
    
    logger.info(f"Loaded {len(df_norm):,} transactions")
    logger.info(f"Fraud rate: {df_norm['is_fraud'].mean():.2%}")
    
    return df_norm


def normalize_paysim(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize PaySim dataset.
    
    PaySim columns:
        step, type, amount, nameOrig, oldbalanceOrg, newbalanceOrig,
        nameDest, oldbalanceDest, newbalanceDest, isFraud, isFlaggedFraud
    """
    # Create synthetic timestamps (1 step = 1 hour in simulation)
    start_date = datetime.now() - timedelta(days=30)
    df['timestamp'] = df['step'].apply(
        lambda x: start_date + timedelta(hours=x)
    )
    
    # Generate transaction IDs
    df['transaction_id'] = df.apply(
        lambda row: f"txn_{row['step']:08d}_{hash(row['nameOrig']) % 100000:05d}",
        axis=1
    )
    
    # Map fields
    df_norm = pd.DataFrame({
        'transaction_id': df['transaction_id'],
        'timestamp': df['timestamp'],
        'amount': df['amount'],
        'user_id': df['nameOrig'],  # Will be hashed in Silver
        'merchant_id': df['nameDest'],
        'merchant_category': df['type'],  # PAYMENT, TRANSFER, CASH_OUT, DEBIT, CASH_IN
        'country': 'US',  # PaySim doesn't have geo data, use default
        'city': None,
        'is_fraud': df['isFraud'].astype(int),
        'old_balance': df['oldbalanceOrg'],
        'new_balance': df['newbalanceOrig']
    })
    
    return df_norm


def normalize_kaggle_cc(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize Kaggle Credit Card Fraud dataset.
    
    Kaggle columns:
        Time, V1-V28 (PCA features), Amount, Class
    """
    # Convert Time (seconds from first transaction) to timestamps
    start_date = datetime.now() - timedelta(days=2)
    df['timestamp'] = df['Time'].apply(
        lambda x: start_date + timedelta(seconds=x)
    )
    
    # Generate IDs
    df['transaction_id'] = df.apply(
        lambda row: f"txn_{int(row['Time']):010d}_{int(row['Amount'] * 100):06d}",
        axis=1
    )
    
    # Generate synthetic user/merchant IDs from PCA features
    # Use V1, V2 for user clustering
    df['user_cluster'] = pd.cut(df['V1'], bins=1000, labels=False)
    df['user_id'] = df['user_cluster'].apply(lambda x: f"user_{x:04d}")
    
    # Use V3, V4 for merchant clustering
    df['merchant_cluster'] = pd.cut(df['V3'], bins=500, labels=False)
    df['merchant_id'] = df['merchant_cluster'].apply(lambda x: f"merchant_{x:04d}")
    
    # Infer merchant category from amount patterns
    df['merchant_category'] = pd.cut(
        df['Amount'],
        bins=[0, 10, 50, 200, 1000, np.inf],
        labels=['convenience', 'grocery', 'retail', 'electronics', 'luxury']
    )
    
    # Map fields
    df_norm = pd.DataFrame({
        'transaction_id': df['transaction_id'],
        'timestamp': df['timestamp'],
        'amount': df['Amount'],
        'user_id': df['user_id'],
        'merchant_id': df['merchant_id'],
        'merchant_category': df['merchant_category'].astype(str),
        'country': 'US',
        'city': None,
        'is_fraud': df['Class'].astype(int)
    })
    
    # Optionally include PCA features (for enrichment in Silver layer)
    pca_cols = [f'V{i}' for i in range(1, 29)]
    for col in pca_cols:
        if col in df.columns:
            df_norm[col] = df[col]
    
    return df_norm


def generate_synthetic_data(n_samples: int = 10000) -> pd.DataFrame:
    """
    Generate synthetic fraud detection dataset for testing.
    """
    logger.info(f"Generating {n_samples:,} synthetic transactions")
    
    np.random.seed(42)
    
    # Generate base data
    start_date = datetime.now() - timedelta(days=30)
    timestamps = [
        start_date + timedelta(seconds=x)
        for x in sorted(np.random.randint(0, 30 * 24 * 3600, n_samples))
    ]
    
    amounts = np.random.lognormal(mean=4, sigma=1.5, size=n_samples)
    amounts = np.clip(amounts, 1, 10000)
    
    user_ids = [f"user_{np.random.randint(1, 5001)}" for _ in range(n_samples)]
    merchant_ids = [f"merchant_{np.random.randint(1, 2001)}" for _ in range(n_samples)]
    
    categories = ['retail', 'grocery', 'restaurant', 'gas', 'online', 'travel']
    merchant_categories = np.random.choice(categories, n_samples)
    
    countries = ['US', 'UK', 'CA']
    country_list = np.random.choice(countries, n_samples, p=[0.7, 0.2, 0.1])
    
    # Generate fraud labels (2% fraud rate)
    is_fraud = np.random.choice([0, 1], n_samples, p=[0.98, 0.02])
    
    # Make fraud transactions look suspicious
    fraud_mask = is_fraud == 1
    amounts[fraud_mask] *= np.random.uniform(2, 5, size=fraud_mask.sum())
    merchant_categories[fraud_mask] = np.random.choice(['online', 'travel'], size=fraud_mask.sum())
    
    # Create DataFrame
    df = pd.DataFrame({
        'transaction_id': [f"txn_{i+1:08d}" for i in range(n_samples)],
        'timestamp': timestamps,
        'amount': amounts,
        'user_id': user_ids,
        'merchant_id': merchant_ids,
        'merchant_category': merchant_categories,
        'country': country_list,
        'city': None,
        'is_fraud': is_fraud
    })
    
    logger.info(f"Generated {len(df):,} transactions ({df['is_fraud'].mean():.2%} fraud rate)")
    
    return df


if __name__ == "__main__":
    # Test with synthetic data
    df = generate_synthetic_data(1000)
    print(df.head())
    print(f"\nFraud rate: {df['is_fraud'].mean():.2%}")
