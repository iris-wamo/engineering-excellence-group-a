"""JWT access-token creation and validation (PyJWT, HS256 by default)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from app.core.config import settings

_TOKEN_TYPE = "access"


class TokenValidationError(Exception):
    """The token is missing claims, expired, tampered with or otherwise invalid."""


@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_in: int  # seconds


def create_access_token(user_id: UUID, role: str) -> AccessToken:
    """Sign a short-lived access token for ``user_id``.

    ``role`` is informational for clients; the server re-reads the user's
    role from the database on every request and never trusts this claim.
    """
    now = datetime.now(UTC)
    lifetime = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims = {
        "sub": str(user_id),
        "role": role,
        "type": _TOKEN_TYPE,
        "iat": now,
        "exp": now + lifetime,
    }
    token = jwt.encode(
        claims, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    return AccessToken(token=token, expires_in=int(lifetime.total_seconds()))


def decode_access_token(token: str) -> UUID:
    """Validate ``token`` and return the user id in its ``sub`` claim."""
    try:
        claims = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenValidationError(str(exc)) from exc

    if claims.get("type") != _TOKEN_TYPE:
        raise TokenValidationError("Not an access token")
    try:
        return UUID(claims["sub"])
    except (TypeError, ValueError) as exc:
        raise TokenValidationError("Malformed subject claim") from exc
