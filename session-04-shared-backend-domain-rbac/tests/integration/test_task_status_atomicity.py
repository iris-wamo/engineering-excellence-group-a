"""Integration tests: atomicity of a status transition (all-or-nothing).

Fault injection proves the acceptance criterion "failed transitions must not
leave partial state":

    task status update + status history + activity log = ONE transaction

Each test injects a failure at a different point of the write path and then
re-reads the database through an independent session to assert that
* nothing of the transition was persisted (no partial task update),
* no partial history row exists,
* no partial activity row exists.

Injection happens in the tests (monkeypatch); production code stays clean and
just uses the Session 3 pattern: stage writes -> single commit -> rollback.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies.deps import get_db
from app.core.config import settings
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.task import Task, TaskStatus
from app.models.task_status_history import TaskStatusHistory
from app.services import task_service


@pytest_asyncio.fixture
async def test_session():
    """Independent session used to inspect what actually persisted."""
    engine = create_async_engine(settings.test_database_url, echo=False)
    session_factory = sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client with DB dependency override."""
    test_engine = create_async_engine(settings.test_database_url, echo=False)
    test_session_local = sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )

    async def override_get_db():
        async with test_session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    await test_engine.dispose()


async def _create_user(client: AsyncClient) -> str:
    unique_id = str(uuid.uuid4())[:8]
    response = await client.post(
        "/users",
        json={
            "name": f"Atomic User {unique_id}",
            "username": f"atomic_user_{unique_id}",
            "email": f"atomic_user_{unique_id}@example.com",
            "password": "SecurePassword123!",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_project(client: AsyncClient, owner_id: str) -> str:
    response = await client.post(
        "/projects",
        json={
            "title": "Atomicity Project",
            "priority": "MEDIUM",
            "status": "ACTIVE",
            "owner_id": owner_id,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_task(client: AsyncClient, project_id: str, assignee_id: str) -> str:
    response = await client.post(
        "/tasks",
        json={
            "title": "Atomicity task",
            "project_id": project_id,
            "assignee_id": assignee_id,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _assert_transition_fully_rolled_back(
    session: AsyncSession, task_uuid: uuid.UUID
) -> None:
    """Nothing persisted: status untouched, no history row, no activity row."""
    session.expire_all()
    status = (
        await session.execute(select(Task.status).where(Task.id == task_uuid))
    ).scalar_one()
    assert status == TaskStatus.TODO

    history = (
        (
            await session.execute(
                select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert history == []

    activities = (
        (
            await session.execute(
                select(ActivityLog).where(ActivityLog.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert activities == []


@pytest.mark.asyncio
async def test_flush_then_failure_proves_rollback_of_written_rows(
    client: AsyncClient, test_session: AsyncSession, monkeypatch
):
    """THE rollback proof: real rows are written, then something fails.

    Unlike a failure raised before any SQL is sent, this injects the failure
    *after* a genuine flush, so the open transaction already contains the task
    UPDATE and both INSERTs. Only a real ROLLBACK can leave the database clean.

        task update -> history/activity write -> FAILURE -> ROLLBACK
    """
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    real_flush = AsyncSession.flush
    real_rollback = AsyncSession.rollback
    in_transaction: dict[str, object] = {}
    rollback_calls: list[bool] = []

    async def _spy_rollback(session, *args, **kwargs):
        rollback_calls.append(True)
        return await real_rollback(session, *args, **kwargs)

    async def _flush_then_fail(session, *args, **kwargs):
        # 1. Actually send the UPDATE + INSERTs to PostgreSQL (uncommitted)
        await real_flush(session, *args, **kwargs)

        # 2. Capture the partial state sitting inside the live transaction
        in_transaction["status"] = (
            await session.execute(select(Task.status).where(Task.id == task_uuid))
        ).scalar_one()
        in_transaction["history"] = len(
            (
                await session.execute(
                    select(TaskStatusHistory).where(
                        TaskStatusHistory.task_id == task_uuid
                    )
                )
            )
            .scalars()
            .all()
        )
        in_transaction["activity"] = len(
            (
                await session.execute(
                    select(ActivityLog).where(ActivityLog.task_id == task_uuid)
                )
            )
            .scalars()
            .all()
        )

        # 3. Now fail, as a mid-operation error would
        raise RuntimeError("injected failure after flush")

    with monkeypatch.context() as m:
        m.setattr(AsyncSession, "flush", _flush_then_fail)
        m.setattr(AsyncSession, "rollback", _spy_rollback)
        with pytest.raises(RuntimeError, match="injected failure after flush"):
            await client.patch(
                f"/tasks/{task_id}/status",
                json={"status": "in_progress"},
                headers={"X-User-ID": actor_id},
            )

    # The service explicitly rolled the failed transaction back
    assert rollback_calls == [True]

    # Proof that partial state really existed before the rollback ran
    assert in_transaction == {
        "status": TaskStatus.IN_PROGRESS,
        "history": 1,
        "activity": 1,
    }

    # ROLLBACK undid the written rows: original status, no partial history/activity
    await _assert_transition_fully_rolled_back(test_session, task_uuid)


@pytest.mark.asyncio
async def test_failure_creating_history_rolls_back_task_update(
    client: AsyncClient, test_session: AsyncSession, monkeypatch
):
    """Task status is already staged when history creation blows up."""
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("injected failure: status history")

    with monkeypatch.context() as m:
        m.setattr(task_service.TaskRepository, "add_status_history", _boom)
        with pytest.raises(RuntimeError, match="injected failure: status history"):
            await client.patch(
                f"/tasks/{task_id}/status",
                json={"status": "in_progress"},
                headers={"X-User-ID": actor_id},
            )

    # The staged status update must not survive on its own
    await _assert_transition_fully_rolled_back(test_session, task_uuid)


@pytest.mark.asyncio
async def test_failure_creating_activity_rolls_back_task_and_history(
    client: AsyncClient, test_session: AsyncSession, monkeypatch
):
    """Task update + history are both staged when activity creation blows up."""
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("injected failure: activity log")

    with monkeypatch.context() as m:
        m.setattr(task_service.ActivityLogRepository, "stage_create", _boom)
        with pytest.raises(RuntimeError, match="injected failure: activity log"):
            await client.patch(
                f"/tasks/{task_id}/status",
                json={"status": "in_progress"},
                headers={"X-User-ID": actor_id},
            )

    await _assert_transition_fully_rolled_back(test_session, task_uuid)


@pytest.mark.asyncio
async def test_failure_at_commit_rolls_back_all_three_writes(
    client: AsyncClient, test_session: AsyncSession, monkeypatch
):
    """All three writes staged, COMMIT fails -> everything is undone."""
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    async def _failing_commit(_self):
        raise RuntimeError("injected failure: commit")

    with monkeypatch.context() as m:
        m.setattr(AsyncSession, "commit", _failing_commit)
        with pytest.raises(RuntimeError, match="injected failure: commit"):
            await client.patch(
                f"/tasks/{task_id}/status",
                json={"status": "in_progress"},
                headers={"X-User-ID": actor_id},
            )

    await _assert_transition_fully_rolled_back(test_session, task_uuid)


@pytest.mark.asyncio
async def test_failure_at_flush_rolls_back_all_three_writes(
    client: AsyncClient, test_session: AsyncSession, monkeypatch
):
    """A DB-level error raised during flush never reaches COMMIT."""
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    flush_spy = AsyncMock(side_effect=RuntimeError("injected failure: flush"))

    with monkeypatch.context() as m:
        m.setattr(AsyncSession, "flush", flush_spy)
        with pytest.raises(RuntimeError, match="injected failure: flush"):
            await client.patch(
                f"/tasks/{task_id}/status",
                json={"status": "in_progress"},
                headers={"X-User-ID": actor_id},
            )

    await _assert_transition_fully_rolled_back(test_session, task_uuid)


@pytest.mark.asyncio
async def test_failed_transition_does_not_poison_later_success(
    client: AsyncClient, test_session: AsyncSession, monkeypatch
):
    """After a rolled-back attempt, a valid transition still commits cleanly."""
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("injected failure: activity log")

    with monkeypatch.context() as m:
        m.setattr(task_service.ActivityLogRepository, "stage_create", _boom)
        with pytest.raises(RuntimeError):
            await client.patch(
                f"/tasks/{task_id}/status",
                json={"status": "in_progress"},
                headers={"X-User-ID": actor_id},
            )

    await _assert_transition_fully_rolled_back(test_session, task_uuid)

    # Same endpoint, same task, now clean -> exactly one audit pair persisted
    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": actor_id},
    )
    assert response.status_code == 200

    test_session.expire_all()
    status = (
        await test_session.execute(select(Task.status).where(Task.id == task_uuid))
    ).scalar_one()
    history = (
        (
            await test_session.execute(
                select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    )
    activities = (
        (
            await test_session.execute(
                select(ActivityLog).where(ActivityLog.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    )

    assert status == TaskStatus.IN_PROGRESS
    assert len(history) == 1
    assert len(activities) == 1
    assert history[0].new_status == TaskStatus.IN_PROGRESS
    assert activities[0].action == "task.status_changed"
