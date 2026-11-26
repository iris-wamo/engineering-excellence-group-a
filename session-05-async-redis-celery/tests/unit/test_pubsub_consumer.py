"""Pub/Sub subscriber: parsing, logging and fire-and-forget delivery."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.events import publisher
from app.events.publisher import TASK_EVENTS_CHANNEL, publish_task_event
from app.events.pubsub_consumer import consume, handle_message
from app.events.schemas import TaskEvent, TaskEventData, TaskEventType


def _event() -> TaskEvent:
    return TaskEvent(
        type=TaskEventType.STATUS_CHANGED,
        actor_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        data=TaskEventData(from_status="todo", to_status="in_progress"),
    )


def test_handle_message_logs_event(caplog):
    caplog.set_level(logging.INFO, logger="taskflow.pubsub_consumer")
    event = _event()
    assert handle_message(event.model_dump_json()) == event
    assert "received task.status_changed v1" in caplog.text
    assert str(event.event_id) in caplog.text


def test_handle_message_skips_bad_payload(caplog):
    caplog.set_level(logging.WARNING, logger="taskflow.pubsub_consumer")
    assert handle_message('{"not": "an event"}') is None
    assert "skipped invalid event" in caplog.text


@pytest.mark.asyncio
async def test_event_is_lost_when_no_subscriber(monkeypatch, caplog):
    redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await redis.ping()
    except (RedisError, OSError):
        await redis.aclose()
        pytest.skip("Redis is not running")
    monkeypatch.setattr(publisher, "_redis", redis)
    caplog.set_level(logging.INFO, logger="taskflow.pubsub_consumer")

    # published while nobody listens: Redis delivers it to 0 subscribers
    missed = _event()
    assert await redis.publish(TASK_EVENTS_CHANNEL, missed.model_dump_json()) == 0

    consumer = asyncio.create_task(consume(redis))
    while await redis.pubsub_numsub(TASK_EVENTS_CHANNEL) == [(TASK_EVENTS_CHANNEL, 0)]:
        await asyncio.sleep(0.05)

    received = _event()
    assert await publish_task_event(received) is True
    await asyncio.sleep(0.3)
    consumer.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await consumer
    await redis.aclose()

    assert str(received.event_id) in caplog.text
    assert str(missed.event_id) not in caplog.text
