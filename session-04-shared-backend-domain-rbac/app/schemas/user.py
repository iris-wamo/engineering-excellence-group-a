from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """Request payload schema for creating a new user."""

    name: str = Field(
        ..., min_length=1, max_length=255, description="Full name of the user"
    )
    username: str = Field(
        ..., min_length=3, max_length=50, description="Unique username"
    )
    email: EmailStr = Field(..., description="Valid email address")
    password: str = Field(
        ..., min_length=6, max_length=128, description="User password (min 6 chars)"
    )


class UserResponse(BaseModel):
    """Response DTO schema for user details.

    Security Notice: password_hash is deliberately excluded to prevent credential leaking.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    username: str
    email: EmailStr
    role: str


class UserListResponse(BaseModel):
    """Paginated list response wrapper for users."""

    items: list[UserResponse]
    page: int = Field(..., ge=1, description="Current page number")
    page_size: int = Field(..., ge=1, le=100, description="Items per page")
    total: int = Field(..., ge=0, description="Total matching users count")
