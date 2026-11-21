"""Tests for GET /tasks/summary with faked repositories (no DB)."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.deps import get_db, get_session_factory
from app.auth.dependencies import get_current_user
from app.core.config import settings
from app.main import app
from app.models.task import TaskStatus
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.schemas.task_summary import SummaryMode
from app.services.task_summary_service import (
    ExternalCallConfig,
    TaskSummaryService,
    run_external,
)

STATUS_KEYS = {"todo", "in_progress", "in_review", "done", "cancelled"}


@asynccontextmanager
async def _fake_session():
    yield None


def _fake_factory():
    return _fake_session()


@pytest.fixture
def repo(monkeypatch):
    fakes = {
        "count_by_status": AsyncMock(
            return_value={TaskStatus.TODO: 3, TaskStatus.DONE: 2}
        ),
        "count_overdue": AsyncMock(return_value=1),
        "count_assigned_to": AsyncMock(return_value=2),
    }
    for name, fake in fakes.items():
        monkeypatch.setattr(TaskRepository, name, fake)
    monkeypatch.setattr(settings, "SUMMARY_EXTERNAL_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(settings, "SUMMARY_EXTERNAL_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(settings, "SUMMARY_EXTERNAL_FAIL", False)
    return fakes


@pytest_asyncio.fixture
async def make_client(repo):  # noqa: ARG001 - activates the fakes
    original = app.dependency_overrides.copy()

    async def fake_db():
        yield AsyncMock()

    @asynccontextmanager
    async def _client(role: str = "member"):
        actor = User(id=uuid4(), role=role)

        async def fake_user():
            return actor

        app.dependency_overrides[get_db] = fake_db
        app.dependency_overrides[get_session_factory] = lambda: _fake_factory
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


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["async", "blocking"])
async def test_summary_shape(make_client, mode):
    async with make_client() as (client, _actor):
        response = await client.get("/tasks/summary", params={"mode": mode})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == mode
    assert set(body["by_status"]) == STATUS_KEYS
    assert body["by_status"]["todo"] == 3
    assert body["by_status"]["done"] == 2
    assert body["by_status"]["in_review"] == 0
    assert body["total"] == 5
    assert body["overdue"] == 1
    assert body["assigned_to_me"] == 2
    assert body["external"]["status"] == "ok"
    assert body["external"]["data"] == {"service": "reporting", "healthy": True}
    assert body["elapsed_ms"] >= 0


@pytest.mark.asyncio
async def test_summary_defaults_to_async_and_rejects_unknown_mode(make_client):
    async with make_client() as (client, _actor):
        default = await client.get("/tasks/summary")
        bad = await client.get("/tasks/summary", params={"mode": "threads"})
    assert default.status_code == 200
    assert default.json()["mode"] == "async"
    assert bad.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "scoped"), [("admin", False), ("manager", True), ("member", True)]
)
async def test_summary_rbac_scoping(make_client, repo, role, scoped):
    async with make_client(role) as (client, actor):
        response = await client.get("/tasks/summary")
    assert response.status_code == 200, response.text
    expected = actor.id if scoped else None
    for name in ("count_by_status", "count_overdue", "count_assigned_to"):
        assert repo[name].await_args.kwargs["member_user_id"] == expected
    assert repo["count_assigned_to"].await_args.args[1] == actor.id


@pytest.mark.asyncio
async def test_summary_requires_auth():
    original = app.dependency_overrides.copy()

    async def fake_db():
        yield None

    app.dependency_overrides[get_db] = fake_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/tasks/summary")
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["async", "blocking"])
async def test_summary_timeout_returns_partial_summary(make_client, mode):
    async with make_client() as (client, _actor):
        started = time.perf_counter()
        response = await client.get(
            "/tasks/summary", params={"mode": mode, "external_delay": 5}
        )
        took = time.perf_counter() - started
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["external"]["status"] == "timeout"
    assert body["external"]["data"] is None
    # the counts are still there
    assert body["total"] == 5
    assert body["overdue"] == 1
    # 0.2s timeout, not the 5s delay
    assert took < 2


@pytest.mark.asyncio
async def test_summary_timeout_from_settings(make_client, monkeypatch):
    monkeypatch.setattr(settings, "SUMMARY_EXTERNAL_DELAY_SECONDS", 1.0)
    async with make_client() as (client, _actor):
        response = await client.get("/tasks/summary")
    assert response.json()["external"]["status"] == "timeout"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["async", "blocking"])
async def test_summary_external_failure_is_reported(make_client, mode):
    async with make_client() as (client, _actor):
        response = await client.get(
            "/tasks/summary", params={"mode": mode, "external_fail": True}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["external"]["status"] == "error"
    assert body["total"] == 5


@pytest.mark.asyncio
async def test_run_external_wait_for_cancels_async_call():
    config = ExternalCallConfig(delay_seconds=5, timeout_seconds=0.05)
    started = time.perf_counter()
    result = await run_external(config)
    assert result.status == "timeout"
    assert time.perf_counter() - started < 1


async def _ticker(stop: asyncio.Event) -> int:
    """Counts how often the loop lets it run."""
    ticks = 0
    while not stop.is_set():
        ticks += 1
        await asyncio.sleep(0.01)
    return ticks


async def _summaries(mode: SummaryMode, n: int) -> tuple[float, int]:
    actor = User(id=uuid4(), role="admin")
    config = ExternalCallConfig(delay_seconds=0.1, timeout_seconds=1)
    stop = asyncio.Event()
    ticker = asyncio.create_task(_ticker(stop))
    started = time.perf_counter()
    await asyncio.gather(
        *(
            TaskSummaryService.get_summary(
                _fake_factory, actor, mode=mode, external=config
            )
            for _ in range(n)
        )
    )
    took = time.perf_counter() - started
    stop.set()
    return took, await ticker


@pytest.mark.asyncio
async def test_async_mode_overlaps_and_blocking_mode_stalls_the_loop(repo):  # noqa: ARG001
    async_took, async_ticks = await _summaries(SummaryMode.ASYNC, 5)
    blocking_took, blocking_ticks = await _summaries(SummaryMode.BLOCKING, 5)

    assert async_took < 0.3
    assert blocking_took >= 0.5
    # time.sleep blocks the ticker
    assert async_ticks >= 5
    assert blocking_ticks <= 2
