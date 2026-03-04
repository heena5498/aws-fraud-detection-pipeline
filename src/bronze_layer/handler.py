"""
Bronze Layer Lambda Handler
Kinesis → DynamoDB (dedupe) → S3 (Parquet)

Responsibilities:
1. Consume events from Kinesis
2. Validate schema (Pydantic)
3. Deduplicate using DynamoDB idempotency table
4. Write validated events to S3 as Parquet (partitioned by date/hour)
5. Emit CloudWatch metrics
"""

import json
import base64
import boto3
from datetime import datetime
from decimal import Decimal
import os
import logging
from typing import List, Dict, Any
import traceback
import sys

# Add parent directory to path for local development
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bronze_layer.validator import validate_event, sanitize_for_parquet
from bronze_layer.deduplicator import Deduplicator
from bronze_layer.s3_writer import S3ParquetWriter
from common.logger import get_logger
from common.metrics import emit_counter, emit_timer, Timer
from common.config import get_config

# Initialize configuration and components
config = get_config()
logger = get_logger('bronze-layer')
deduplicator = Deduplicator(config.dedupe_table, config.aws_region)
s3_writer = S3ParquetWriter(config.bronze_bucket, 'transactions', config.aws_region)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for Kinesis stream processing.
    
    Event structure:
    {
        "Records": [
            {
                "kinesis": {
                    "data": "<base64-encoded-json>",
                    "partitionKey": "user_123",
                    "sequenceNumber": "...",
                    "approximateArrivalTimestamp": 1234567890
                },
                "eventID": "...",
                "eventName": "aws:kinesis:record"
            }
        ]
    }
    """
    logger.info(f"Processing batch of {len(event['Records'])} Kinesis records")
    
    stats = {
        'records_received': len(event['Records']),
        'records_validated': 0,
        'records_deduplicated': 0,
        'records_written': 0,
        'errors': 0,
        'duplicates': 0
    }
    
    validated_events = []
    
    # Process each Kinesis record
    for record in event['Records']:
        try:
            # Decode Kinesis data
            data = base64.b64decode(record['kinesis']['data']).decode('utf-8')
            event_data = json.loads(data)
            
            # Add Kinesis metadata
            event_data['kinesis_sequence_number'] = record['kinesis']['sequenceNumber']
            event_data['kinesis_arrival_timestamp'] = record['kinesis'].get(
                'approximateArrivalTimestamp', 
                datetime.now().timestamp()
            )
            
            # Validate event
            validated_event = validate_event(event_data)
            if not validated_event:
                stats['errors'] += 1
                continue
            
            stats['records_validated'] += 1
            
            # Check for duplicates
            is_duplicate = deduplicator.is_duplicate(
                transaction_id=validated_event['transaction_id'],
                event_id=validated_event.get('event_id')
            )
            
            if is_duplicate:
                logger.debug(f"Duplicate transaction: {validated_event['transaction_id']}")
                stats['duplicates'] += 1
                continue
            
            # Mark as processed in dedupe table
            deduplicator.mark_processed(
                transaction_id=validated_event['transaction_id'],
                event_id=validated_event.get('event_id'),
                ttl_hours=24  # Keep in table for 24 hours
            )
            
            stats['records_deduplicated'] += 1
            
            # Add ingestion metadata
            validated_event['ingestion_timestamp'] = datetime.now().isoformat()
            validated_event['bronze_layer_version'] = '1.0'
            
            validated_events.append(validated_event)
        
        except Exception as e:
            logger.error(
                f"Error processing record {record.get('eventID', 'unknown')}: {e}",
                extra={
                    'error_type': type(e).__name__,
                    'traceback': traceback.format_exc()
                }
            )
            stats['errors'] += 1
    
    # Write validated events to S3 as Parquet
    if validated_events:
        try:
            write_result = s3_writer.write_batch(validated_events)
            stats['records_written'] = write_result['records_written']
            
            logger.info(
                f"Successfully wrote {stats['records_written']} records to S3",
                extra={
                    's3_path': write_result['s3_path'],
                    'partition': write_result['partition'],
                    'file_size_mb': write_result['file_size_mb']
                }
            )
        
        except Exception as e:
            logger.error(f"Failed to write to S3: {e}", exc_info=True)
            stats['errors'] += len(validated_events)
    
    # Emit CloudWatch metrics
    emit_metric('RecordsReceived', stats['records_received'], 'Count')
    emit_metric('RecordsValidated', stats['records_validated'], 'Count')
    emit_metric('RecordsWritten', stats['records_written'], 'Count')
    emit_metric('RecordsDuplicated', stats['duplicates'], 'Count')
    emit_metric('RecordsErrors', stats['errors'], 'Count')
    
    # Log summary
    logger.info(
        "Batch processing complete",
        extra={
            'stats': stats,
            'success_rate': (
                stats['records_written'] / stats['records_received']
                if stats['records_received'] > 0 else 0
            )
        }
    )
    
    # Return stats for monitoring
    return {
        'statusCode': 200,
        'body': json.dumps(stats),
        'stats': stats
    }


# For local testing
if __name__ == "__main__":
    # Sample event
    sample_event = {
        "Records": [
            {
                "kinesis": {
                    "data": base64.b64encode(json.dumps({
                        "transaction_id": "txn_001",
                        "timestamp": datetime.now().isoformat(),
                        "amount": 99.99,
                        "user_id": "user_123",
                        "merchant_id": "merchant_456",
                        "country": "US",
                        "is_fraud": 0
                    }).encode()).decode(),
                    "partitionKey": "user_123",
                    "sequenceNumber": "123456"
                },
                "eventID": "event_001"
            }
        ]
    }
    
    result = lambda_handler(sample_event, None)
    print(json.dumps(result, indent=2))
