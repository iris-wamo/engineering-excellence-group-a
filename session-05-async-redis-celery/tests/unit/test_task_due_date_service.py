"""Check that due dates cross service boundaries without losing timezone data."""

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.models.task import Task, TaskPriority, TaskStatus
from app.schemas.task import TaskCreate
from app.services import task_service
from app.services.task_service import TaskService, to_task_response


@pytest.mark.asyncio
@pytest.mark.parametrize("has_due_date", [False, True])
async def test_create_forwards_due_date_to_repository(monkeypatch, has_due_date):
    due_date = (
        (datetime.now(UTC) + timedelta(days=1)).astimezone(timezone(timedelta(hours=5)))
        if has_due_date
        else None
    )
    payload = TaskCreate(
        title="Due-date service test", project_id=uuid4(), due_date=due_date
    )
    monkeypatch.setattr(
        task_service,
        "require_project_access",
        AsyncMock(return_value=SimpleNamespace(can_manage=True)),
    )
    monkeypatch.setattr(
        task_service.ProjectRepository,
        "get_by_id",
        AsyncMock(return_value=SimpleNamespace(id=payload.project_id)),
    )
    create = AsyncMock(return_value=Task(due_date=due_date))
    monkeypatch.setattr(task_service.TaskRepository, "create", create)

    result = await TaskService.create_task(
        AsyncMock(), payload, actor=SimpleNamespace(id=uuid4())
    )

    assert create.await_count == 1
    assert create.await_args.kwargs["due_date"] is payload.due_date
    assert result.due_date == due_date


@pytest.mark.parametrize("has_due_date", [False, True])
def test_response_mapper_includes_stored_due_date(has_due_date):
    # Overdue tasks must remain readable; only creation rejects past due dates.
    due_date = datetime.now(UTC) - timedelta(days=1) if has_due_date else None
    task = Task(
        id=uuid4(),
        title="Stored task",
        description=None,
        priority=TaskPriority.MEDIUM,
        status=TaskStatus.TODO,
        project_id=uuid4(),
        assigned_to=None,
        estimated_time=None,
        deadline=None,
        due_date=due_date,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    response = to_task_response(task)

    assert response.due_date == due_date
    assert "due_date" in response.model_dump(mode="json")
    if due_date is None:
        assert response.model_dump(mode="json")["due_date"] is None
