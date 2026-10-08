"""
OIDC Authentication
===================
Verifies OIDC access tokens (JWTs) issued by the identity provider
(Keycloak in local development, see docker-compose.yml).

Flow:
1. A user logs in at the identity provider and receives a signed access token
2. The client calls the API with header: Authorization: Bearer <token>
3. This module checks the token's signature (using the provider's public keys),
   issuer, audience and expiry before the endpoint runs
"""

from functools import cached_property
from typing import Dict, Optional

import jwt
import requests
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

# auto_error=False so we can return a proper 401 (with WWW-Authenticate) ourselves
bearer_scheme = HTTPBearer(auto_error=False)


class OIDCVerifier:
    """Validate bearer tokens against an OIDC issuer."""

    def __init__(self, issuer: str, audience: str, algorithms: Optional[list] = None):
        self.issuer = issuer.rstrip('/')
        self.audience = audience
        self.algorithms = algorithms or ["RS256"]

    @cached_property
    def jwks_client(self) -> jwt.PyJWKClient:
        """
        Discover the provider's signing keys (JWKS) via the standard
        /.well-known/openid-configuration document. Fetched lazily on the first
        authenticated request, so the API can start before the provider is up.
        """
        discovery_url = f"{self.issuer}/.well-known/openid-configuration"
        response = requests.get(discovery_url, timeout=5)
        response.raise_for_status()
        jwks_uri = response.json()['jwks_uri']
        logger.info(f"✓ OIDC keys discovered at {jwks_uri}")
        return jwt.PyJWKClient(jwks_uri, cache_keys=True)

    def verify(self, token: str) -> Dict:
        """Return the token's claims if valid, otherwise raise HTTPException."""
        try:
            signing_key = self.jwks_client.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                signing_key.key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except (requests.RequestException, jwt.PyJWKClientConnectionError) as e:
            logger.error(f"Identity provider unreachable: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Identity provider unavailable"
            )
        except (jwt.InvalidTokenError, jwt.PyJWKClientError) as e:
            logger.warning(f"Rejected token: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    def authenticate(
        self,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
    ) -> Dict:
        """FastAPI dependency: require a valid bearer token, return its claims."""
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return self.verify(credentials.credentials)
