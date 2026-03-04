"""
DynamoDB-based deduplication service.
Ensures exactly-once processing of Kinesis events.

Strategy:
- Use DynamoDB conditional writes (put_item with condition_expression)
- TTL to auto-expire old records (24 hours)
- Composite key: transaction_id + event_id for idempotency
"""

import boto3
from datetime import datetime, timedelta
from typing import Optional
import logging
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class Deduplicator:
    """
    DynamoDB-based deduplication for exactly-once processing.
    """
    
    def __init__(self, table_name: str, region: str = 'us-east-1'):
        """
        Initialize deduplicator.
        
        Args:
            table_name: DynamoDB table name
            region: AWS region
        """
        self.dynamodb = boto3.resource('dynamodb', region_name=region)
        self.table = self.dynamodb.Table(table_name)
        self.table_name = table_name
        
        logger.info(f"Initialized deduplicator with table: {table_name}")
    
    def is_duplicate(
        self,
        transaction_id: str,
        event_id: Optional[str] = None
    ) -> bool:
        """
        Check if transaction has already been processed.
        
        Args:
            transaction_id: Unique transaction ID
            event_id: Optional event ID for additional uniqueness
        
        Returns:
            True if duplicate, False if new
        """
        try:
            # Create composite key
            key = self._make_key(transaction_id, event_id)
            
            # Check if exists
            response = self.table.get_item(
                Key={'idempotency_key': key},
                ConsistentRead=True  # Ensure we get latest state
            )
            
            if 'Item' in response:
                logger.debug(
                    f"Duplicate detected: {transaction_id}",
                    extra={'transaction_id': transaction_id, 'event_id': event_id}
                )
                return True
            
            return False
        
        except ClientError as e:
            logger.error(
                f"Error checking duplicate: {e}",
                extra={'transaction_id': transaction_id}
            )
            # On error, assume not duplicate to avoid data loss
            # Downstream deduplication can catch it
            return False
    
    def mark_processed(
        self,
        transaction_id: str,
        event_id: Optional[str] = None,
        ttl_hours: int = 24,
        metadata: Optional[dict] = None
    ) -> bool:
        """
        Mark transaction as processed in DynamoDB.
        
        Uses conditional write to prevent race conditions.
        
        Args:
            transaction_id: Unique transaction ID
            event_id: Optional event ID
            ttl_hours: Hours until record expires (default 24)
            metadata: Optional metadata to store
        
        Returns:
            True if successfully marked, False if already exists
        """
        try:
            key = self._make_key(transaction_id, event_id)
            ttl = int((datetime.now() + timedelta(hours=ttl_hours)).timestamp())
            
            # Prepare item
            item = {
                'idempotency_key': key,
                'transaction_id': transaction_id,
                'processed_at': datetime.now().isoformat(),
                'ttl': ttl
            }
            
            if event_id:
                item['event_id'] = event_id
            
            if metadata:
                item['metadata'] = metadata
            
            # Conditional write: only if key doesn't exist
            self.table.put_item(
                Item=item,
                ConditionExpression='attribute_not_exists(idempotency_key)'
            )
            
            logger.debug(
                f"Marked as processed: {transaction_id}",
                extra={'transaction_id': transaction_id, 'ttl_hours': ttl_hours}
            )
            
            return True
        
        except ClientError as e:
            if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
                # Already exists - this is a duplicate
                logger.info(
                    f"Transaction already marked as processed: {transaction_id}",
                    extra={'transaction_id': transaction_id}
                )
                return False
            else:
                logger.error(f"Error marking processed: {e}")
                raise
    
    def _make_key(self, transaction_id: str, event_id: Optional[str] = None) -> str:
        """
        Create composite idempotency key.
        
        Format: {transaction_id}#{event_id} or just {transaction_id}
        """
        if event_id:
            return f"{transaction_id}#{event_id}"
        return transaction_id
    
    def cleanup_expired(self) -> int:
        """
        Manually cleanup expired records (if TTL is not enabled).
        Returns number of records deleted.
        
        Note: In production, enable DynamoDB TTL for automatic cleanup.
        """
        # This is expensive and should only be used if TTL is not enabled
        logger.warning("Manual cleanup is inefficient. Enable DynamoDB TTL instead.")
        
        try:
            now = int(datetime.now().timestamp())
            items_deleted = 0
            
            # Scan for expired items (expensive!)
            response = self.table.scan(
                FilterExpression='#ttl < :now',
                ExpressionAttributeNames={'#ttl': 'ttl'},
                ExpressionAttributeValues={':now': now}
            )
            
            # Delete expired items
            with self.table.batch_writer() as batch:
                for item in response.get('Items', []):
                    batch.delete_item(
                        Key={'idempotency_key': item['idempotency_key']}
                    )
                    items_deleted += 1
            
            logger.info(f"Cleaned up {items_deleted} expired records")
            return items_deleted
        
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return 0


# For local testing
if __name__ == "__main__":
    import os
    
    # Point to local DynamoDB or use moto for testing
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
    
    deduplicator = Deduplicator('fraud-dedupe-dev')
    
    # Test duplicate detection
    txn_id = "txn_test_001"
    
    # First check - should be False (new)
    is_dup = deduplicator.is_duplicate(txn_id)
    print(f"First check (expect False): {is_dup}")
    
    # Mark as processed
    success = deduplicator.mark_processed(txn_id)
    print(f"Mark processed (expect True): {success}")
    
    # Second check - should be True (duplicate)
    is_dup = deduplicator.is_duplicate(txn_id)
    print(f"Second check (expect True): is_dup")
    
    # Try to mark again - should fail
    success = deduplicator.mark_processed(txn_id)
    print(f"Mark again (expect False): {success}")
