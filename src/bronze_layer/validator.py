"""
Event validator using Pydantic schemas.
Handles schema validation, type conversion, and error logging.
"""

import json
from typing import Optional, Dict, Any
from decimal import Decimal
from datetime import datetime
import logging

# Import schema from data_producer
import sys
sys.path.append('/opt')  # Lambda layer

try:
    from data_producer.schemas import TransactionEvent
except ImportError:
    from schemas import TransactionEvent

logger = logging.getLogger(__name__)


def validate_event(event_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Validate transaction event against Pydantic schema.
    
    Args:
        event_data: Raw event dictionary
    
    Returns:
        Validated event dict, or None if validation fails
    """
    try:
        # Parse with Pydantic
        event = TransactionEvent(**event_data)
        
        # Convert to dict (handles Decimal, datetime serialization)
        validated = json.loads(event.json())
        
        logger.debug(
            f"Validated transaction {event.transaction_id}",
            extra={'transaction_id': event.transaction_id}
        )
        
        return validated
    
    except Exception as e:
        logger.error(
            f"Schema validation failed: {e}",
            extra={
                'error_type': type(e).__name__,
                'event_data': event_data,
                'errors': str(e)
            }
        )
        return None


def validate_schema_version(event_data: Dict[str, Any]) -> bool:
    """
    Check if schema version is supported.
    Allows for graceful schema evolution.
    """
    supported_versions = ['1.0']
    
    version = event_data.get('schema_version', '1.0')
    
    if version not in supported_versions:
        logger.warning(
            f"Unsupported schema version: {version}",
            extra={'supported_versions': supported_versions}
        )
        return False
    
    return True


def sanitize_for_parquet(event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize event data for Parquet compatibility.
    
    Parquet considerations:
    - Convert Decimal to float
    - Convert datetime to string (ISO format)
    - Handle nested structures
    - Remove null/None for required fields
    """
    sanitized = {}
    
    for key, value in event_data.items():
        if value is None:
            sanitized[key] = value
        elif isinstance(value, Decimal):
            sanitized[key] = float(value)
        elif isinstance(value, datetime):
            sanitized[key] = value.isoformat()
        elif isinstance(value, dict):
            sanitized[key] = json.dumps(value)  # Flatten nested objects
        else:
            sanitized[key] = value
    
    return sanitized


if __name__ == "__main__":
    # Test validation
    test_event = {
        "transaction_id": "txn_001",
        "timestamp": "2026-03-03T14:30:00",
        "amount": 99.99,
        "user_id": "user_123",
        "merchant_id": "merchant_456",
        "country": "US",
        "is_fraud": 0
    }
    
    validated = validate_event(test_event)
    print(json.dumps(validated, indent=2))
    
    # Test invalid event
    invalid_event = {
        "transaction_id": "",  # Empty - should fail
        "amount": -10,  # Negative - should fail
        "country": "INVALID"  # Too long - should fail
    }
    
    result = validate_event(invalid_event)
    print(f"\nInvalid event validation result: {result}")
