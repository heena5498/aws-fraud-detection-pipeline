"""Tests for OIDC authentication (no identity provider needed)."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.testclient import TestClient

ISSUER = "http://localhost:8180/realms/fraud-detection"
AUDIENCE = "fraud-api"

private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class FakeJWKSClient:
    """Stands in for the provider's key endpoint, serving our test public key."""

    class _Key:
        key = private_key.public_key()

    def get_signing_key_from_jwt(self, token):
        return self._Key()


def make_token(**overrides):
    now = int(time.time())
    claims = {"sub": "user-1", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300}
    claims.update(overrides)
    return jwt.encode(claims, private_key, algorithm="RS256")


@pytest.fixture
def verifier():
    from api.auth import OIDCVerifier

    v = OIDCVerifier(issuer=ISSUER, audience=AUDIENCE)
    v.jwks_client = FakeJWKSClient()
    return v


def test_valid_token(verifier):
    claims = verifier.verify(make_token())
    assert claims["sub"] == "user-1"


@pytest.mark.parametrize("overrides", [
    {"exp": int(time.time()) - 10},          # expired
    {"aud": "some-other-api"},               # wrong audience
    {"iss": "http://evil.example.com"},      # wrong issuer
])
def test_rejected_tokens(verifier, overrides):
    with pytest.raises(HTTPException) as exc:
        verifier.verify(make_token(**overrides))
    assert exc.value.status_code == 401


def test_token_signed_with_other_key_rejected(verifier):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    token = jwt.encode(
        {"sub": "x", "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + 300},
        other_key, algorithm="RS256"
    )
    with pytest.raises(HTTPException) as exc:
        verifier.verify(token)
    assert exc.value.status_code == 401


def test_endpoint_protection(monkeypatch):
    import api.main as am

    # setitem on __dict__ avoids triggering the real (network) cached_property
    monkeypatch.setitem(am.oidc_verifier.__dict__, "jwks_client", FakeJWKSClient())
    client = TestClient(am.app)  # no startup event, so the model is not loaded

    assert client.get("/model/info").status_code == 401
    assert client.get("/model/info", headers={"Authorization": "Bearer garbage"}).status_code == 401

    # Valid token passes auth and reaches the endpoint (503 = model not loaded)
    resp = client.get("/model/info", headers={"Authorization": f"Bearer {make_token()}"})
    assert resp.status_code == 503

    # Public endpoints stay open for machine callers
    assert client.get("/health").status_code == 200
