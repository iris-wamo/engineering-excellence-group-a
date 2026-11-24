"""Database access owned by Celery workers, separate from the API's request scope.

Celery tasks are synchronous. Each task drives async code with ``run_async``,
which starts a fresh event loop per call. asyncpg connections belong to the loop
that opened them, so the API's pooled engine (``app.db.database``) must not be
reused here: a pooled connection from a previous loop would fail. ``NullPool``
opens a connection per session and closes it when the session ends.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

if settings.DATABASE_URL is None:
    raise ValueError("DATABASE_URL is not configured")

worker_engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=NullPool,
)

WorkerSessionLocal = async_sessionmaker(
    bind=worker_engine,
    expire_on_commit=False,
)


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine to completion from a synchronous Celery task."""
    return asyncio.run(coro)
