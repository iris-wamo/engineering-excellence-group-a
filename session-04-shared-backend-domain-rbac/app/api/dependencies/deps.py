from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an async database session for API routes."""
    async for session in get_async_session():
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db)]


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
