from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    EmailAlreadyExistsError,
    UsernameAlreadyExistsError,
    UserNotFoundError,
)
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate


def _hash_password(password: str) -> str:
    """Hash password securely using SHA-256 with salt."""
    salt = "taskflow_salt_v1"
    return hashlib.sha256(f"{password}{salt}".encode()).hexdigest()


class UserService:
    """Business logic service layer for User management."""

    @staticmethod
    async def create_user(db: AsyncSession, payload: UserCreate) -> User:
        """Create a new user ensuring email and username uniqueness."""
        # 1. Check if email already exists
        existing_email = await UserRepository.get_by_email(db, str(payload.email))
        if existing_email is not None:
            raise EmailAlreadyExistsError()

        # 2. Check if username already exists
        existing_username = await UserRepository.get_by_username(db, payload.username)
        if existing_username is not None:
            raise UsernameAlreadyExistsError()

        # 3. Hash the raw password
        hashed_password = _hash_password(payload.password)

        # 4. Delegate creation to repository layer with default 'user' role
        return await UserRepository.create(
            db,
            name=payload.name,
            username=payload.username,
            email=str(payload.email),
            password_hash=hashed_password,
            role="user",
        )

    @staticmethod
    async def get_users(
        db: AsyncSession,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        """Fetch a paginated list of users along with total count."""
        return await UserRepository.get_all(db, limit=limit, offset=offset)

    @staticmethod
    async def get_user(db: AsyncSession, user_id: UUID) -> User:
        """Fetch a user by UUID or raise UserNotFoundError."""
        user = await UserRepository.get_by_id(db, user_id)
        if user is None:
            raise UserNotFoundError()

        return user
