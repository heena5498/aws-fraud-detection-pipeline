"""
AWS SDK client factory with proper configuration.
Handles retries, timeouts, and credential management.
"""

import boto3
from botocore.config import Config as BotoConfig
from typing import Optional
import logging
from config import get_config

logger = logging.getLogger(__name__)


class AWSClients:
    """
    Factory for AWS service clients with best practices:
    - Automatic retry with exponential backoff
    - Connection pooling
    - Region configuration
    - Credential management
    """
    
    def __init__(self, region: Optional[str] = None):
        """
        Initialize AWS clients factory.
        
        Args:
            region: AWS region (defaults to config)
        """
        config = get_config()
        self.region = region or config.aws_region
        
        # Boto3 client configuration
        self.boto_config = BotoConfig(
            region_name=self.region,
            retries={
                'max_attempts': 3,
                'mode': 'adaptive'  # Adaptive retry mode (recommended)
            },
            max_pool_connections=50,  # Connection pooling
            connect_timeout=5,
            read_timeout=60
        )
        
        # Client cache (lazy initialization)
        self._clients = {}
        
        logger.debug(f"Initialized AWS clients factory: region={self.region}")
    
    def get_client(self, service_name: str):
        """
        Get or create AWS service client.
        
        Args:
            service_name: AWS service (s3, dynamodb, kinesis, etc.)
        
        Returns:
            Boto3 client instance
        """
        if service_name not in self._clients:
            self._clients[service_name] = boto3.client(
                service_name,
                config=self.boto_config
            )
            logger.debug(f"Created {service_name} client")
        
        return self._clients[service_name]
    
    @property
    def s3(self):
        """Get S3 client."""
        return self.get_client('s3')
    
    @property
    def dynamodb(self):
        """Get DynamoDB client."""
        return self.get_client('dynamodb')
    
    @property
    def kinesis(self):
        """Get Kinesis client."""
        return self.get_client('kinesis')
    
    @property
    def glue(self):
        """Get Glue client."""
        return self.get_client('glue')
    
    @property
    def athena(self):
        """Get Athena client."""
        return self.get_client('athena')
    
    @property
    def secretsmanager(self):
        """Get Secrets Manager client."""
        return self.get_client('secretsmanager')
    
    @property
    def cloudwatch(self):
        """Get CloudWatch client."""
        return self.get_client('cloudwatch')
    
    @property
    def stepfunctions(self):
        """Get Step Functions client."""
        return self.get_client('stepfunctions')
    
    @property
    def eventbridge(self):
        """Get EventBridge client."""
        return self.get_client('events')


# Singleton instance
_aws_clients: Optional[AWSClients] = None


def get_aws_clients() -> AWSClients:
    """Get singleton AWS clients factory."""
    global _aws_clients
    if _aws_clients is None:
        _aws_clients = AWSClients()
    return _aws_clients


# Convenience functions for common clients
def get_s3_client():
    """Get S3 client."""
    return get_aws_clients().s3


def get_dynamodb_client():
    """Get DynamoDB client."""
    return get_aws_clients().dynamodb


def get_kinesis_client():
    """Get Kinesis client."""
    return get_aws_clients().kinesis


# For local testing
if __name__ == "__main__":
    clients = get_aws_clients()
    
    print(f"Region: {clients.region}")
    print(f"S3 client: {clients.s3}")
    print(f"DynamoDB client: {clients.dynamodb}")
