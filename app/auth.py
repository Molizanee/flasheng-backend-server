"""Supabase JWT authentication using JWKS (JSON Web Key Set).

Uses the modern JWKS endpoint and RS256 asymmetric signing keys
instead of the legacy static JWT secret with HS256.
"""

import logging

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, DecodeError, ExpiredSignatureError, InvalidTokenError
import jwt

from app.config import get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)
_jwks_client = None


def get_jwks_client() -> PyJWKClient:
    """Get or create a cached PyJWKClient for Supabase JWKS.

    The JWKS endpoint is at: https://<project>.supabase.co/auth/v1/.well-known/jwks.json
    """
    global _jwks_client
    if _jwks_client is None:
        settings = get_settings()
        # Construct JWKS URL from supabase_url
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_keys=True)
        logger.info("Initialized JWKS client for %s", jwks_url)
    return _jwks_client


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """Validate a Supabase JWT and return the user ID (``sub`` claim).

    The client must send the header ``Authorization: Bearer <supabase_jwt>``.

    First tries JWKS/RS256 (modern approach), then falls back to HS256 with
    JWT secret if configured.

    Returns:
        The ``sub`` claim from the JWT, which is the Supabase user ID.

    Raises:
        HTTPException 401: If the token is missing, expired, or invalid.
    """
    if credentials is None:
        logger.error("No Authorization header received")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing. Use: Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    settings = get_settings()

    # Debug logging
    logger.info(
        "Received token (first 50 chars): %s...",
        token[:50] if len(token) > 50 else token,
    )

    # Try JWKS/RS256 first (modern approach)
    try:
        logger.info("Attempting JWKS/RS256 validation...")
        jwks_client = get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        logger.info("Signing key found from JWKS")

        # Try ES256 first (your token uses this), then RS256
        algorithms = ["ES256", "RS256"]
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=algorithms,
            audience="authenticated",
        )
        logger.info("JWT decoded successfully with RS256")

        user_id: str | None = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token does not contain a valid user identifier.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user_id

    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as jwks_exc:
        logger.warning("JWKS validation failed: %s", jwks_exc)

    # Fallback to HS256 if JWT secret is configured
    if settings.supabase_jwt_secret:
        logger.info("Falling back to HS256 validation with configured secret...")
        try:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
            logger.info("JWT decoded successfully with HS256")

            user_id: str | None = payload.get("sub")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token does not contain a valid user identifier.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return user_id

        except ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except InvalidTokenError as exc:
            logger.error("HS256 validation also failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # Neither method worked
    logger.error("All JWT validation methods failed")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
