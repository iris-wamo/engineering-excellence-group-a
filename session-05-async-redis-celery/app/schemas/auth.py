from __future__ import annotations

from pydantic import BaseModel, Field


class TokenResponse(BaseModel):
    """OAuth2-compatible access token response returned by POST /auth/login."""

    access_token: str
    token_type: str = Field(default="bearer")
    expires_in: int = Field(..., description="Token lifetime in seconds")
