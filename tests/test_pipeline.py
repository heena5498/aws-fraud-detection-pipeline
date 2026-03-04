"""Test suite for fraud detection pipeline."""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path


def test_data_exists():
    """Test that data directory structure exists."""
    assert Path("data").exists()
    assert Path("data/raw").exists()
    assert Path("etl").exists()
    assert Path("ml").exists()


def test_config_valid():
    """Test configuration file is valid."""
    import yaml
    
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    
    assert 'data' in config
    assert 'ml' in config
    assert 'kafka' in config
    assert 'api' in config


def test_transaction_generation():
    """Test synthetic transaction generation."""
    from scripts.download_data import generate_synthetic_transactions
    
    df = generate_synthetic_transactions(n_samples=1000)
    
    assert len(df) == 1000
    assert 'transaction_id' in df.columns
    assert 'amount' in df.columns
    assert 'is_fraud' in df.columns
    assert df['is_fraud'].sum() > 0  # Should have some fraud


# Add more tests as needed
