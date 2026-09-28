from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UserRepository:
    """Repository handling database operations for the User entity."""

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: UUID) -> User | None:
        """Fetch user by UUID primary key."""
        result = await db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_email(db: AsyncSession, email: str) -> User | None:
        """Fetch user by email address."""
        result = await db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_username(db: AsyncSession, username: str) -> User | None:
        """Fetch user by unique username."""
        result = await db.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(
        db: AsyncSession,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        """Fetch paginated list of users along with total count."""
        count_res = await db.execute(select(func.count(User.id)))
        total = count_res.scalar_one()

        query = select(User).offset(offset).limit(limit)
        result = await db.execute(query)
        users = list(result.scalars().all())

        return users, total

    @staticmethod
    async def create(
        db: AsyncSession,
        name: str,
        username: str,
        email: str,
        password_hash: str,
        role: str = "user",
    ) -> User:
        """Create and persist a new user entity in the database."""
        user = User(
            name=name,
            username=username,
            email=email,
            password_hash=password_hash,
            role=role,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user
