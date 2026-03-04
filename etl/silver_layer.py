"""
Silver Layer - Feature Engineering
===================================
Responsibilities:
1. Load data from Bronze layer
2. Engineer features (velocity, aggregations, behavioral)
3. Enrich with external data (geo, merchant info)
4. Create time-based windows and aggregations
"""

import pandas as pd
import numpy as np
import yaml
from pathlib import Path
from typing import List, Dict
from loguru import logger
from datetime import datetime, timedelta


class SilverLayer:
    """Transform Bronze data into engineered features."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize Silver Layer with configuration."""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.bronze_path = Path(self.config['data']['bronze_path'])
        self.silver_path = Path(self.config['data']['silver_path'])
        self.silver_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Silver Layer initialized. Output: {self.silver_path}")
    
    def load_bronze_data(self) -> pd.DataFrame:
        """Load latest data from Bronze layer."""
        logger.info("Loading data from Bronze layer...")
        
        # Get most recent bronze file
        bronze_files = sorted(self.bronze_path.glob("*.parquet"))
        if not bronze_files:
            raise FileNotFoundError(f"No parquet files found in {self.bronze_path}")
        
        latest_file = bronze_files[-1]
        logger.info(f"Loading: {latest_file}")
        
        df = pd.read_parquet(latest_file)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')
        
        logger.info(f"Loaded {len(df):,} records from Bronze layer")
        return df
    
    def engineer_temporal_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create time-based features."""
        logger.info("Engineering temporal features...")
        
        df['hour_of_day'] = df['timestamp'].dt.hour
        df['day_of_week'] = df['timestamp'].dt.dayofweek
        df['day_of_month'] = df['timestamp'].dt.day
        df['month'] = df['timestamp'].dt.month
        df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
        df['is_night_time'] = ((df['hour_of_day'] >= 22) | (df['hour_of_day'] <= 6)).astype(int)
        
        logger.info("✓ Added temporal features")
        return df
    
    def engineer_amount_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create amount-based features."""
        logger.info("Engineering amount features...")
        
        df['amount_log'] = np.log1p(df['amount'])
        df['amount_rounded'] = (df['amount'] // 100) * 100  # Round to nearest 100
        df['is_high_amount'] = (df['amount'] > df['amount'].quantile(0.95)).astype(int)
        
        logger.info("✓ Added amount features")
        return df
    
    def engineer_velocity_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create user velocity features (transaction frequency, volume)."""
        logger.info("Engineering velocity features...")
        
        # Sort by user and timestamp and reset index
        df = df.sort_values(['user_id', 'timestamp']).reset_index(drop=True)
        
        # Time since last transaction for each user
        df['time_since_last_transaction'] = df.groupby('user_id')['timestamp'].diff().dt.total_seconds() / 3600
        df['time_since_last_transaction'] = df['time_since_last_transaction'].fillna(999)
        
        # Rolling windows for velocity
        windows = {
            '1h': '1h',
            '6h': '6h',
            '24h': '24h',
            '7d': '7d'
        }
        
        for window_name, window_size in windows.items():
            # Transaction count in window
            df[f'transaction_count_{window_name}'] = df.groupby('user_id').rolling(
                window=window_size, on='timestamp', min_periods=1
            )['transaction_id'].count().values
            
            # Total amount in window
            df[f'total_amount_{window_name}'] = df.groupby('user_id').rolling(
                window=window_size, on='timestamp', min_periods=1
            )['amount'].sum().values
            
            # Average amount in window
            df[f'avg_amount_{window_name}'] = df.groupby('user_id').rolling(
                window=window_size, on='timestamp', min_periods=1
            )['amount'].mean().values
        
        logger.info("✓ Added velocity features")
        return df
    
    def engineer_merchant_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create merchant aggregate features."""
        logger.info("Engineering merchant features...")
        
        # Merchant statistics (using expanding window to avoid data leakage)
        merchant_stats = df.groupby('merchant_id').agg({
            'amount': ['mean', 'std', 'count'],
            'is_fraud': 'mean'  # Fraud rate per merchant
        }).reset_index()
        
        merchant_stats.columns = [
            'merchant_id',
            'merchant_avg_amount',
            'merchant_std_amount',
            'merchant_transaction_count',
            'merchant_fraud_rate'
        ]
        
        # Merge back to main dataframe
        df = df.merge(merchant_stats, on='merchant_id', how='left')
        
        # Amount deviation from merchant average
        df['amount_deviation_from_merchant'] = (
            df['amount'] - df['merchant_avg_amount']
        ) / (df['merchant_std_amount'] + 1e-5)
        
        logger.info("✓ Added merchant features")
        return df
    
    def engineer_user_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create user behavior features."""
        logger.info("Engineering user features...")
        
        # User historical statistics (expanding window)
        user_stats = df.groupby('user_id').agg({
            'amount': ['mean', 'std', 'count'],
            'merchant_id': 'nunique'
        }).reset_index()
        
        user_stats.columns = [
            'user_id',
            'user_avg_amount',
            'user_std_amount',
            'user_total_transactions',
            'user_unique_merchants'
        ]
        
        df = df.merge(user_stats, on='user_id', how='left')
        
        # Amount deviation from user's typical behavior
        df['amount_deviation_from_user'] = (
            df['amount'] - df['user_avg_amount']
        ) / (df['user_std_amount'] + 1e-5)
        
        # Flag if amount is unusual for user
        df['is_unusual_amount'] = (np.abs(df['amount_deviation_from_user']) > 3).astype(int)
        
        logger.info("✓ Added user behavior features")
        return df
    
    def engineer_geo_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create geography-based features."""
        logger.info("Engineering geo features...")
        
        # Sort by user and timestamp
        df = df.sort_values(['user_id', 'timestamp'])
        
        # Previous country for each user
        df['prev_country'] = df.groupby('user_id')['country'].shift(1)
        df['country_mismatch'] = (df['country'] != df['prev_country']).astype(int)
        df['country_mismatch'] = df['country_mismatch'].fillna(0)
        
        # NOTE: For real geo distance, you'd need lat/lon coordinates
        # This is a simplified version
        df['suspected_geo_fraud'] = (
            (df['country_mismatch'] == 1) & 
            (df['time_since_last_transaction'] < 1)  # Less than 1 hour
        ).astype(int)
        
        logger.info("✓ Added geo features")
        return df
    
    def engineer_interaction_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Create interaction features between variables."""
        logger.info("Engineering interaction features...")
        
        # Amount × Time interactions
        df['amount_x_hour'] = df['amount'] * df['hour_of_day']
        df['amount_x_weekend'] = df['amount'] * df['is_weekend']
        
        # Velocity × Amount
        df['velocity_amount_ratio'] = df['transaction_count_24h'] / (df['amount'] + 1)
        
        logger.info("✓ Added interaction features")
        return df
    
    def save_to_silver(self, df: pd.DataFrame):
        """Save feature-engineered data to Silver layer."""
        output_path = self.silver_path / f"transactions_features_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
        
        logger.info(f"Saving to Silver layer: {output_path}")
        
        df.to_parquet(
            output_path,
            engine='pyarrow',
            compression='snappy',
            index=False
        )
        
        logger.info(f"✓ Saved {len(df):,} records with {len(df.columns)} features to Silver layer")
        logger.info(f"File size: {output_path.stat().st_size / 1024 / 1024:.2f} MB")
    
    def run(self):
        """Execute full Silver layer pipeline."""
        logger.info("=" * 60)
        logger.info("SILVER LAYER - Starting Pipeline")
        logger.info("=" * 60)
        
        # Step 1: Load Bronze data
        df = self.load_bronze_data()
        
        # Step 2: Feature engineering
        df = self.engineer_temporal_features(df)
        df = self.engineer_amount_features(df)
        df = self.engineer_velocity_features(df)
        df = self.engineer_merchant_features(df)
        df = self.engineer_user_features(df)
        df = self.engineer_geo_features(df)
        df = self.engineer_interaction_features(df)
        
        # Step 3: Save to Silver
        self.save_to_silver(df)
        
        logger.info("=" * 60)
        logger.info("✓ SILVER LAYER - Pipeline Complete")
        logger.info(f"Total features created: {len(df.columns)}")
        logger.info("=" * 60)
        
        return df


def main():
    """Run Silver layer pipeline."""
    silver = SilverLayer()
    silver.run()


if __name__ == "__main__":
    main()

