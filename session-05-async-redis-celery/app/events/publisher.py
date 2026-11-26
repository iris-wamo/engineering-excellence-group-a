"""Publishes task events to Redis. Never raises: a lost event must not fail the request."""

from __future__ import annotations

import asyncio
import logging

from redis.asyncio import Redis

from app.events.schemas import TaskEvent

logger = logging.getLogger("taskflow.events")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

TASK_EVENTS_CHANNEL = "taskflow:events:task"
PUBLISH_TIMEOUT_SECONDS = 1.0

_redis: Redis | None = None


def bind_redis(client: Redis | None) -> None:
    """Set by the app lifespan so events use the shared client."""
    global _redis
    _redis = client


async def publish_task_event(event: TaskEvent) -> bool:
    """Call only after the DB commit succeeded. Returns False if the event was lost."""
    if _redis is None:
        logger.warning(
            "event %s %s not published: no Redis client", event.type, event.event_id
        )
        return False
    try:
        async with asyncio.timeout(PUBLISH_TIMEOUT_SECONDS):
            await _redis.publish(TASK_EVENTS_CHANNEL, event.model_dump_json())
    except Exception as exc:
        logger.warning("event %s %s not published: %r", event.type, event.event_id, exc)
        return False
    logger.info("event %s %s published", event.type, event.event_id)
    return True
