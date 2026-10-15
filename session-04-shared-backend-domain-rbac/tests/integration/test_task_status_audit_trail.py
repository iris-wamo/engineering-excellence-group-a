"""Integration tests: activity/history integration for status transitions.

For every SUCCESSFUL transition the service must write, in the same
transaction and only after validation succeeds:

1. one ``TaskStatusHistory`` row: previous status, new status, actor;
2. one ``ActivityLog`` row: ``task.status_changed`` with both statuses;
3. nothing at all when the transition is a no-op or is rejected.

The tests re-read through an independent session and compare the audit
rows against the status values actually read from the database, so the
history/activity can never disagree with the real transition.
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
    """Independent session for direct audit-trail assertions."""
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
            "name": f"Audit User {unique_id}",
            "username": f"audit_user_{unique_id}",
            "email": f"audit_user_{unique_id}@example.com",
            "password": "SecurePassword123!",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_project(client: AsyncClient, owner_id: str) -> str:
    response = await client.post(
        "/projects",
        json={
            "title": "Audit Trail Project",
            "priority": "MEDIUM",
            "status": "ACTIVE",
            "owner_id": owner_id,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_task(
    client: AsyncClient, project_id: str, assignee_id: str | None
) -> str:
    payload: dict[str, object] = {
        "title": "Audit trail task",
        "project_id": project_id,
    }
    if assignee_id is not None:
        payload["assignee_id"] = assignee_id
    response = await client.post("/tasks", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


async def _db_status(session: AsyncSession, task_uuid: uuid.UUID) -> TaskStatus:
    return (
        await session.execute(select(Task.status).where(Task.id == task_uuid))
    ).scalar_one()


async def _history(session: AsyncSession, task_uuid: uuid.UUID):
    return (
        (
            await session.execute(
                select(TaskStatusHistory)
                .where(TaskStatusHistory.task_id == task_uuid)
                .order_by(TaskStatusHistory.created_at)
            )
        )
        .scalars()
        .all()
    )


async def _activities(session: AsyncSession, task_uuid: uuid.UUID):
    return (
        (
            await session.execute(
                select(ActivityLog)
                .where(ActivityLog.task_id == task_uuid)
                .order_by(ActivityLog.created_at)
            )
        )
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_every_successful_transition_writes_history_and_activity(
    client: AsyncClient, test_session: AsyncSession
):
    """Walk the workflow: each successful step adds exactly one pair of rows."""
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    expected_steps = [
        (TaskStatus.TODO, TaskStatus.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW),
        (TaskStatus.IN_REVIEW, TaskStatus.DONE),
    ]

    for index, (expected_prev, expected_next) in enumerate(expected_steps, start=1):
        # Status before the call, read straight from the DB
        status_before = await _db_status(test_session, task_uuid)

        response = await client.patch(
            f"/tasks/{task_id}/status",
            json={"status": expected_next.value.lower()},
            headers={"X-User-ID": actor_id},
        )
        assert response.status_code == 200

        test_session.expire_all()
        status_after = await _db_status(test_session, task_uuid)

        # The audit trail describes the transition that actually happened
        assert status_before == expected_prev
        assert status_after == expected_next

        history = await _history(test_session, task_uuid)
        activities = await _activities(test_session, task_uuid)
        assert len(history) == index
        assert len(activities) == index

        latest = history[-1]
        assert latest.previous_status == status_before
        assert latest.new_status == status_after
        assert latest.changed_by_id == uuid.UUID(actor_id)
        assert latest.task_id == task_uuid

        latest_activity = activities[-1]
        assert latest_activity.action == "task.status_changed"
        assert latest_activity.actor_id == uuid.UUID(actor_id)
        assert latest_activity.task_id == task_uuid
        assert latest_activity.details == {
            "previous_status": status_before.value,
            "new_status": status_after.value,
        }


@pytest.mark.asyncio
async def test_actor_recorded_is_the_user_who_performed_the_change(
    client: AsyncClient, test_session: AsyncSession
):
    """A project owner changing someone else's task is credited, not the assignee."""
    owner_id = await _create_user(client)
    assignee_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)
    task_id = await _create_task(client, project_id, assignee_id)
    task_uuid = uuid.UUID(task_id)

    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": owner_id},  # owner acts
    )
    assert response.status_code == 200

    test_session.expire_all()
    history = await _history(test_session, task_uuid)
    activities = await _activities(test_session, task_uuid)

    assert len(history) == 1
    assert history[0].changed_by_id == uuid.UUID(owner_id)
    assert history[0].previous_status == TaskStatus.TODO
    assert history[0].new_status == TaskStatus.IN_PROGRESS
    assert activities[0].actor_id == uuid.UUID(owner_id)
    # The assignee did not perform the change
    assert history[0].changed_by_id != uuid.UUID(assignee_id)


@pytest.mark.asyncio
async def test_history_and_activity_endpoints_mirror_the_transition(
    client: AsyncClient, test_session: AsyncSession
):
    """The audit APIs return the same transition the database recorded."""
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": actor_id},
    )
    assert response.status_code == 200

    # GET /tasks/{id}/history
    history_res = await client.get(f"/tasks/{task_id}/history")
    assert history_res.status_code == 200
    statuses = history_res.json()["statuses"]
    assert len(statuses) == 1
    assert statuses[0]["previous_status"] == "todo"
    assert statuses[0]["new_status"] == "in_progress"
    assert statuses[0]["changed_by_id"] == actor_id
    assert statuses[0]["task_id"] == task_id

    # GET /tasks/{id}/activity
    activity_res = await client.get(f"/tasks/{task_id}/activity")
    assert activity_res.status_code == 200
    activities = activity_res.json()
    assert len(activities) == 1
    assert activities[0]["action"] == "task.status_changed"
    assert activities[0]["actor_id"] == actor_id
    assert activities[0]["details"]["previous_status"] == "TODO"
    assert activities[0]["details"]["new_status"] == "IN_PROGRESS"

    # The task's live status agrees with the audit trail
    test_session.expire_all()
    assert await _db_status(test_session, task_uuid) == TaskStatus.IN_PROGRESS

    # API and database describe the exact same transition
    db_history = await _history(test_session, task_uuid)
    assert statuses[0]["new_status"] == db_history[0].new_status.value.lower()


@pytest.mark.asyncio
async def test_noop_transition_writes_no_audit_rows(
    client: AsyncClient, test_session: AsyncSession
):
    """Re-sending the same status is idempotent: no history, no activity."""
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "todo"},  # already todo
        headers={"X-User-ID": actor_id},
    )
    assert response.status_code == 200

    test_session.expire_all()
    assert await _history(test_session, task_uuid) == []
    assert await _activities(test_session, task_uuid) == []
    assert await _db_status(test_session, task_uuid) == TaskStatus.TODO


@pytest.mark.asyncio
async def test_rejected_transition_writes_no_audit_rows(
    client: AsyncClient, test_session: AsyncSession
):
    """A 409 leaves the audit trail untouched (atomic rollback)."""
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_review"},  # todo -> in_review is illegal
        headers={"X-User-ID": actor_id},
    )
    assert response.status_code == 409

    test_session.expire_all()
    assert await _history(test_session, task_uuid) == []
    assert await _activities(test_session, task_uuid) == []
    assert await _db_status(test_session, task_uuid) == TaskStatus.TODO
