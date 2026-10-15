"""Integration tests: a valid status transition is actually persisted.

Verifies the persistence guarantees for the happy path (todo -> in_progress):

1. The task row in PostgreSQL receives the new status.
2. The transaction is committed (a brand-new, independent session sees it).
3. A subsequent DB read returns the new status + its audit trail.
4. Session 3 transaction patterns are reused: staged writes inside the
   service, a single commit, and zero partial writes on rejection.

These tests talk to the real test database and re-read through separate
sessions so an in-request (uncommitted) change can never pass them.
"""

import uuid

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


@pytest_asyncio.fixture
async def test_session():
    """Independent session: proves data was COMMITTED, not just staged."""
    engine = create_async_engine(settings.test_database_url, echo=False)
    session_factory = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client with DB dependency override."""
    test_engine = create_async_engine(settings.test_database_url, echo=False)
    test_session_local = sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
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
    payload = {
        "name": f"Persistence User {unique_id}",
        "username": f"persist_user_{unique_id}",
        "email": f"persist_user_{unique_id}@example.com",
        "password": "SecurePassword123!",
    }
    response = await client.post("/users", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


async def _create_project(client: AsyncClient, owner_id: str) -> str:
    payload = {
        "title": "Persistence Project",
        "description": "Project used for status persistence tests",
        "priority": "MEDIUM",
        "status": "ACTIVE",
        "owner_id": owner_id,
    }
    response = await client.post("/projects", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


async def _create_task(client: AsyncClient, project_id: str, assignee_id: str) -> str:
    payload = {
        "title": "Persist todo -> in_progress",
        "project_id": project_id,
        "assignee_id": assignee_id,
        "status": "todo",
    }
    response = await client.post("/tasks", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_valid_transition_updates_task_status_in_database(
    client: AsyncClient, test_session: AsyncSession
):
    """todo -> in_progress: the row in PostgreSQL really changes."""
    owner_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)
    task_id = await _create_task(client, project_id, owner_id)
    task_uuid = uuid.UUID(task_id)

    # Status before the transition, read straight from the database
    before = (
        await test_session.execute(select(Task.status).where(Task.id == task_uuid))
    ).scalar_one()
    assert before == TaskStatus.TODO

    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": owner_id},
    )
    assert response.status_code == 200

    # Independent session -> this can only succeed if the commit landed
    test_session.expire_all()
    db_task = (
        await test_session.execute(select(Task).where(Task.id == task_uuid))
    ).scalar_one()

    assert db_task.status == TaskStatus.IN_PROGRESS
    assert db_task.id == task_uuid
    assert db_task.updated_at is not None


@pytest.mark.asyncio
async def test_transition_commit_is_visible_to_a_fresh_connection(client: AsyncClient):
    """Commit proof: a brand-new engine/connection reads the new status."""
    owner_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)
    task_id = await _create_task(client, project_id, owner_id)
    task_uuid = uuid.UUID(task_id)

    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": owner_id},
    )
    assert response.status_code == 200

    # Fresh engine = fresh connection pool, no shared transaction state
    fresh_engine = create_async_engine(settings.test_database_url, echo=False)
    fresh_factory = sessionmaker(
        bind=fresh_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with fresh_factory() as fresh_session:
            status = (
                await fresh_session.execute(
                    select(Task.status).where(Task.id == task_uuid)
                )
            ).scalar_one()
            history_count = len(
                (
                    await fresh_session.execute(
                        select(TaskStatusHistory).where(
                            TaskStatusHistory.task_id == task_uuid
                        )
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await fresh_engine.dispose()

    assert status == TaskStatus.IN_PROGRESS
    # Exactly one audit row: committed once, not duplicated or partially written
    assert history_count == 1


@pytest.mark.asyncio
async def test_subsequent_db_read_shows_new_status_and_audit_trail(
    client: AsyncClient, test_session: AsyncSession
):
    """A later read returns the new status plus the committed history/activity."""
    owner_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)
    task_id = await _create_task(client, project_id, owner_id)
    task_uuid = uuid.UUID(task_id)

    await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": owner_id},
    )

    # Re-read the task through a later, independent query
    test_session.expire_all()
    reread = (
        await test_session.execute(select(Task).where(Task.id == task_uuid))
    ).scalar_one()
    assert reread.status == TaskStatus.IN_PROGRESS

    # The audit trail was committed in the same transaction (Session 3 pattern)
    status_rows = (
        (
            await test_session.execute(
                select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert len(status_rows) == 1
    assert status_rows[0].previous_status == TaskStatus.TODO
    assert status_rows[0].new_status == TaskStatus.IN_PROGRESS
    assert status_rows[0].changed_by_id == uuid.UUID(owner_id)

    activity_rows = (
        (
            await test_session.execute(
                select(ActivityLog).where(ActivityLog.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert len(activity_rows) == 1
    assert activity_rows[0].action == "task.status_changed"
    assert activity_rows[0].details["new_status"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_rejected_transition_leaves_zero_partial_writes(
    client: AsyncClient, test_session: AsyncSession
):
    """Session 3 rollback guarantee reused: nothing persists on rejection."""
    owner_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)
    task_id = await _create_task(client, project_id, owner_id)
    task_uuid = uuid.UUID(task_id)

    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "done"},  # todo -> done skips the workflow
        headers={"X-User-ID": owner_id},
    )
    assert response.status_code == 409

    test_session.expire_all()
    status = (
        await test_session.execute(select(Task.status).where(Task.id == task_uuid))
    ).scalar_one()
    assert status == TaskStatus.TODO

    assert (
        (
            await test_session.execute(
                select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    ) == []
    assert (
        (
            await test_session.execute(
                select(ActivityLog).where(ActivityLog.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    ) == []


@pytest.mark.asyncio
async def test_each_step_of_workflow_commits_in_order(
    client: AsyncClient, test_session: AsyncSession
):
    """todo -> in_progress -> in_review: every step is committed and audited."""
    owner_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)
    task_id = await _create_task(client, project_id, owner_id)
    task_uuid = uuid.UUID(task_id)

    for next_status in ("in_progress", "in_review"):
        response = await client.patch(
            f"/tasks/{task_id}/status",
            json={"status": next_status},
            headers={"X-User-ID": owner_id},
        )
        assert response.status_code == 200

    test_session.expire_all()
    final_status = (
        await test_session.execute(select(Task.status).where(Task.id == task_uuid))
    ).scalar_one()
    assert final_status == TaskStatus.IN_REVIEW

    rows = (
        (
            await test_session.execute(
                select(TaskStatusHistory)
                .where(TaskStatusHistory.task_id == task_uuid)
                .order_by(TaskStatusHistory.created_at)
            )
        )
        .scalars()
        .all()
    )
    assert [(r.previous_status, r.new_status) for r in rows] == [
        (TaskStatus.TODO, TaskStatus.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW),
    ]
