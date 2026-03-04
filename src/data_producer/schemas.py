"""
Pydantic schemas for transaction events.
Version-aware for schema evolution.
"""

from pydantic import BaseModel, Field, validator, constr
from typing import Optional, Literal
from datetime import datetime
from decimal import Decimal


class TransactionEvent(BaseModel):
    """
    Transaction event schema for Kinesis ingestion.
    
    Version: 1.0
    Changes: Initial schema
    """
    
    # Schema versioning
    schema_version: Literal["1.0"] = "1.0"
    
    # Core transaction fields
    transaction_id: constr(min_length=1, max_length=64) = Field(
        ..., 
        description="Unique transaction identifier",
        example="txn_20260303_abc123"
    )
    
    timestamp: datetime = Field(
        ...,
        description="Transaction timestamp (ISO 8601)"
    )
    
    amount: Decimal = Field(
        ...,
        ge=0.01,
        max_digits=12,
        decimal_places=2,
        description="Transaction amount in USD"
    )
    
    # User identification
    user_id: constr(min_length=1, max_length=64) = Field(
        ...,
        description="User/cardholder ID (will be hashed in Silver layer)"
    )
    
    card_id: Optional[constr(min_length=1, max_length=64)] = Field(
        None,
        description="Card ID (will be hashed in Silver layer)"
    )
    
    # Merchant information
    merchant_id: constr(min_length=1, max_length=64) = Field(
        ...,
        description="Merchant identifier"
    )
    
    merchant_name: Optional[str] = Field(
        None,
        max_length=256,
        description="Merchant business name"
    )
    
    merchant_category: Optional[str] = Field(
        None,
        description="MCC category code",
        example="5411"  # Grocery stores
    )
    
    # Geographic information
    country: str = Field(
        ...,
        min_length=2,
        max_length=2,
        description="ISO 3166-1 alpha-2 country code",
        example="US"
    )
    
    city: Optional[str] = Field(None, max_length=128)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    
    # Device/channel information
    device_id: Optional[str] = Field(None, max_length=128)
    device_type: Optional[Literal["mobile", "web", "pos", "atm", "other"]] = None
    channel: Optional[Literal["online", "in_store", "atm"]] = "online"
    
    # Transaction metadata
    currency: str = Field(default="USD", min_length=3, max_length=3)
    transaction_type: Optional[Literal["purchase", "withdrawal", "transfer", "payment"]] = "purchase"
    
    # Ground truth label (for training data only)
    is_fraud: Optional[int] = Field(
        None,
        ge=0,
        le=1,
        description="Ground truth fraud label (0=legit, 1=fraud). Only in training data."
    )
    
    # Event metadata
    event_id: Optional[str] = Field(
        None,
        description="Unique event ID (for deduplication, auto-generated if missing)"
    )
    
    source_system: Optional[str] = Field(
        default="data-producer",
        description="Source system that generated this event"
    )
    
    class Config:
        json_encoders = {
            Decimal: lambda v: float(v),
            datetime: lambda v: v.isoformat()
        }
    
    @validator('timestamp', pre=True)
    def parse_timestamp(cls, v):
        """Parse timestamp from various formats."""
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            # Try ISO format
            try:
                return datetime.fromisoformat(v.replace('Z', '+00:00'))
            except ValueError:
                # Try other common formats
                from dateutil import parser
                return parser.parse(v)
        raise ValueError(f"Invalid timestamp format: {v}")
    
    @validator('event_id', pre=True, always=True)
    def generate_event_id(cls, v, values):
        """Auto-generate event_id if not provided."""
        if v:
            return v
        # Generate from transaction_id + timestamp for idempotency
        import hashlib
        txn_id = values.get('transaction_id', '')
        ts = values.get('timestamp', datetime.now())
        unique_str = f"{txn_id}_{ts.isoformat()}"
        return hashlib.sha256(unique_str.encode()).hexdigest()[:16]


class TransactionEventBatch(BaseModel):
    """Batch of transaction events for efficient Kinesis writes."""
    events: list[TransactionEvent]
    
    @validator('events')
    def check_not_empty(cls, v):
        if not v:
            raise ValueError("Event batch cannot be empty")
        return v


# Example usage
if __name__ == "__main__":
    # Valid event
    event = TransactionEvent(
        transaction_id="txn_001",
        timestamp=datetime.now(),
        amount=Decimal("99.99"),
        user_id="user_123",
        card_id="card_456",
        merchant_id="merchant_789",
        merchant_category="5411",
        country="US",
        is_fraud=0
    )
    
    print("Valid event:")
    print(event.json(indent=2))
    
    # Invalid event (negative amount)
    try:
        bad_event = TransactionEvent(
            transaction_id="txn_002",
            timestamp=datetime.now(),
            amount=Decimal("-10.00"),  # Invalid!
            user_id="user_123",
            merchant_id="merchant_789",
            country="US"
        )
    except Exception as e:
        print(f"\nValidation error (expected): {e}")
