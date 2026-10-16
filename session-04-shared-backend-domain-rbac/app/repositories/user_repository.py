from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.roles import UserRole
from app.models.project_member import ProjectMember
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
    async def get_by_login(db: AsyncSession, login: str) -> User | None:
        """Fetch user by username, or by email when ``login`` contains '@'."""
        column = User.email if "@" in login else User.username
        result = await db.execute(select(User).where(column == login))
        return result.scalar_one_or_none()

    @staticmethod
    def _visible_to(user_id: UUID):
        """Condition: the user themselves, or anyone sharing a project with them."""
        my_projects = select(ProjectMember.project_id).where(
            ProjectMember.user_id == user_id
        )
        co_members = select(ProjectMember.user_id).where(
            ProjectMember.project_id.in_(my_projects)
        )
        return or_(User.id == user_id, User.id.in_(co_members))

    @staticmethod
    async def get_all(
        db: AsyncSession,
        limit: int = 10,
        offset: int = 0,
        visible_to: UUID | None = None,
    ) -> tuple[list[User], int]:
        """Fetch paginated list of users along with total count.

        ``visible_to`` limits the result to that user and their project co-members.
        """
        query = select(User)
        if visible_to is not None:
            query = query.where(UserRepository._visible_to(visible_to))

        count_res = await db.execute(select(func.count()).select_from(query.subquery()))
        total = count_res.scalar_one()

        result = await db.execute(query.offset(offset).limit(limit))
        users = list(result.scalars().all())

        return users, total

    @staticmethod
    async def is_visible_to(db: AsyncSession, user_id: UUID, viewer_id: UUID) -> bool:
        """True when ``viewer_id`` may see ``user_id`` (self or project co-member)."""
        result = await db.execute(
            select(User.id).where(
                User.id == user_id, UserRepository._visible_to(viewer_id)
            )
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def create(
        db: AsyncSession,
        name: str,
        username: str,
        email: str,
        password_hash: str,
        role: str = UserRole.MEMBER,
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
