"""Unit tests for TaskService.update_task_status (the status service operation).

Locks in the Session 4 separation SLO:

    route  ->  service  ->  workflow (rules)  ->  repository (write)

Key guarantees asserted here:
1. The service is the orchestrator: retrieve -> authorize -> validate -> write.
2. The workflow is invoked BEFORE any repository write.
3. An invalid transition never touches the repository and surfaces as HTTP 409.
4. HTTP routes hold no transition business rules.
"""

import ast
import inspect
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.v1.routes import tasks as tasks_routes
from app.core.exceptions import (
    InvalidStatusTransitionError,
    StatusChangeForbiddenError,
    TaskNotFoundError,
)
from app.models.task import TaskStatus
from app.repositories.task_repository import TaskRepository
from app.schemas.task import TaskStatusUpdate, TaskStatusValue
from app.services import task_service
from app.services.task_service import TaskService
from app.workflows.task_status_workflow import TaskStatusWorkflow


def _fake_task(status: TaskStatus = TaskStatus.TODO) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        project_id=uuid.uuid4(),
        assigned_to=uuid.uuid4(),
    )


def _fake_db() -> SimpleNamespace:
    return SimpleNamespace(
        flush=AsyncMock(),
        commit=AsyncMock(),
        rollback=AsyncMock(),
        refresh=AsyncMock(),
    )


def _fake_actor() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role="user")


def _patch_context(monkeypatch, *, task, write_log: list[str]):
    """Patch repositories/workflow so we observe ordering without a real DB."""
    monkeypatch.setattr(
        task_service.TaskRepository, "get_by_id", AsyncMock(return_value=task)
    )
    monkeypatch.setattr(TaskService, "_ensure_can_change_status", AsyncMock())

    def _record_write(*_args, **_kwargs) -> None:
        write_log.append("write")

    monkeypatch.setattr(
        task_service.TaskRepository, "stage_update_status", _record_write
    )
    monkeypatch.setattr(
        task_service.TaskRepository, "add_status_history", _record_write
    )
    monkeypatch.setattr(
        task_service.ActivityLogRepository, "stage_create", _record_write
    )


@pytest.mark.asyncio
async def test_service_validates_transition_before_writing(monkeypatch):
    """Workflow validation must happen before the repository write."""
    order: list[str] = []
    task = _fake_task(TaskStatus.TODO)

    _patch_context(monkeypatch, task=task, write_log=order)

    def _spy_validate(cls, current, target):  # noqa: ARG001
        order.append("validate")

    monkeypatch.setattr(TaskStatusWorkflow, "validate", classmethod(_spy_validate))

    await TaskService.update_task_status(
        _fake_db(),
        task.id,
        TaskStatusUpdate(status=TaskStatusValue.IN_PROGRESS),
        actor=_fake_actor(),
    )

    assert order[0] == "validate", order
    assert "write" in order[1:], order


@pytest.mark.asyncio
async def test_service_skips_workflow_and_write_for_same_status(monkeypatch):
    """Re-sending the same status is a service-level no-op (idempotent)."""
    writes: list[str] = []
    task = _fake_task(TaskStatus.IN_PROGRESS)
    _patch_context(monkeypatch, task=task, write_log=writes)

    validated: list[str] = []
    monkeypatch.setattr(
        TaskStatusWorkflow,
        "validate",
        classmethod(lambda cls, c, t: validated.append("validate")),  # noqa: ARG005
    )

    result = await TaskService.update_task_status(
        _fake_db(),
        task.id,
        TaskStatusUpdate(status=TaskStatusValue.IN_PROGRESS),
        actor=_fake_actor(),
    )

    assert result is task
    assert writes == []
    assert validated == []


