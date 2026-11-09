"""Exercise due-date HTTP updates and real authorization with an isolated repository."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.deps import get_db
from app.auth.dependencies import get_current_user
from app.main import app
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository


@pytest_asyncio.fixture
async def due_date_client(monkeypatch):
    task = Task(
        id=uuid4(),
        project_id=uuid4(),
        title="Due-date update",
        priority=TaskPriority.MEDIUM,
        status=TaskStatus.TODO,
        due_date=datetime.now(UTC) + timedelta(days=1),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    actor = User(id=uuid4(), role="admin")
    get_task = AsyncMock(return_value=task)
    get_role = AsyncMock(return_value="manager")

    async def update(_db, row, **changes):
        for name, value in changes.items():
            setattr(row, name, value)
        return row

    write = AsyncMock(side_effect=update)
    monkeypatch.setattr(TaskRepository, "get_by_id", get_task)
    monkeypatch.setattr(TaskRepository, "update", write)
    monkeypatch.setattr(ProjectRepository, "get_member_role", get_role)
    original = app.dependency_overrides.copy()

    async def fake_db():
        yield None

    async def fake_user():
        return actor

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = fake_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, task, actor, get_task, get_role, write
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["set", "clear", "omit", "past"])
async def test_due_date_update_values(due_date_client, action):
    client, task, _actor, _get_task, _get_role, write = due_date_client
    previous = task.due_date
    target = datetime.now(UTC) + timedelta(days=-1 if action == "past" else 2)
    payload = (
        {}
        if action == "omit"
        else {"due_date": None if action == "clear" else target.isoformat()}
    )
    response = await client.patch(f"/tasks/{task.id}", json=payload)
    assert response.status_code == 200, response.text
    expected = previous if action == "omit" else None if action == "clear" else target
    assert task.due_date == expected
    value = response.json()["due_date"]
    assert (
        value is None if expected is None else datetime.fromisoformat(value) == expected
    )
    if action == "omit":
        write.assert_not_awaited()
    else:
        write.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("project_role", "expected_status"),
    [("manager", 200), ("member", 403), (None, 404)],
)
async def test_due_date_update_project_permissions(
    due_date_client, project_role, expected_status
):
    client, task, actor, _get_task, get_role, write = due_date_client
    actor.role = "member"
    get_role.return_value = project_role
    previous = task.due_date
    response = await client.patch(f"/tasks/{task.id}", json={"due_date": None})
    assert response.status_code == expected_status, response.text
    if expected_status != 200:
        write.assert_not_awaited()
        assert task.due_date == previous


@pytest.mark.asyncio
async def test_due_date_update_missing_task(due_date_client):
    client, task, _actor, get_task, _get_role, write = due_date_client
    get_task.return_value = None
    response = await client.patch(f"/tasks/{task.id}", json={"due_date": None})
    assert response.status_code == 404
    write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{"due_date": "2030-01-01T12:00:00"}, {"status": "done"}]
)
async def test_due_date_update_rejects_invalid_or_unrelated_fields(
    due_date_client, payload
):
    client, task, _actor, _get_task, _get_role, write = due_date_client
    response = await client.patch(f"/tasks/{task.id}", json=payload)
    assert response.status_code == 422
    write.assert_not_awaited()
