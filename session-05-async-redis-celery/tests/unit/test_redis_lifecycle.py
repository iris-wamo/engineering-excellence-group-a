"""Verify the actual app lifespan without requiring a Redis server."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from starlette.requests import Request

from app.core.config import settings
from app.core.redis import get_redis
from app.main import app


@pytest.mark.asyncio
async def test_lifespan_shares_one_client_and_closes_it():
    client = AsyncMock()
    request = Request({"type": "http", "app": app})
    with patch("app.core.redis.Redis.from_url", return_value=client) as factory:
        async with app.router.lifespan_context(app):
            assert get_redis(request) is client
            assert get_redis(request) is client
            factory.assert_called_once_with(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=None,
                health_check_interval=30,
            )
            client.ping.assert_awaited_once()
            client.aclose.assert_not_awaited()

    client.aclose.assert_awaited_once()
    with pytest.raises(RuntimeError, match="unavailable"):
        get_redis(request)


@pytest.mark.asyncio
async def test_failed_startup_closes_client_and_propagates_error():
    client = AsyncMock()
    client.ping.side_effect = RedisConnectionError("Redis is offline")
    with (
        patch("app.core.redis.Redis.from_url", return_value=client),
        pytest.raises(RedisConnectionError, match="offline"),
    ):
        async with app.router.lifespan_context(app):
            pytest.fail("An unreachable Redis must prevent startup")

    client.aclose.assert_awaited_once()
    assert app.state.redis is None


@pytest.mark.asyncio
async def test_request_processing_failure_still_closes_client():
    client = AsyncMock()
    with (
        patch("app.core.redis.Redis.from_url", return_value=client),
        pytest.raises(ValueError, match="processing failed"),
    ):
        async with app.router.lifespan_context(app):
            raise ValueError("processing failed")

    client.aclose.assert_awaited_once()
    assert app.state.redis is None


@pytest.mark.asyncio
async def test_startup_deadline_closes_client_when_ping_never_responds():
    async def stalled_ping():
        await asyncio.Future()

    client = AsyncMock()
    client.ping.side_effect = stalled_ping
    # The outer deadline fails the test if the app's shorter deadline is missing.
    async with asyncio.timeout(10):
        with (
            patch("app.core.redis.Redis.from_url", return_value=client),
            pytest.raises(TimeoutError),
        ):
            async with app.router.lifespan_context(app):
                pytest.fail("Startup must fail when its readiness deadline expires")

    client.aclose.assert_awaited_once()
    assert app.state.redis is None
