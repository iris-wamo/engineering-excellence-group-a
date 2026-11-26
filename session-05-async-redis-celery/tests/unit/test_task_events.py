"""Task domain events: emitted after commit, never on rollback."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.events import publisher
from app.events.publisher import TASK_EVENTS_CHANNEL, publish_task_event
from app.events.schemas import TaskEvent, TaskEventType
from app.models.task import TaskStatus
from app.schemas.task import TaskAssignRequest, TaskStatusUpdate, TaskStatusValue
from app.services import task_service
from app.services.task_service import TaskService


def _task(status: TaskStatus = TaskStatus.TODO) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        project_id=uuid.uuid4(),
        assigned_to=None,
        title="t",
    )


def _db(calls: list[str]) -> SimpleNamespace:
    async def commit():
        calls.append("commit")

    return SimpleNamespace(
        flush=AsyncMock(),
        commit=AsyncMock(side_effect=commit),
        rollback=AsyncMock(),
        refresh=AsyncMock(),
    )


def _actor() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role="admin", name="Ada")


@pytest.fixture
def events(monkeypatch):
    """Capture published events instead of sending them to Redis."""
    sent: list[TaskEvent] = []
    calls: list[str] = []

    async def fake_publish(event):
        calls.append("publish")
        sent.append(event)
        return True

    monkeypatch.setattr(task_service, "publish_task_event", fake_publish)
    return sent, calls


@pytest.fixture
def status_repos(monkeypatch):
    def patch(task):
        monkeypatch.setattr(
            task_service.TaskRepository, "get_by_id", AsyncMock(return_value=task)
        )
        monkeypatch.setattr(TaskService, "_ensure_can_change_status", AsyncMock())
        for owner, name in (
            (task_service.TaskRepository, "stage_update_status"),
            (task_service.TaskRepository, "add_status_history"),
            (task_service.ActivityLogRepository, "stage_create"),
        ):
            monkeypatch.setattr(owner, name, lambda *a, **k: None)  # noqa: ARG005

    return patch


@pytest.fixture
def assign_repos(monkeypatch):
    def patch(task):
        monkeypatch.setattr(
            task_service.TaskRepository, "get_by_id", AsyncMock(return_value=task)
        )
        monkeypatch.setattr(task_service, "require_project_manager", AsyncMock())
        monkeypatch.setattr(
            task_service,
            "_ensure_assignee_in_project",
            AsyncMock(return_value=SimpleNamespace(name="Bob")),
        )
        for owner, name in (
            (task_service.TaskRepository, "stage_task_assignment"),
            (task_service.TaskRepository, "add_assignment_history"),
            (task_service.TaskRepository, "add_status_history"),
            (task_service.ActivityLogRepository, "stage_create"),
            (task_service.NotificationRepository, "stage_create"),
        ):
            monkeypatch.setattr(owner, name, lambda *a, **k: object())  # noqa: ARG005

    return patch


@pytest.mark.asyncio
async def test_status_change_emits_event_after_commit(events, status_repos):
    sent, calls = events
    task, actor = _task(TaskStatus.TODO), _actor()
    status_repos(task)

    await TaskService.update_task_status(
        _db(calls), task.id, TaskStatusUpdate(status=TaskStatusValue.IN_PROGRESS), actor
    )

    assert calls == ["commit", "publish"]
    [event] = sent
    assert event.type == TaskEventType.STATUS_CHANGED
    assert (event.actor_id, event.task_id, event.project_id) == (
        actor.id,
        task.id,
        task.project_id,
    )
    assert event.data.from_status == "todo"
    assert event.data.to_status == "in_progress"
    assert event.data.assignee_id is None


@pytest.mark.asyncio
async def test_same_status_emits_nothing(events, status_repos):
    sent, calls = events
    task = _task(TaskStatus.IN_PROGRESS)
    status_repos(task)

    await TaskService.update_task_status(
        _db(calls),
        task.id,
        TaskStatusUpdate(status=TaskStatusValue.IN_PROGRESS),
        _actor(),
    )
    assert sent == []


@pytest.mark.asyncio
async def test_status_change_rollback_emits_nothing(events, status_repos):
    sent, calls = events
    task = _task(TaskStatus.TODO)
    status_repos(task)
    db = _db(calls)
    db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))

    with pytest.raises(RuntimeError):
        await TaskService.update_task_status(
            db, task.id, TaskStatusUpdate(status=TaskStatusValue.IN_PROGRESS), _actor()
        )
    db.rollback.assert_awaited_once()
    assert sent == []


@pytest.mark.asyncio
async def test_assign_emits_event_after_commit(events, assign_repos):
    sent, calls = events
    task, actor, assignee = _task(TaskStatus.TODO), _actor(), uuid.uuid4()
    assign_repos(task)

    await TaskService.assign_task(
        _db(calls), task.id, TaskAssignRequest(assignee_id=assignee), actor
    )

    assert calls == ["commit", "publish"]
    [event] = sent
    assert event.type == TaskEventType.ASSIGNED
    assert event.actor_id == actor.id
    assert event.task_id == task.id
    assert event.data.assignee_id == assignee
    assert event.data.from_status is None
    assert event.data.to_status is None


@pytest.mark.asyncio
async def test_assign_with_status_change_includes_statuses(events, assign_repos):
    sent, calls = events
    task = _task(TaskStatus.TODO)
    assign_repos(task)

    await TaskService.assign_task(
        _db(calls),
        task.id,
        TaskAssignRequest(
            assignee_id=uuid.uuid4(), new_status=TaskStatusValue.IN_PROGRESS
        ),
        _actor(),
    )
    [event] = sent
    assert (event.data.from_status, event.data.to_status) == ("todo", "in_progress")


@pytest.mark.asyncio
@pytest.mark.parametrize("step", [1, 2, 3, 4, 5])
async def test_assign_rollback_emits_nothing(events, assign_repos, step):
    sent, calls = events
    task = _task(TaskStatus.TODO)
    assign_repos(task)
    db = _db(calls)

    with pytest.raises(task_service.SimulatedAssignmentFailureError):
        await TaskService.assign_task(
            db,
            task.id,
            TaskAssignRequest(assignee_id=uuid.uuid4()),
            _actor(),
            simulate_failure=True,
            simulate_failure_step=step,
        )
    db.rollback.assert_awaited_once()
    assert calls == []
    assert sent == []


@pytest.mark.asyncio
async def test_publish_failure_does_not_fail_the_request(
    status_repos, monkeypatch, caplog
):
    broken = SimpleNamespace(publish=AsyncMock(side_effect=ConnectionError("down")))
    monkeypatch.setattr(publisher, "_redis", broken)
    task = _task(TaskStatus.TODO)
    status_repos(task)
    caplog.set_level(logging.WARNING, logger="taskflow.events")

    result = await TaskService.update_task_status(
        _db([]), task.id, TaskStatusUpdate(status=TaskStatusValue.IN_PROGRESS), _actor()
    )

    assert result is task
    assert "not published" in caplog.text


@pytest.mark.asyncio
async def test_publisher_sends_json_to_channel(monkeypatch):
    redis = SimpleNamespace(publish=AsyncMock())
    monkeypatch.setattr(publisher, "_redis", redis)
    event = TaskEvent(
        type=TaskEventType.ASSIGNED,
        actor_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )

    assert await publish_task_event(event) is True
    channel, payload = redis.publish.await_args.args
    assert channel == TASK_EVENTS_CHANNEL
    body = json.loads(payload)
    assert body["type"] == "task.assigned"
    assert body["version"] == 1
    assert body["event_id"] == str(event.event_id)
    assert set(body["data"]) == {"from_status", "to_status", "assignee_id"}


@pytest.mark.asyncio
async def test_publisher_without_redis_logs_and_returns_false(monkeypatch, caplog):
    monkeypatch.setattr(publisher, "_redis", None)
    caplog.set_level(logging.WARNING, logger="taskflow.events")
    event = TaskEvent(
        type=TaskEventType.STATUS_CHANGED,
        actor_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )
    assert await publish_task_event(event) is False
    assert "not published" in caplog.text


def test_event_defaults():
    ids = {
        "actor_id": uuid.uuid4(),
        "task_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
    }
    a = TaskEvent(type=TaskEventType.ASSIGNED, **ids)
    b = TaskEvent(type=TaskEventType.ASSIGNED, **ids)
    assert a.event_id != b.event_id
    assert a.version == 1
    assert a.occurred_at.tzinfo is UTC
    assert TaskEvent.model_validate_json(a.model_dump_json()) == a
