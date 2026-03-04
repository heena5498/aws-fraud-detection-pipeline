"""
Bronze Layer - Data Ingestion & Validation
==========================================
Responsibilities:
1. Ingest raw transaction data
2. Validate schema and data quality
3. Deduplicate records
4. Store in parquet format for efficiency
"""

import pandas as pd
import pyarrow.parquet as pq
import yaml
from pathlib import Path
from typing import Optional
from loguru import logger
import pandera as pa
from pandera import Column, Check, DataFrameSchema
from datetime import datetime


class BronzeLayer:
    """Handle raw data ingestion, validation, and storage."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize Bronze Layer with configuration."""
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.raw_path = Path(self.config['data']['raw_data_path'])
        self.bronze_path = Path(self.config['data']['bronze_path'])
        self.bronze_path.mkdir(parents=True, exist_ok=True)
        
        # Define expected schema
        self.schema = self._create_schema()
        
        logger.info(f"Bronze Layer initialized. Output: {self.bronze_path}")
    
    def _create_schema(self) -> DataFrameSchema:
        """Define expected schema for transaction data."""
        return DataFrameSchema({
            "transaction_id": Column(str, unique=True),
            "timestamp": Column(pa.DateTime),
            "amount": Column(float, Check.greater_than(0)),
            "merchant_id": Column(str),
            "user_id": Column(str),
            "merchant_category": Column(str, nullable=True),
            "country": Column(str, nullable=True),
            "is_fraud": Column(int, Check.isin([0, 1])),
        }, strict=False)  # Allow additional columns
    
    def load_raw_data(self, file_path: Optional[str] = None) -> pd.DataFrame:
        """Load raw transaction data from CSV."""
        file_path = file_path or self.raw_path
        logger.info(f"Loading raw data from {file_path}")
        
        # Read in chunks for large files
        chunk_size = self.config['etl']['chunk_size']
        df = pd.read_csv(file_path)
        
        logger.info(f"Loaded {len(df):,} raw records")
        return df
    
    def validate_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Validate data against schema."""
        logger.info("Validating data schema...")
        
        try:
            # Validate with Pandera (this will raise if validation fails)
            validated_df = self.schema.validate(df, lazy=True)
            logger.info(f"✓ Schema validation passed for {len(validated_df):,} records")
            return validated_df
        
        except pa.errors.SchemaErrors as e:
            logger.warning(f"Schema validation found {len(e.failure_cases)} issues")
            logger.debug(e.failure_cases)
            
            # Continue with valid records only
            # In production, you might want to log failures to a separate table
            valid_mask = ~df.index.isin(e.failure_cases['index'])
            validated_df = df[valid_mask]
            logger.info(f"Continuing with {len(validated_df):,} valid records")
            return validated_df
    
    def deduplicate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove duplicate records."""
        logger.info("Deduplicating records...")
        
        initial_count = len(df)
        dedupe_cols = self.config['etl']['dedupe_columns']
        
        df_deduped = df.drop_duplicates(subset=dedupe_cols, keep='first')
        
        duplicates_removed = initial_count - len(df_deduped)
        logger.info(f"Removed {duplicates_removed:,} duplicates. Remaining: {len(df_deduped):,}")
        
        return df_deduped
    
    def add_metadata(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add ingestion metadata."""
        df['ingestion_timestamp'] = datetime.now()
        df['bronze_layer_version'] = '1.0'
        return df
    
    def save_to_bronze(self, df: pd.DataFrame, partition_by: Optional[str] = None):
        """Save validated data to Bronze layer in Parquet format."""
        output_path = self.bronze_path / f"transactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}.parquet"
        
        logger.info(f"Saving to Bronze layer: {output_path}")
        
        # Save as Parquet for efficient storage and querying
        df.to_parquet(
            output_path,
            engine='pyarrow',
            compression='snappy',
            index=False
        )
        
        logger.info(f"✓ Saved {len(df):,} records to Bronze layer")
        logger.info(f"File size: {output_path.stat().st_size / 1024 / 1024:.2f} MB")
    
    def run(self, file_path: Optional[str] = None):
        """Execute full Bronze layer pipeline."""
        logger.info("=" * 60)
        logger.info("BRONZE LAYER - Starting Pipeline")
        logger.info("=" * 60)
        
        # Step 1: Load raw data
        df = self.load_raw_data(file_path)
        
        # Step 2: Validate schema
        df = self.validate_data(df)
        
        # Step 3: Deduplicate
        df = self.deduplicate(df)
        
        # Step 4: Add metadata
        df = self.add_metadata(df)
        
        # Step 5: Save to Bronze
        self.save_to_bronze(df)
        
        logger.info("=" * 60)
        logger.info("✓ BRONZE LAYER - Pipeline Complete")
        logger.info("=" * 60)
        
        return df


def main():
    """Run Bronze layer pipeline."""
    bronze = BronzeLayer()
    bronze.run()


if __name__ == "__main__":
    main()