@pytest.mark.asyncio
async def test_service_rejects_invalid_transition_without_writing(monkeypatch):
    """todo -> done: workflow rejects, nothing is persisted, HTTP 409 surfaces."""
    writes: list[str] = []
    task = _fake_task(TaskStatus.TODO)
    _patch_context(monkeypatch, task=task, write_log=writes)
    db = _fake_db()

    with pytest.raises(InvalidStatusTransitionError) as exc_info:
        await TaskService.update_task_status(
            db,
            task.id,
            TaskStatusUpdate(status=TaskStatusValue.DONE),
            actor=_fake_actor(),
        )

    # Domain error was translated into a consistent HTTP 409
    err = exc_info.value
    assert err.status_code == 409
    assert err.detail["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert "TODO" in err.detail["error"]["message"]
    assert "DONE" in err.detail["error"]["message"]

    # No repository write, no commit
    assert writes == []
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_retrieves_task_and_raises_404_when_missing(monkeypatch):
    """Step 1 of the operation: retrieve the task."""
    get_by_id = AsyncMock(return_value=None)
    monkeypatch.setattr(task_service.TaskRepository, "get_by_id", get_by_id)
    monkeypatch.setattr(TaskService, "_ensure_can_change_status", AsyncMock())

    with pytest.raises(TaskNotFoundError):
        await TaskService.update_task_status(
            _fake_db(),
            uuid.uuid4(),
            TaskStatusUpdate(status=TaskStatusValue.IN_PROGRESS),
            actor=_fake_actor(),
        )

    get_by_id.assert_awaited_once()


@pytest.mark.asyncio
async def test_service_authorizes_before_validating(monkeypatch):
    """403 must be decided before workflow validation runs."""
    order: list[str] = []
    task = _fake_task(TaskStatus.TODO)
    monkeypatch.setattr(
        task_service.TaskRepository, "get_by_id", AsyncMock(return_value=task)
    )

    async def _deny(*_args, **_kwargs):
        order.append("authorize")
        raise StatusChangeForbiddenError()

    monkeypatch.setattr(TaskService, "_ensure_can_change_status", _deny)
    monkeypatch.setattr(
        TaskStatusWorkflow,
        "validate",
        classmethod(lambda cls, c, t: order.append("validate")),  # noqa: ARG005
    )

    with pytest.raises(StatusChangeForbiddenError):
        await TaskService.update_task_status(
            _fake_db(),
            task.id,
            TaskStatusUpdate(status=TaskStatusValue.IN_PROGRESS),
            actor=_fake_actor(),
        )

    assert order == ["authorize"]


def test_session3_transaction_pattern_is_reused():
    """Repository stages writes; the service owns the commit/rollback boundary."""
    stage_source = inspect.getsource(TaskRepository.stage_update_status)
    # No premature commit inside the repository layer (staged write only)
    assert "db.commit" not in stage_source

    service_source = inspect.getsource(TaskService.update_task_status)
    assert service_source.count("await db.commit()") == 1
    assert service_source.count("await db.rollback()") == 1
    assert "TaskRepository.stage_update_status(" in service_source


def test_route_contains_no_transition_business_rules():
    """Session 4 SLO: routes must not hold workflow logic."""
    source = inspect.getsource(tasks_routes)

    for forbidden in (
        "TaskStatusWorkflow",
        "InvalidTransitionError",
        "TRANSITIONS",
        "can_transition",
        "allowed_next",
        "is_terminal",
        "app.workflows",
    ):
        assert forbidden not in source, f"route leaked workflow detail: {forbidden}"


def test_status_route_is_request_response_only():
    """The route delegates to the service and returns a response DTO."""
    tree = ast.parse(inspect.getsource(tasks_routes.update_task_status))
    func = tree.body[0]
    body = [
        node
        for node in func.body
        if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    ]
    body_source = "\n".join(ast.unparse(node) for node in body)

    assert "TaskService.update_task_status(" in body_source
    assert "to_task_response(" in body_source
    # No business decisions / error handling in the route body itself
    assert "raise " not in body_source
    assert "if " not in body_source
    assert "try:" not in body_source
