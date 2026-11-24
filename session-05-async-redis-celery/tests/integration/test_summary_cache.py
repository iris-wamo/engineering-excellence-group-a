"""Redis cache for GET /tasks/summary (repositories faked, real Redis)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api.dependencies.deps import get_db, get_session_factory
from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.core.redis import get_optional_redis
from app.main import app
from app.models.task import TaskStatus
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.schemas.task_summary import (
    ExternalResult,
    ExternalStatus,
    SummaryMode,
    TaskSummaryResponse,
)
from app.services.summary_cache import (
    invalidate_summary_cache,
    set_cached_summary,
    summary_key,
)


@asynccontextmanager
async def _fake_session():
    yield None


@pytest_asyncio.fixture
async def redis_client():
    client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except (RedisError, OSError):
        await client.aclose()
        pytest.skip("Redis is not running")
    yield client
    await client.aclose()


@pytest.fixture
def repo(monkeypatch):
    fakes = {
        "count_by_status": AsyncMock(return_value={TaskStatus.TODO: 2}),
        "count_overdue": AsyncMock(return_value=1),
        "count_assigned_to": AsyncMock(return_value=1),
    }
    for name, fake in fakes.items():
        monkeypatch.setattr(TaskRepository, name, fake)
    monkeypatch.setattr(settings, "SUMMARY_EXTERNAL_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(settings, "SUMMARY_EXTERNAL_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(settings, "SUMMARY_EXTERNAL_FAIL", False)
    return fakes


@pytest_asyncio.fixture
async def make_client(repo):  # noqa: ARG001
    original = app.dependency_overrides.copy()
    actor = User(id=uuid4(), role="member")

    async def fake_db():
        yield AsyncMock()

    async def fake_user():
        return actor

    @asynccontextmanager
    async def _client(redis):
        app.dependency_overrides[get_optional_redis] = lambda: redis
        app.dependency_overrides[get_db] = fake_db
        app.dependency_overrides[get_session_factory] = lambda: _fake_session
        app.dependency_overrides[get_current_user] = fake_user
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, actor

    try:
        yield _client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


async def _get(client, **params):
    response = await client.get("/tasks/summary", params=params)
    assert response.status_code == 200, response.text
    return response


@pytest.mark.asyncio
async def test_miss_then_hit(make_client, repo, redis_client):
    async with make_client(redis_client) as (client, actor):
        first = await _get(client)
        second = await _get(client)
    try:
        assert first.headers["X-Cache"] == "MISS"
        assert second.headers["X-Cache"] == "HIT"
        assert second.json() == first.json()
        assert repo["count_by_status"].await_count == 1
        ttl = await redis_client.ttl(summary_key(actor.id))
        assert 0 < ttl <= settings.SUMMARY_CACHE_TTL_SECONDS
    finally:
        await redis_client.delete(summary_key(actor.id))


@pytest.mark.asyncio
async def test_ttl_expiry(make_client, redis_client, monkeypatch):
    monkeypatch.setattr(settings, "SUMMARY_CACHE_TTL_SECONDS", 1)
    async with make_client(redis_client) as (client, _actor):
        assert (await _get(client)).headers["X-Cache"] == "MISS"
        assert (await _get(client)).headers["X-Cache"] == "HIT"
        await asyncio.sleep(1.2)
        assert (await _get(client)).headers["X-Cache"] == "MISS"


@pytest.mark.asyncio
async def test_invalidation_forces_miss(make_client, redis_client):
    async with make_client(redis_client) as (client, actor):
        await _get(client)
        await invalidate_summary_cache(redis_client, [actor.id])
        assert (await _get(client)).headers["X-Cache"] == "MISS"
    await redis_client.delete(summary_key(actor.id))


@pytest.mark.asyncio
@pytest.mark.parametrize("redis", ["down", "missing"])
async def test_redis_unavailable_falls_back(make_client, repo, caplog, redis):
    client_down = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    caplog.set_level(logging.WARNING, logger="taskflow.summary_cache")
    async with make_client(client_down if redis == "down" else None) as (client, _):
        first = await _get(client)
        second = await _get(client)
    await client_down.aclose()
    assert first.headers["X-Cache"] == second.headers["X-Cache"] == "MISS"
    assert first.json()["total"] == 2
    assert repo["count_by_status"].await_count == 2
    assert "computing directly" in caplog.text


@pytest.mark.asyncio
async def test_partial_summary_is_not_cached(make_client, redis_client, monkeypatch):
    monkeypatch.setattr(settings, "SUMMARY_EXTERNAL_DELAY_SECONDS", 1)
    async with make_client(redis_client) as (client, actor):
        body = (await _get(client)).json()
        assert body["external"]["status"] == "timeout"
        assert await redis_client.exists(summary_key(actor.id)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "params",
    [{"cache": "false"}, {"mode": "blocking"}, {"external_delay": "0"}],
)
async def test_demo_requests_skip_cache(make_client, redis_client, params):
    async with make_client(redis_client) as (client, actor):
        assert (await _get(client, **params)).headers["X-Cache"] == "MISS"
        assert (await _get(client, **params)).headers["X-Cache"] == "MISS"
        assert await redis_client.exists(summary_key(actor.id)) == 0


@pytest.mark.asyncio
async def test_key_format(redis_client):
    user_id = uuid4()
    summary = TaskSummaryResponse(
        mode=SummaryMode.ASYNC,
        by_status={"todo": 0},
        total=0,
        overdue=0,
        assigned_to_me=0,
        external=ExternalResult(status=ExternalStatus.OK, elapsed_ms=1),
        elapsed_ms=1,
    )
    await set_cached_summary(redis_client, user_id, summary)
    key = f"taskflow:v1:summary:user:{user_id}"
    assert await redis_client.exists(key) == 1
    await redis_client.delete(key)
