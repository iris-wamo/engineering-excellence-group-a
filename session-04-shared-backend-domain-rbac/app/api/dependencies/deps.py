from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CurrentUserNotFoundError, MissingUserHeaderError
from app.db.database import get_async_session
from app.models.user import User
from app.repositories.user_repository import UserRepository


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an async database session for API routes."""
    async for session in get_async_session():
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: SessionDep,
    x_user_id: UUID | None = Header(default=None, alias="X-User-ID"),
) -> User:
    """Resolve the acting user from the X-User-ID header.

    Stand-in for real authentication: 401 if the header is missing or the
    referenced user does not exist.
    """
    if x_user_id is None:
        raise MissingUserHeaderError()
    user = await UserRepository.get_by_id(db, x_user_id)
    if user is None:
        raise CurrentUserNotFoundError()
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


class PaginationParams:
    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(10, ge=1, le=100, description="Items per page"),
    ):
        self.page = page
        self.page_size = page_size
        self.offset = (page - 1) * page_size
        self.limit = page_size
