"""
S3 Parquet Writer for Bronze Layer
Writes validated events to S3 with efficient partitioning.

Partitioning strategy:
- s3://bucket/prefix/year=YYYY/month=MM/day=DD/hour=HH/batch_timestamp.parquet
- Enables efficient Athena queries with partition pruning
- Optimized file sizes (32-128 MB recommended for Parquet)
"""

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from datetime import datetime
from typing import List, Dict, Any
import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class S3ParquetWriter:
    """
    Write transaction events to S3 as Parquet files with partitioning.
    """
    
    def __init__(
        self,
        bucket: str,
        prefix: str = 'transactions',
        region: str = 'us-east-1',
        compression: str = 'snappy'
    ):
        """
        Initialize S3 writer.
        
        Args:
            bucket: S3 bucket name
            prefix: S3 prefix/folder
            region: AWS region
            compression: Parquet compression (snappy, gzip, None)
        """
        self.s3_client = boto3.client('s3', region_name=region)
        self.bucket = bucket
        self.prefix = prefix.rstrip('/')
        self.compression = compression
        
        logger.info(
            f"Initialized S3 writer: s3://{bucket}/{prefix}",
            extra={'bucket': bucket, 'prefix': prefix, 'compression': compression}
        )
    
    def write_batch(
        self,
        events: List[Dict[str, Any]],
        partition_by_time: bool = True
    ) -> Dict[str, Any]:
        """
        Write batch of events to S3 as Parquet.
        
        Args:
            events: List of validated event dictionaries
            partition_by_time: Enable time-based partitioning
        
        Returns:
            Dict with write metadata
        """
        if not events:
            logger.warning("No events to write")
            return {'records_written': 0}
        
        try:
            # Convert to DataFrame
            df = pd.DataFrame(events)
            
            # Ensure timestamp is datetime
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Add partition columns if enabled
            if partition_by_time and 'timestamp' in df.columns:
                df['year'] = df['timestamp'].dt.year
                df['month'] = df['timestamp'].dt.month.astype(str).str.zfill(2)
                df['day'] = df['timestamp'].dt.day.astype(str).str.zfill(2)
                df['hour'] = df['timestamp'].dt.hour.astype(str).str.zfill(2)
                partition_cols = ['year', 'month', 'day', 'hour']
            else:
                partition_cols = []
            
            # Determine S3 path
            batch_ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            
            if partition_cols:
                # Use first event's timestamp for partition
                first_ts = pd.to_datetime(events[0]['timestamp'])
                partition_path = (
                    f"year={first_ts.year}/"
                    f"month={first_ts.month:02d}/"
                    f"day={first_ts.day:02d}/"
                    f"hour={first_ts.hour:02d}"
                )
                s3_key = f"{self.prefix}/{partition_path}/batch_{batch_ts}.parquet"
            else:
                s3_key = f"{self.prefix}/batch_{batch_ts}.parquet"
            
            # Convert to PyArrow Table
            table = pa.Table.from_pandas(df)
            
            # Write to in-memory buffer
            buffer = io.BytesIO()
            pq.write_table(
                table,
                buffer,
                compression=self.compression,
                use_dictionary=True,  # Reduce size for repeated values
                write_statistics=True  # Enable predicate pushdown in Athena
            )
            
            # Upload to S3
            buffer.seek(0)
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=s3_key,
                Body=buffer.getvalue(),
                ContentType='application/vnd.apache.parquet',
                ServerSideEncryption='AES256'  # SSE-S3 encryption
            )
            
            file_size_mb = buffer.tell() / 1024 / 1024
            
            logger.info(
                f"Wrote {len(df)} records to S3",
                extra={
                    's3_uri': f"s3://{self.bucket}/{s3_key}",
                    'records': len(df),
                    'file_size_mb': file_size_mb,
                    'compression': self.compression
                }
            )
            
            return {
                'records_written': len(df),
                's3_path': f"s3://{self.bucket}/{s3_key}",
                's3_key': s3_key,
                'partition': partition_path if partition_cols else None,
                'file_size_mb': round(file_size_mb, 2),
                'compression': self.compression
            }
        
        except Exception as e:
            logger.error(f"Failed to write batch to S3: {e}", exc_info=True)
            raise
    
    def write_dataframe(
        self,
        df: pd.DataFrame,
        partition_cols: List[str] = None
    ) -> Dict[str, Any]:
        """
        Write DataFrame directly to S3 (for large batches).
        
        Args:
            df: Pandas DataFrame
            partition_cols: Columns to partition by (e.g., ['year', 'month', 'day'])
        """
        events = df.to_dict('records')
        return self.write_batch(events, partition_by_time=bool(partition_cols))


# For local testing
if __name__ == "__main__":
    import os
    
    # Test with local S3 (localstack) or real AWS
    writer = S3ParquetWriter(
        bucket='fraud-bronze-dev',
        prefix='transactions',
        region='us-east-1'
    )
    
    # Sample events
    events = [
        {
            'transaction_id': f'txn_{i:04d}',
            'timestamp': datetime.now().isoformat(),
            'amount': float(99.99 + i),
            'user_id': f'user_{i % 100}',
            'merchant_id': f'merchant_{i % 50}',
            'country': 'US',
            'is_fraud': 0
        }
        for i in range(100)
    ]
    
    result = writer.write_batch(events)
    print(f"Write result: {result}")
