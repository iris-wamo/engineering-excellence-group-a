"""Task writes invalidate cached summaries (test DB + real Redis)."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.api.dependencies.deps import get_session_factory
from app.core.config import settings
from app.core.redis import get_optional_redis
from app.main import app
from app.services.summary_cache import summary_key
from tests.auth.conftest import World


@pytest_asyncio.fixture
async def cached(session_factory, world: World):
    client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await client.ping()
    except (RedisError, OSError):
        await client.aclose()
        pytest.skip("Redis is not running")
    app.dependency_overrides[get_optional_redis] = lambda: client
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    yield client
    users = (world.admin, world.alice, world.bob, world.carol, world.dave)
    await client.delete(*(summary_key(u.id) for u in users))
    await client.aclose()


async def _cache_header(client: AsyncClient, headers: dict[str, str]) -> str:
    response = await client.get("/tasks/summary", headers=headers)
    assert response.status_code == 200, response.text
    return response.headers["X-Cache"]


@pytest.mark.asyncio
async def test_status_change_invalidates(client: AsyncClient, world: World, cached):  # noqa: ARG001
    for actor in (world.alice, world.carol):
        assert await _cache_header(client, actor.headers) == "MISS"
        assert await _cache_header(client, actor.headers) == "HIT"
    # bob is a manager elsewhere, so his summary doesn't include this project
    assert await _cache_header(client, world.bob.headers) == "MISS"

    res = await client.patch(
        f"/tasks/{world.carol_task_id}/status",
        json={"status": "in_progress"},
        headers=world.carol.headers,
    )
    assert res.status_code == 200, res.text

    for actor in (world.alice, world.carol):
        assert await _cache_header(client, actor.headers) == "MISS"
    assert await _cache_header(client, world.bob.headers) == "HIT"

    body = (await client.get("/tasks/summary", headers=world.alice.headers)).json()
    assert body["by_status"]["in_progress"] == 1


@pytest.mark.asyncio
async def test_create_and_assign_invalidate(
    client: AsyncClient,
    world: World,
    cached,  # noqa: ARG001
):
    await _cache_header(client, world.alice.headers)
    res = await client.post(
        "/tasks",
        json={"title": "new task", "project_id": world.project_id},
        headers=world.alice.headers,
    )
    assert res.status_code == 201, res.text
    assert await _cache_header(client, world.alice.headers) == "MISS"

    await _cache_header(client, world.dave.headers)
    res = await client.post(
        f"/tasks/{res.json()['id']}/assign",
        json={"assignee_id": world.dave.id},
        headers=world.alice.headers,
    )
    assert res.status_code == 200, res.text
    assert await _cache_header(client, world.dave.headers) == "MISS"
