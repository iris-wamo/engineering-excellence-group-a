"""Redis Pub/Sub subscriber that logs every task event.

Run with `make pubsub-consumer`. Pub/Sub is fire-and-forget: events published
while this process is not running are never delivered to it.
"""

from __future__ import annotations

import asyncio
import logging

from pydantic import ValidationError
from redis.asyncio import Redis

from app.core.config import settings
from app.events.publisher import TASK_EVENTS_CHANNEL
from app.events.schemas import TaskEvent

logger = logging.getLogger("taskflow.pubsub_consumer")


def handle_message(raw: str) -> TaskEvent | None:
    """Parse and log one message; bad payloads are logged and skipped."""
    try:
        event = TaskEvent.model_validate_json(raw)
    except ValidationError:
        logger.warning("skipped invalid event payload: %s", raw[:200])
        return None
    logger.info(
        "received %s v%d event_id=%s task=%s actor=%s data=%s",
        event.type,
        event.version,
        event.event_id,
        event.task_id,
        event.actor_id,
        event.data.model_dump(mode="json", exclude_none=True),
    )
    return event


async def consume(redis: Redis) -> None:
    async with redis.pubsub() as pubsub:
        await pubsub.subscribe(TASK_EVENTS_CHANNEL)
        logger.info("subscribed to %s, waiting for events", TASK_EVENTS_CHANNEL)
        async for message in pubsub.listen():
            if message["type"] == "message":
                handle_message(message["data"])


async def main() -> None:
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await consume(redis)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("stopped")
