"""
CloudWatch Metrics client for custom application metrics.
Enables monitoring dashboards and alarms.
"""

import boto3
from datetime import datetime
from typing import Optional, Dict, List
import logging
from config import get_config

logger = logging.getLogger(__name__)


class MetricsClient:
    """
    Wrapper for CloudWatch put_metric_data.
    Batches metrics and handles retries.
    """
    
    def __init__(self, namespace: Optional[str] = None, region: Optional[str] = None):
        """
        Initialize metrics client.
        
        Args:
            namespace: CloudWatch namespace (default from config)
            region: AWS region (default from config)
        """
        config = get_config()
        
        self.namespace = namespace or config.cloudwatch_namespace
        self.region = region or config.aws_region
        self.cloudwatch = boto3.client('cloudwatch', region_name=self.region)
        
        # Metric buffer for batching
        self.metric_buffer: List[Dict] = []
        self.max_buffer_size = 20  # CloudWatch PutMetricData limit
        
        logger.debug(f"Initialized metrics client: namespace={self.namespace}")
    
    def emit(
        self,
        metric_name: str,
        value: float,
        unit: str = 'None',
        dimensions: Optional[Dict[str, str]] = None,
        timestamp: Optional[datetime] = None
    ):
        """
        Emit a metric to CloudWatch.
        
        Args:
            metric_name: Metric name
            value: Metric value
            unit: CloudWatch unit (Count, Seconds, Bytes, etc.)
            dimensions: Dict of dimension name/value pairs
            timestamp: Metric timestamp (defaults to now)
        """
        metric_data = {
            'MetricName': metric_name,
            'Value': value,
            'Unit': unit,
            'Timestamp': timestamp or datetime.utcnow()
        }
        
        if dimensions:
            metric_data['Dimensions'] = [
                {'Name': k, 'Value': v}
                for k, v in dimensions.items()
            ]
        
        self.metric_buffer.append(metric_data)
        
        # Flush if buffer is full
        if len(self.metric_buffer) >= self.max_buffer_size:
            self.flush()
    
    def flush(self):
        """Send buffered metrics to CloudWatch."""
        if not self.metric_buffer:
            return
        
        try:
            self.cloudwatch.put_metric_data(
                Namespace=self.namespace,
                MetricData=self.metric_buffer
            )
            
            logger.debug(f"Flushed {len(self.metric_buffer)} metrics to CloudWatch")
            self.metric_buffer.clear()
        
        except Exception as e:
            logger.error(f"Failed to flush metrics: {e}")
            # Clear buffer to prevent memory buildup
            self.metric_buffer.clear()
    
    def __del__(self):
        """Flush remaining metrics on deletion."""
        self.flush()


# Global metrics client instance
_metrics_client: Optional[MetricsClient] = None


def get_metrics_client() -> MetricsClient:
    """Get singleton metrics client."""
    global _metrics_client
    if _metrics_client is None:
        _metrics_client = MetricsClient()
    return _metrics_client


def emit_metric(
    metric_name: str,
    value: float,
    unit: str = 'None',
    dimensions: Optional[Dict[str, str]] = None
):
    """
    Convenience function to emit a metric.
    
    Usage:
        emit_metric('RecordsProcessed', 100, 'Count')
        emit_metric('ProcessingTime', 1.5, 'Seconds', {'stage': 'bronze'})
    """
    client = get_metrics_client()
    client.emit(metric_name, value, unit, dimensions)


def emit_counter(metric_name: str, count: int = 1, dimensions: Optional[Dict[str, str]] = None):
    """Emit a counter metric."""
    emit_metric(metric_name, count, 'Count', dimensions)


def emit_gauge(metric_name: str, value: float, dimensions: Optional[Dict[str, str]] = None):
    """Emit a gauge metric."""
    emit_metric(metric_name, value, 'None', dimensions)


def emit_timer(metric_name: str, seconds: float, dimensions: Optional[Dict[str, str]] = None):
    """Emit a timing metric."""
    emit_metric(metric_name, seconds, 'Seconds', dimensions)


# Context manager for timing
class Timer:
    """
    Context manager for timing operations.
    
    Usage:
        with Timer('ProcessingTime', dimensions={'stage': 'bronze'}):
            # ... do work ...
            pass
    """
    
    def __init__(self, metric_name: str, dimensions: Optional[Dict[str, str]] = None):
        self.metric_name = metric_name
        self.dimensions = dimensions
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            emit_timer(self.metric_name, elapsed, self.dimensions)


# For local testing
if __name__ == "__main__":
    import time
    
    # Emit some test metrics
    emit_counter('TestCounter', 1)
    emit_gauge('TestGauge', 42.0)
    emit_timer('TestTimer', 1.5)
    
    # Test timer context manager
    with Timer('TestOperation'):
        time.sleep(0.1)
    
    # Flush remaining metrics
    get_metrics_client().flush()
    
    print("Metrics emitted successfully")
