"""
Kinesis Data Producer
Replays PaySim/Kaggle dataset as events into Kinesis Data Streams.
Supports both batch and streaming modes.
"""

import boto3
import pandas as pd
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
import logging
from schemas import TransactionEvent
from dataset_loader import load_dataset

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class KinesisProducer:
    """
    Producer for sending transaction events to Kinesis Data Streams.
    """
    
    def __init__(
        self,
        stream_name: str,
        region: str = "us-east-1",
        profile: Optional[str] = None
    ):
        """
        Initialize Kinesis producer.
        
        Args:
            stream_name: Name of the Kinesis stream
            region: AWS region
            profile: AWS profile name (optional, for local dev)
        """
        session = boto3.Session(
            profile_name=profile,
            region_name=region
        )
        self.kinesis = session.client('kinesis')
        self.stream_name = stream_name
        self.records_sent = 0
        self.bytes_sent = 0
        self.errors = 0
        
        # Verify stream exists
        try:
            response = self.kinesis.describe_stream(StreamName=stream_name)
            logger.info(f"Connected to Kinesis stream: {stream_name}")
            logger.info(f"Stream status: {response['StreamDescription']['StreamStatus']}")
        except Exception as e:
            logger.error(f"Failed to connect to stream {stream_name}: {e}")
            raise
    
    def send_event(
        self,
        event: TransactionEvent,
        partition_key: Optional[str] = None
    ) -> bool:
        """
        Send a single event to Kinesis.
        
        Args:
            event: Transaction event
            partition_key: Partition key (defaults to user_id for even distribution)
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Use user_id as partition key for consistent routing
            pk = partition_key or event.user_id
            
            # Serialize event
            data = event.json()
            
            # Send to Kinesis
            response = self.kinesis.put_record(
                StreamName=self.stream_name,
                Data=data,
                PartitionKey=pk
            )
            
            self.records_sent += 1
            self.bytes_sent += len(data)
            
            logger.debug(
                f"Sent event {event.transaction_id} to shard {response['ShardId']}"
            )
            
            return True
        
        except Exception as e:
            self.errors += 1
            logger.error(f"Failed to send event {event.transaction_id}: {e}")
            return False
    
    def send_batch(self, events: list[TransactionEvent]) -> dict:
        """
        Send batch of events using PutRecords (up to 500 records).
        More efficient than sending one-by-one.
        
        Returns:
            Dict with success/fail counts
        """
        # Kinesis PutRecords limit is 500 records
        MAX_BATCH_SIZE = 500
        
        results = {
            'success': 0,
            'failed': 0,
            'failed_records': []
        }
        
        # Process in chunks
        for i in range(0, len(events), MAX_BATCH_SIZE):
            batch = events[i:i+MAX_BATCH_SIZE]
            
            # Prepare records
            records = [
                {
                    'Data': event.json(),
                    'PartitionKey': event.user_id
                }
                for event in batch
            ]
            
            try:
                response = self.kinesis.put_records(
                    Records=records,
                    StreamName=self.stream_name
                )
                
                # Check for partial failures
                failed_count = response['FailedRecordCount']
                success_count = len(records) - failed_count
                
                results['success'] += success_count
                results['failed'] += failed_count
                
                self.records_sent += success_count
                self.errors += failed_count
                
                # Log failed records
                if failed_count > 0:
                    for idx, record in enumerate(response['Records']):
                        if 'ErrorCode' in record:
                            results['failed_records'].append({
                                'index': i + idx,
                                'error': record.get('ErrorMessage', 'Unknown')
                            })
                
                logger.info(
                    f"Batch: {success_count} succeeded, {failed_count} failed"
                )
            
            except Exception as e:
                logger.error(f"Batch send error: {e}")
                results['failed'] += len(batch)
                self.errors += len(batch)
        
        return results
    
    def replay_dataset(
        self,
        df: pd.DataFrame,
        rate: float = 100.0,
        duration: Optional[int] = None,
        start_index: int = 0
    ):
        """
        Replay transactions from dataset at specified rate.
        
        Args:
            df: DataFrame with transactions
            rate: Events per second
            duration: Max duration in seconds (None = replay all)
            start_index: Starting row index
        """
        logger.info("=" * 60)
        logger.info(f"REPLAYING DATASET: {len(df):,} transactions")
        logger.info(f"Rate: {rate} events/sec")
        logger.info(f"Duration: {duration or 'unlimited'} seconds")
        logger.info("=" * 60)
        
        start_time = time.time()
        interval = 1.0 / rate  # Time between events
        
        try:
            for idx, row in df.iterrows():
                if idx < start_index:
                    continue
                
                # Check duration limit
                if duration and (time.time() - start_time) >= duration:
                    logger.info("Duration limit reached")
                    break
                
                # Create event
                event = self._row_to_event(row)
                
                # Send to Kinesis
                self.send_event(event)
                
                # Progress logging
                if self.records_sent % 100 == 0:
                    elapsed = time.time() - start_time
                    actual_rate = self.records_sent / elapsed if elapsed > 0 else 0
                    logger.info(
                        f"Progress: {self.records_sent:,} sent | "
                        f"Rate: {actual_rate:.1f} evt/s | "
                        f"Errors: {self.errors}"
                    )
                
                # Rate limiting
                time.sleep(interval)
        
        except KeyboardInterrupt:
            logger.info("\nStopped by user")
        
        finally:
            self._print_summary(start_time)
    
    def _row_to_event(self, row: pd.Series) -> TransactionEvent:
        """Convert DataFrame row to TransactionEvent."""
        # Map dataset columns to event schema
        # Adjust field names based on your dataset (PaySim vs Kaggle)
        
        return TransactionEvent(
            transaction_id=str(row.get('transaction_id', f"txn_{int(time.time() * 1000)}")),
            timestamp=pd.to_datetime(row.get('timestamp', datetime.now())),
            amount=Decimal(str(row['amount'])),
            user_id=str(row.get('user_id', row.get('nameOrig', 'unknown'))),
            card_id=str(row.get('card_id', row.get('nameDest', None))),
            merchant_id=str(row.get('merchant_id', f"merchant_{hash(row.get('nameDest', 'default')) % 10000}")),
            merchant_category=str(row.get('merchant_category', row.get('type', 'other'))),
            country=str(row.get('country', 'US')),
            city=str(row.get('city', None)) if pd.notna(row.get('city')) else None,
            is_fraud=int(row.get('is_fraud', row.get('isFraud', 0)))
        )
    
    def _print_summary(self, start_time: float):
        """Print execution summary."""
        elapsed = time.time() - start_time
        
        logger.info("=" * 60)
        logger.info("REPLAY SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Records sent: {self.records_sent:,}")
        logger.info(f"Bytes sent: {self.bytes_sent:,} ({self.bytes_sent / 1024 / 1024:.2f} MB)")
        logger.info(f"Errors: {self.errors}")
        logger.info(f"Duration: {elapsed:.1f}s")
        logger.info(f"Avg rate: {self.records_sent / elapsed:.1f} events/sec")
        logger.info("=" * 60)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Kinesis Data Producer for Fraud Detection")
    
    parser.add_argument(
        '--stream',
        required=True,
        help='Kinesis stream name (e.g., fraud-transactions-dev)'
    )
    
    parser.add_argument(
        '--dataset',
        default='data/raw/transactions.csv',
        help='Path to transaction dataset CSV'
    )
    
    parser.add_argument(
        '--rate',
        type=float,
        default=100.0,
        help='Events per second (default: 100)'
    )
    
    parser.add_argument(
        '--duration',
        type=int,
        default=None,
        help='Max duration in seconds (default: replay all)'
    )
    
    parser.add_argument(
        '--region',
        default='us-east-1',
        help='AWS region'
    )
    
    parser.add_argument(
        '--profile',
        default=None,
        help='AWS profile name (for local dev)'
    )
    
    parser.add_argument(
        '--start-index',
        type=int,
        default=0,
        help='Starting row index in dataset'
    )
    
    args = parser.parse_args()
    
    # Load dataset
    logger.info(f"Loading dataset from {args.dataset}...")
    df = load_dataset(args.dataset)
    logger.info(f"Loaded {len(df):,} transactions")
    
    # Initialize producer
    producer = KinesisProducer(
        stream_name=args.stream,
        region=args.region,
        profile=args.profile
    )
    
    # Replay
    producer.replay_dataset(
        df=df,
        rate=args.rate,
        duration=args.duration,
        start_index=args.start_index
    )


if __name__ == "__main__":
    main()
