"""
Gold Layer - Feature Store Creation
====================================
Responsibilities:
1. Load data from Silver layer
2. Select and prepare final features for ML
3. Create train/test splits
4. Store model-ready datasets
"""

import pandas as pd
import numpy as np
import yaml
from pathlib import Path
from typing import List, Tuple
from loguru import logger
from datetime import datetime
from sklearn.model_selection import train_test_split


class GoldLayer:
    """Prepare model-ready feature store from Silver data."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize Gold Layer with configuration."""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.silver_path = Path(self.config['data']['silver_path'])
        self.gold_path = Path(self.config['data']['gold_path'])
        self.gold_path.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Gold Layer initialized. Output: {self.gold_path}")
    
    def load_silver_data(self) -> pd.DataFrame:
        """Load latest data from Silver layer."""
        logger.info("Loading data from Silver layer...")
        
        # Get most recent silver file
        silver_files = sorted(self.silver_path.glob("*.parquet"))
        if not silver_files:
            raise FileNotFoundError(f"No parquet files found in {self.silver_path}")
        
        latest_file = silver_files[-1]
        logger.info(f"Loading: {latest_file}")
        
        df = pd.read_parquet(latest_file)
        logger.info(f"Loaded {len(df):,} records from Silver layer")
        
        return df
    
    def select_features(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, List[str]]:
        """Select final features for modeling."""
        logger.info("Selecting features for modeling...")
        
        # Exclude non-feature columns
        exclude_cols = [
            'transaction_id',
            'timestamp',
            'user_id',
            'merchant_id',
            'ingestion_timestamp',
            'bronze_layer_version',
            'prev_country',
            'is_fraud'  # This is the target
        ]
        
        # Get all feature columns
        feature_cols = [col for col in df.columns if col not in exclude_cols]
        
        logger.info(f"Selected {len(feature_cols)} features for modeling")
        logger.debug(f"Features: {feature_cols}")
        
        return df, feature_cols
    
    def handle_missing_values(self, df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
        """Handle missing values in features."""
        logger.info("Handling missing values...")
        
        missing_counts = df[feature_cols].isnull().sum()
        if missing_counts.sum() > 0:
            logger.info(f"Found {missing_counts.sum()} missing values across {(missing_counts > 0).sum()} features")
            
            # Fill numeric features with median
            numeric_cols = df[feature_cols].select_dtypes(include=[np.number]).columns
            df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].median())
            
            # Fill categorical features with mode or 'unknown'
            categorical_cols = df[feature_cols].select_dtypes(include=['object', 'category']).columns
            for col in categorical_cols:
                df[col] = df[col].fillna('unknown')
            
            logger.info("✓ Missing values handled")
        else:
            logger.info("✓ No missing values found")
        
        return df
    
    def create_train_test_split(
        self, 
        df: pd.DataFrame, 
        feature_cols: List[str]
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Create train/test split with proper time-based separation."""
        logger.info("Creating train/test split...")
        
        # Option 1: Time-based split (recommended for time series)
        # Use first 80% for training, last 20% for testing
        if 'timestamp' in df.columns:
            df = df.sort_values('timestamp')
            split_idx = int(len(df) * 0.8)
            
            train_df = df.iloc[:split_idx]
            test_df = df.iloc[split_idx:]
            
            logger.info(f"Time-based split: Train={len(train_df):,}, Test={len(test_df):,}")
        
        # Option 2: Random split (alternative)
        else:
            train_df, test_df = train_test_split(
                df,
                test_size=self.config['ml']['test_size'],
                random_state=self.config['ml']['random_state'],
                stratify=df['is_fraud']  # Maintain class balance
            )
            logger.info(f"Random split: Train={len(train_df):,}, Test={len(test_df):,}")
        
        # Separate features and target
        X_train = train_df[feature_cols]
        y_train = train_df['is_fraud']
        X_test = test_df[feature_cols]
        y_test = test_df['is_fraud']
        
        # Log class distribution
        logger.info(f"Train fraud rate: {y_train.mean():.2%}")
        logger.info(f"Test fraud rate: {y_test.mean():.2%}")
        
        return X_train, X_test, y_train, y_test
    
    def create_feature_store(self, df: pd.DataFrame, feature_cols: List[str]):
        """Create feature store with metadata."""
        logger.info("Creating feature store...")
        
        # Feature store includes all data with selected features
        feature_store = df[['transaction_id', 'user_id', 'merchant_id', 'timestamp'] + feature_cols + ['is_fraud']].copy()
        
        # Add metadata
        feature_store['feature_store_version'] = '1.0'
        feature_store['created_at'] = datetime.now()
        
        return feature_store
    
    def save_to_gold(
        self,
        feature_store: pd.DataFrame,
        X_train: pd.DataFrame,
        X_test: pd.DataFrame,
        y_train: pd.Series,
        y_test: pd.Series,
        feature_cols: List[str]
    ):
        """Save all Gold layer outputs."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Save feature store
        feature_store_path = self.gold_path / f"feature_store_{timestamp}.parquet"
        feature_store.to_parquet(feature_store_path, index=False)
        logger.info(f"✓ Saved feature store: {feature_store_path}")
        
        # Save train/test splits
        train_path = self.gold_path / f"train_{timestamp}.parquet"
        test_path = self.gold_path / f"test_{timestamp}.parquet"
        
        train_df = X_train.copy()
        train_df['is_fraud'] = y_train.values
        test_df = X_test.copy()
        test_df['is_fraud'] = y_test.values
        
        train_df.to_parquet(train_path, index=False)
        test_df.to_parquet(test_path, index=False)
        
        logger.info(f"✓ Saved train set: {train_path}")
        logger.info(f"✓ Saved test set: {test_path}")
        
        # Save feature list
        feature_list_path = self.gold_path / "feature_columns.txt"
        with open(feature_list_path, 'w') as f:
            f.write('\n'.join(feature_cols))
        logger.info(f"✓ Saved feature list: {feature_list_path}")
        
        # Save metadata
        metadata = {
            'created_at': timestamp,
            'num_features': len(feature_cols),
            'train_size': len(X_train),
            'test_size': len(X_test),
            'fraud_rate_train': float(y_train.mean()),
            'fraud_rate_test': float(y_test.mean()),
        }
        
        metadata_path = self.gold_path / f"metadata_{timestamp}.yaml"
        with open(metadata_path, 'w') as f:
            yaml.dump(metadata, f)
        logger.info(f"✓ Saved metadata: {metadata_path}")
    
    def run(self):
        """Execute full Gold layer pipeline."""
        logger.info("=" * 60)
        logger.info("GOLD LAYER - Starting Pipeline")
        logger.info("=" * 60)
        
        # Step 1: Load Silver data
        df = self.load_silver_data()
        
        # Step 2: Select features
        df, feature_cols = self.select_features(df)
        
        # Step 3: Handle missing values
        df = self.handle_missing_values(df, feature_cols)
        
        # Step 4: Create train/test split
        X_train, X_test, y_train, y_test = self.create_train_test_split(df, feature_cols)
        
        # Step 5: Create feature store
        feature_store = self.create_feature_store(df, feature_cols)
        
        # Step 6: Save to Gold
        self.save_to_gold(feature_store, X_train, X_test, y_train, y_test, feature_cols)
        
        logger.info("=" * 60)
        logger.info("✓ GOLD LAYER - Pipeline Complete")
        logger.info(f"Features: {len(feature_cols)}")
        logger.info(f"Train samples: {len(X_train):,}")
        logger.info(f"Test samples: {len(X_test):,}")
        logger.info("=" * 60)
        
        return feature_store, X_train, X_test, y_train, y_test


def main():
    """Run Gold layer pipeline."""
    gold = GoldLayer()
    gold.run()


if __name__ == "__main__":
    main()
