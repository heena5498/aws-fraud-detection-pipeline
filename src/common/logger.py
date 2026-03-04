"""
Structured JSON logging for CloudWatch.
Enables efficient querying with CloudWatch Insights.
"""

import logging
import json
import sys
from datetime import datetime
from typing import Any, Dict, Optional
import traceback


class JSONFormatter(logging.Formatter):
    """
    Custom formatter that outputs JSON for structured logging.
    
    Format:
    {
        "timestamp": "2026-03-03T14:30:00.123Z",
        "level": "INFO",
        "logger": "bronze-layer",
        "message": "Processing batch",
        "transaction_id": "txn_001",
        "custom_field": "value"
    }
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage()
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': traceback.format_exception(*record.exc_info)
            }
        
        # Add extra fields from `extra` parameter
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)
        
        # Add any custom attributes
        for key, value in record.__dict__.items():
            if key not in [
                'name', 'msg', 'args', 'created', 'filename', 'funcName',
                'levelname', 'lineno', 'module', 'msecs', 'pathname',
                'process', 'processName', 'relativeCreated', 'thread',
                'threadName', 'exc_info', 'exc_text', 'stack_info',
                'extra_data'
            ]:
                if not key.startswith('_'):
                    log_data[key] = value
        
        return json.dumps(log_data)


def get_logger(
    name: str,
    level: str = None,
    use_json: bool = True
) -> logging.Logger:
    """
    Get configured logger instance.
    
    Args:
        name: Logger name (typically __name__ or service name)
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        use_json: Use JSON formatter (default True for CloudWatch)
    
    Returns:
        Configured logger instance
    """
    import os
    
    logger = logging.getLogger(name)
    
    # Set level from parameter or environment
    log_level = level or os.getenv('LOG_LEVEL', 'INFO')
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Avoid duplicate handlers
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        
        if use_json:
            handler.setFormatter(JSONFormatter())
        else:
            # Human-readable format for local dev
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
        
        logger.addHandler(handler)
    
    return logger


class LoggerAdapter(logging.LoggerAdapter):
    """
    Adapter to add contextual information to all log messages.
    
    Usage:
        logger = get_logger(__name__)
        contextual_logger = LoggerAdapter(logger, {'transaction_id': 'txn_001'})
        contextual_logger.info("Processing")  # Will include transaction_id
    """
    
    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        """Add extra context to log record."""
        if 'extra' not in kwargs:
            kwargs['extra'] = {}
        kwargs['extra'].update(self.extra)
        return msg, kwargs


# For local testing
if __name__ == "__main__":
    # JSON logging
    logger = get_logger('test-service', level='DEBUG', use_json=True)
    
    logger.info("Test info message")
    logger.warning("Test warning", extra={'custom_field': 'value'})
    logger.error("Test error", extra={'error_code': 'E001'})
    
    try:
        raise ValueError("Test exception")
    except ValueError:
        logger.exception("Exception occurred")
    
    print("\n--- Human-readable logging ---\n")
    
    # Human-readable format
    logger2 = get_logger('test-service-2', use_json=False)
    logger2.info("This is human-readable")
    logger2.error("Error message")
