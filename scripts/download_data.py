"""
Download Sample Fraud Detection Dataset
========================================
Downloads PaySim dataset or generates synthetic data
"""

import pandas as pd
import numpy as np
from pathlib import Path
from loguru import logger
from datetime import datetime, timedelta
import yaml


def generate_synthetic_transactions(n_samples: int = 100000) -> pd.DataFrame:
    """
    Generate synthetic transaction data for fraud detection.
    This is a simplified version - you can replace this with actual dataset download.
    """
    logger.info(f"Generating {n_samples:,} synthetic transactions...")
    
    np.random.seed(42)
    
    # Generate timestamps over 30 days
    start_date = datetime.now() - timedelta(days=30)
    timestamps = [start_date + timedelta(seconds=int(x)) for x in sorted(np.random.randint(0, 30*24*3600, n_samples))]
    
    # Generate user IDs (10,000 unique users)
    user_ids = [f"user_{np.random.randint(1, 10001)}" for _ in range(n_samples)]
    
    # Generate merchant IDs (5,000 unique merchants)
    merchant_ids = [f"merchant_{np.random.randint(1, 5001)}" for _ in range(n_samples)]
    
    # Generate transaction amounts (log-normal distribution)
    amounts = np.random.lognormal(mean=4, sigma=1.5, size=n_samples)
    amounts = np.clip(amounts, 1, 10000)  # Clip to reasonable range
    
    # Merchant categories
    categories = ['retail', 'grocery', 'restaurant', 'gas_station', 'online', 'entertainment', 'travel', 'other']
    merchant_categories = np.random.choice(categories, n_samples, p=[0.25, 0.15, 0.15, 0.10, 0.15, 0.08, 0.07, 0.05])
    
    # Countries
    countries = ['US', 'UK', 'CA', 'FR', 'DE', 'AU']
    transaction_countries = np.random.choice(countries, n_samples, p=[0.50, 0.15, 0.12, 0.10, 0.08, 0.05])
    
    # Generate fraud labels (2% fraud rate)
    is_fraud = np.random.choice([0, 1], n_samples, p=[0.98, 0.02])
    
    # Make fraud transactions look suspicious
    fraud_mask = is_fraud == 1
    
    # Fraud transactions tend to:
    # - Have higher amounts
    amounts[fraud_mask] *= np.random.uniform(2, 5, size=fraud_mask.sum())
    
    # - Occur at unusual times (late night)
    for i in np.where(fraud_mask)[0]:
        hour = np.random.choice([0, 1, 2, 3, 4, 5, 23])
        timestamps[i] = timestamps[i].replace(hour=hour)
    
    # - Be from online merchants
    merchant_categories[fraud_mask] = np.random.choice(
        ['online', 'travel'],
        size=fraud_mask.sum(),
        p=[0.7, 0.3]
    )
    
    # Create DataFrame
    df = pd.DataFrame({
        'transaction_id': [f"txn_{i+1:08d}" for i in range(n_samples)],
        'timestamp': timestamps,
        'amount': amounts,
        'user_id': user_ids,
        'merchant_id': merchant_ids,
        'merchant_category': merchant_categories,
        'country': transaction_countries,
        'is_fraud': is_fraud
    })
    
    # Sort by timestamp
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    logger.info(f"✓ Generated {len(df):,} transactions")
    logger.info(f"  Fraud rate: {df['is_fraud'].mean():.2%}")
    logger.info(f"  Date range: {df['timestamp'].min()} to {df['timestamp'].max()}")
    logger.info(f"  Unique users: {df['user_id'].nunique():,}")
    logger.info(f"  Unique merchants: {df['merchant_id'].nunique():,}")
    
    return df


def download_paysim_dataset():
    """
    Download PaySim dataset from Kaggle.
    NOTE: Requires Kaggle API credentials.
    
    Setup:
    1. Install kaggle: pip install kaggle
    2. Get API token from https://www.kaggle.com/settings
    3. Place kaggle.json in ~/.kaggle/
    """
    try:
        import kaggle
        logger.info("Downloading PaySim dataset from Kaggle...")
        
        # Download dataset
        kaggle.api.dataset_download_files(
            'ealaxi/paysim1',
            path='data/raw',
            unzip=True
        )
        
        logger.info("✓ Dataset downloaded successfully")
        return True
    
    except ImportError:
        logger.warning("Kaggle package not installed. Using synthetic data instead.")
        logger.info("To use real datasets, install: pip install kaggle")
        return False
    
    except Exception as e:
        logger.warning(f"Failed to download from Kaggle: {str(e)}")
        logger.info("Using synthetic data instead.")
        return False


def main():
    """Download or generate transaction data."""
    logger.info("=" * 60)
    logger.info("DATA DOWNLOAD - Starting")
    logger.info("=" * 60)
    
    # Create data directory
    data_path = Path("data/raw")
    data_path.mkdir(parents=True, exist_ok=True)
    
    # Try to download real dataset
    downloaded = download_paysim_dataset()
    
    # If download failed, generate synthetic data
    if not downloaded:
        logger.info("Generating synthetic transaction data...")
        df = generate_synthetic_transactions(n_samples=100000)
        
        # Save to CSV
        output_path = data_path / "transactions.csv"
        df.to_csv(output_path, index=False)
        
        logger.info(f"✓ Saved synthetic data to: {output_path}")
        logger.info(f"  File size: {output_path.stat().st_size / 1024 / 1024:.2f} MB")
    
    logger.info("=" * 60)
    logger.info("✓ DATA DOWNLOAD - Complete")
    logger.info("=" * 60)
    logger.info("\nNext steps:")
    logger.info("  1. Run: python etl/bronze_layer.py")
    logger.info("  2. Run: python etl/silver_layer.py")
    logger.info("  3. Run: python etl/gold_layer.py")
    logger.info("  4. Run: python ml/train.py")


if __name__ == "__main__":
    main()
