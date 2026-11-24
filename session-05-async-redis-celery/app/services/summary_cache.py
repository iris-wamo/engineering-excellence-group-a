"""Per-user Redis cache for GET /tasks/summary."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Iterable
from uuid import UUID

from pydantic import ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.repositories.task_repository import TaskRepository
from app.schemas.task_summary import TaskSummaryResponse

logger = logging.getLogger("taskflow.summary_cache")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

KEY_FORMAT = "taskflow:v1:summary:user:{user_id}"

# a down or hanging Redis must never fail the request
_REDIS_ERRORS = (RedisError, OSError, TimeoutError)


def summary_key(user_id: UUID) -> str:
    return KEY_FORMAT.format(user_id=user_id)


async def get_cached_summary(
    redis: Redis | None, user_id: UUID
) -> TaskSummaryResponse | None:
    """Cached summary, or None on a miss or when Redis is unavailable."""
    if redis is None:
        logger.warning("summary cache: Redis not configured, computing directly")
        return None
    try:
        async with asyncio.timeout(settings.SUMMARY_CACHE_TIMEOUT_SECONDS):
            raw = await redis.get(summary_key(user_id))
    except _REDIS_ERRORS as exc:
        logger.warning("summary cache: Redis unavailable (%r), computing directly", exc)
        return None
    summary = None
    if raw is not None:
        with contextlib.suppress(ValidationError):
            summary = TaskSummaryResponse.model_validate_json(raw)
    logger.info("summary cache %s user=%s", "HIT" if summary else "MISS", user_id)
    return summary


async def set_cached_summary(
    redis: Redis | None, user_id: UUID, summary: TaskSummaryResponse
) -> None:
    if redis is None:
        return
    try:
        async with asyncio.timeout(settings.SUMMARY_CACHE_TIMEOUT_SECONDS):
            await redis.set(
                summary_key(user_id),
                summary.model_dump_json(),
                ex=settings.SUMMARY_CACHE_TTL_SECONDS,
            )
    except _REDIS_ERRORS as exc:
        logger.warning("summary cache: could not store summary (%r)", exc)


async def invalidate_summary_cache(
    redis: Redis | None, user_ids: Iterable[UUID]
) -> None:
    keys = [summary_key(user_id) for user_id in user_ids]
    if redis is None or not keys:
        return
    try:
        async with asyncio.timeout(settings.SUMMARY_CACHE_TIMEOUT_SECONDS):
            await redis.delete(*keys)
    except _REDIS_ERRORS as exc:
        # entries still expire after the TTL
        logger.warning("summary cache: invalidation failed (%r)", exc)
        return
    logger.info("summary cache: invalidated %d user(s)", len(keys))


async def invalidate_project_summaries(
    redis: Redis | None, db: AsyncSession, project_id: UUID
) -> None:
    """Drop the cached summary of everyone who can see this project's tasks."""
    if redis is None:
        return
    user_ids = await TaskRepository.summary_audience(db, project_id)
    await invalidate_summary_cache(redis, user_ids)
