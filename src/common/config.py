"""
Common configuration management.
Loads from environment variables with type safety and validation.
"""

import os
from typing import Optional
from dataclasses import dataclass


@dataclass
class Config:
    """Application configuration."""
    
    # Environment
    environment: str = os.getenv('ENVIRONMENT', 'dev')
    aws_region: str = os.getenv('AWS_REGION', 'us-east-1')
    
    # S3 Data Lake
    bronze_bucket: str = os.getenv('BRONZE_BUCKET', 'fraud-bronze-dev')
    silver_bucket: str = os.getenv('SILVER_BUCKET', 'fraud-silver-dev')
    gold_bucket: str = os.getenv('GOLD_BUCKET', 'fraud-gold-dev')
    models_bucket: str = os.getenv('MODELS_BUCKET', 'fraud-models-dev')
    
    # DynamoDB
    dedupe_table: str = os.getenv('DEDUPE_TABLE_NAME', 'fraud-dedupe-dev')
    alerts_table: str = os.getenv('ALERTS_TABLE_NAME', 'fraud-alerts-dev')
    feedback_table: str = os.getenv('FEEDBACK_TABLE_NAME', 'fraud-feedback-dev')
    monitoring_table: str = os.getenv('MONITORING_TABLE_NAME', 'fraud-monitoring-dev')
    
    # Kinesis
    kinesis_stream: str = os.getenv('KINESIS_STREAM_NAME', 'fraud-transactions-dev')
    
    # Glue
    glue_database: str = os.getenv('GLUE_DATABASE', 'fraud_detection_dev')
    silver_job_name: str = os.getenv('SILVER_JOB_NAME', 'fraud-silver-job-dev')
    gold_job_name: str = os.getenv('GOLD_JOB_NAME', 'fraud-gold-job-dev')
    
    # API
    api_url: str = os.getenv('API_URL', 'http://localhost:8000')
    
    # ML
    mlflow_tracking_uri: str = os.getenv('MLFLOW_TRACKING_URI', 'http://localhost:5000')
    model_name: str = os.getenv('MODEL_NAME', 'fraud-detection-model')
    
    # Feature thresholds
    psi_threshold: float = float(os.getenv('PSI_THRESHOLD', '0.25'))
    fraud_probability_threshold: float = float(os.getenv('FRAUD_THRESHOLD', '0.7'))
    
    # Monitoring
    cloudwatch_namespace: str = os.getenv('CLOUDWATCH_NAMESPACE', 'FraudDetection')
    log_level: str = os.getenv('LOG_LEVEL', 'INFO')
    
    # PII security
    pii_salt_secret_name: str = os.getenv('PII_SALT_SECRET', 'fraud-pii-salt')
    
    def __post_init__(self):
        """Validate configuration."""
        if not self.bronze_bucket:
            raise ValueError("BRONZE_BUCKET environment variable required")
        
        if self.psi_threshold < 0 or self.psi_threshold > 1:
            raise ValueError(f"Invalid PSI_THRESHOLD: {self.psi_threshold}")
        
        if self.fraud_probability_threshold < 0 or self.fraud_probability_threshold > 1:
            raise ValueError(f"Invalid FRAUD_THRESHOLD: {self.fraud_probability_threshold}")
    
    def is_production(self) -> bool:
        """Check if running in production."""
        return self.environment.lower() == 'prod'
    
    def get_table_name(self, table_type: str) -> str:
        """Get table name with environment suffix."""
        table_map = {
            'dedupe': self.dedupe_table,
            'alerts': self.alerts_table,
            'feedback': self.feedback_table,
            'monitoring': self.monitoring_table
        }
        return table_map.get(table_type, f'fraud-{table_type}-{self.environment}')


# Singleton instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get singleton config instance."""
    global _config
    if _config is None:
        _config = Config()
    return _config


# For local testing
if __name__ == "__main__":
    config = get_config()
    print(f"Environment: {config.environment}")
    print(f"AWS Region: {config.aws_region}")
    print(f"Bronze Bucket: {config.bronze_bucket}")
    print(f"PSI Threshold: {config.psi_threshold}")
    print(f"Is Production: {config.is_production()}")
