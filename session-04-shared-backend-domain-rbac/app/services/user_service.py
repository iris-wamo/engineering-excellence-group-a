from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password, verify_password
from app.auth.permissions import is_admin
from app.auth.roles import UserRole
from app.core.exceptions import (
    CannotChangeOwnRoleError,
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    UsernameAlreadyExistsError,
    UserNotFoundError,
)
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate


class UserService:
    """Business logic service layer for User management."""

    @staticmethod
    async def create_user(
        db: AsyncSession, payload: UserCreate, role: UserRole = UserRole.MEMBER
    ) -> User:
        """Create a new user ensuring email and username uniqueness.

        Signup always passes the default ``member`` role; only the admin-only
        endpoint passes another role.
        """
        # 1. Check if email already exists
        existing_email = await UserRepository.get_by_email(db, str(payload.email))
        if existing_email is not None:
            raise EmailAlreadyExistsError()

        # 2. Check if username already exists
        existing_username = await UserRepository.get_by_username(db, payload.username)
        if existing_username is not None:
            raise UsernameAlreadyExistsError()

        # 3. Hash the raw password (Argon2)
        hashed_password = hash_password(payload.password)

        # 4. Delegate creation to repository layer
        return await UserRepository.create(
            db,
            name=payload.name,
            username=payload.username,
            email=str(payload.email),
            password_hash=hashed_password,
            role=role,
        )

    @staticmethod
    async def authenticate(db: AsyncSession, login: str, password: str) -> User:
        """Return the user for a username/email + password, else 401.

        The same error is raised for an unknown login and a wrong password,
        and both paths run a hash check, so accounts cannot be enumerated.
        """
        user = await UserRepository.get_by_login(db, login)
        stored_hash = user.password_hash if user is not None else None
        if not verify_password(password, stored_hash) or user is None:
            raise InvalidCredentialsError()
        return user

    @staticmethod
    async def get_users(
        db: AsyncSession,
        actor: User,
        *,
        limit: int = 10,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        """Admins see every user; others see themselves and project co-members."""
        visible_to = None if is_admin(actor) else actor.id
        return await UserRepository.get_all(
            db, limit=limit, offset=offset, visible_to=visible_to
        )

    @staticmethod
    async def get_user(db: AsyncSession, user_id: UUID) -> User:
        """Fetch a user by UUID or raise UserNotFoundError."""
        user = await UserRepository.get_by_id(db, user_id)
        if user is None:
            raise UserNotFoundError()

        return user

    @staticmethod
    async def get_visible_user(db: AsyncSession, user_id: UUID, actor: User) -> User:
        """Fetch a user the actor may see; 404 for anyone outside their projects."""
        if not is_admin(actor) and not await UserRepository.is_visible_to(
            db, user_id, actor.id
        ):
            raise UserNotFoundError()
        return await UserService.get_user(db, user_id)

    @staticmethod
    async def change_role(
        db: AsyncSession, user_id: UUID, role: UserRole, actor: User
    ) -> User:
        """Admin-only: change a user's global role.

        Demoting a manager to member also downgrades their project-manager
        memberships, so they keep access to those projects but stop running
        them. Admins cannot change their own role (avoids locking out the last
        admin).
        """
        if user_id == actor.id:
            raise CannotChangeOwnRoleError()

        user = await UserService.get_user(db, user_id)
        try:
            if role == UserRole.MEMBER and user.role != UserRole.MEMBER:
                await ProjectRepository.downgrade_managerships(db, user_id)
            user.role = role
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        await db.refresh(user)
        return user
