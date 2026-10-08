"""Regression test: serving-time features must match training-time encoding."""

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from xgboost import XGBClassifier


@pytest.fixture
def client(tmp_path, monkeypatch):
    """API loaded with a small model trained on one-hot encoded data, like ml/train.py."""
    import api.main as am

    rng = np.random.default_rng(0)
    n = 200
    X = pd.DataFrame({
        'amount': rng.uniform(1, 3000, n),
        'hour_of_day': rng.integers(0, 24, n),
        'merchant_category': rng.choice(['entertainment', 'grocery', 'online', 'travel'], n),
        'country': rng.choice(['AU', 'UK', 'US'], n),
    })
    y = (X['amount'] > 2000).astype(int)

    # Same encoding as FraudModelTrainer.encode_categorical_features
    X = pd.get_dummies(X, columns=['merchant_category', 'country'], drop_first=True)
    model = XGBClassifier(n_estimators=5, max_depth=2).fit(X, y)

    model_path = tmp_path / "model.pkl"
    joblib.dump(model, model_path)
    monkeypatch.setitem(am.config['api'], 'model_path', str(model_path))

    with TestClient(am.app) as c:  # runs the startup event, which loads the model
        yield c, am


@pytest.mark.parametrize("category,country", [
    ("online", "US"),          # regular one-hot columns
    ("entertainment", "AU"),   # categories dropped by drop_first -> all zeros
    ("unseen_category", "ZZ"), # categories never seen in training
    (None, None),              # optional fields omitted
])
def test_predict_succeeds(client, category, country):
    c, _ = client
    txn = {
        "transaction_id": "txn_1", "user_id": "user_1", "merchant_id": "merchant_1",
        "amount": 2500.0, "timestamp": "2026-10-07 02:13:00",
        "merchant_category": category, "country": country,
    }
    resp = c.post("/predict", json=txn)
    assert resp.status_code == 200, resp.text
    assert 0 <= resp.json()["fraud_probability"] <= 1


def test_features_match_model_columns(client):
    _, am = client
    txn = am.Transaction(
        transaction_id="t", user_id="u", merchant_id="m", amount=50.0,
        timestamp="2026-10-07 14:00:00", merchant_category="online", country="US",
    )
    features = am.engineer_features(txn)

    assert list(features.columns) == list(am.model.feature_names_in_)
    assert features['merchant_category_online'].iloc[0] == 1
    assert features['merchant_category_travel'].iloc[0] == 0
    assert features['country_US'].iloc[0] == 1
