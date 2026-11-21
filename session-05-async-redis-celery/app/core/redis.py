"""One async Redis client and connection pool per running API process."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from redis.asyncio import Redis

from app.core.config import settings


@asynccontextmanager
async def redis_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Verify Redis at startup and release its pool, even if startup fails."""
    client = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=5,
        # Blocking commands use their own server-side wait, which can exceed 5s.
        socket_timeout=None,
        health_check_interval=30,
    )
    try:
        # Bound readiness separately from the shared client's command behavior.
        async with asyncio.timeout(5):
            await client.ping()
        app.state.redis = client
        yield
    finally:
        app.state.redis = None
        await client.aclose()


def get_redis(request: Request) -> Redis:
    """Return the shared client; callers should bound request-path operations."""
    client = getattr(request.app.state, "redis", None)
    if client is None:
        raise RuntimeError("Redis client is unavailable; run the app lifespan first")
    return client
