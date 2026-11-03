from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from taskflow_shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from taskflow_shared.pagination import PaginationParams as SharedPaginationParams

from app.db.database import get_async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an async database session for API routes."""
    async for session in get_async_session():
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db)]


class PaginationParams(SharedPaginationParams):
    def __init__(
        self,
        page: int = Query(1, ge=1, description="Page number"),
        page_size: int = Query(
            DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Items per page"
        ),
    ):
        super().__init__(page=page, page_size=page_size)
