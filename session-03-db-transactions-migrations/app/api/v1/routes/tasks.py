from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies.deps import PaginationParams, SessionDep
from app.schemas.task import (
    ActivityLogResponse,
    NotificationResponse,
    TaskAssignmentHistoryResponse,
    TaskAssignRequest,
    TaskAssignResponse,
    TaskCreate,
    TaskListResponse,
    TaskPriorityValue,
    TaskResponse,
    TaskStatusHistoryResponse,
    TaskStatusUpdate,
    TaskStatusValue,
)
from app.services.task_service import (
    TaskService,
    to_activity_log_response,
    to_assignment_history_response,
    to_notification_response,
    to_status_history_response,
    to_task_assign_response,
    to_task_response,
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new task",
    description="Creates a task under a project. Validates project and optional assignee.",
)
async def create_task(
    payload: TaskCreate,
    db: SessionDep,
    response: Response,
) -> TaskResponse:
    """POST /tasks - Create a new task."""
    task = await TaskService.create_task(db, payload)
    response.headers["location"] = f"/tasks/{task.id}"
    return to_task_response(task)


@router.get(
    "",
    response_model=TaskListResponse,
    status_code=status.HTTP_200_OK,
    summary="List tasks",
    description="Paginated task list with optional status, priority, project, and assignee filters.",
)
async def list_tasks(
    db: SessionDep,
    pagination: PaginationParams = Depends(),
    status_filter: TaskStatusValue | None = Query(
        default=None,
        alias="status",
        description="Filter by status: todo | in_progress | done",
    ),
    priority: TaskPriorityValue | None = Query(
        default=None,
        description="Filter by priority: low | medium | high",
    ),
    project_id: UUID | None = Query(default=None, description="Filter by project"),
    assignee_id: UUID | None = Query(default=None, description="Filter by assignee"),
) -> TaskListResponse:
    """GET /tasks - Paginated and filtered task list."""
    tasks, total = await TaskService.get_tasks(
        db,
        page=pagination.page,
        page_size=pagination.page_size,
        status=status_filter,
        priority=priority,
        project_id=project_id,
        assignee_id=assignee_id,
    )
    return TaskListResponse(
        items=[to_task_response(t) for t in tasks],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Get task by ID",
    description="Fetch a single task by UUID. Returns 404 if missing.",
)
async def get_task(
    task_id: UUID,
    db: SessionDep,
) -> TaskResponse:
    """GET /tasks/{task_id} - Retrieve one task."""
    task = await TaskService.get_task(db, task_id)
    return to_task_response(task)


@router.patch(
    "/{task_id}/status",
    response_model=TaskResponse,
    status_code=status.HTTP_200_OK,
    summary="Update task status",
    description="Updates only the task status. Returns 404 if the task does not exist.",
)
async def update_task_status(
    task_id: UUID,
    payload: TaskStatusUpdate,
    db: SessionDep,
) -> TaskResponse:
    """PATCH /tasks/{task_id}/status - Update task status."""
    task = await TaskService.update_task_status(db, task_id, payload)
    return to_task_response(task)


@router.post(
    "/{task_id}/assign",
    response_model=TaskAssignResponse,
    status_code=status.HTTP_200_OK,
    summary="Atomically assign task",
    description=(
        "Executes a 5-step transaction-safe task assignment flow: updates assignee/status, "
        "records assignment history, records status history, writes an activity log, "
        "and creates a notification. If any step fails, the entire transaction rolls back."
    ),
)
async def assign_task(
    task_id: UUID,
    payload: TaskAssignRequest,
    db: SessionDep,
    simulate_failure: bool = Query(
        default=False,
        description="Simulate a mid-transaction failure for rollback testing",
    ),
    simulate_failure_step: int = Query(
        default=5,
        ge=1,
        le=5,
        description="Step at which to inject failure (1: task, 2: assign_hist, 3: status_hist, 4: activity, 5: notification)",
    ),
) -> TaskAssignResponse:
    """POST /tasks/{task_id}/assign - Transaction-safe task assignment."""
    (
        task,
        assignment_history,
        status_history,
        activity_log,
        notification,
    ) = await TaskService.assign_task(
        db,
        task_id,
        payload,
        simulate_failure=simulate_failure,
        simulate_failure_step=simulate_failure_step,
    )
    return to_task_assign_response(
        task,
        assignment_history,
        status_history,
        activity_log,
        notification,
    )


@router.get(
    "/{task_id}/history",
    response_model=dict[
        str, list[TaskAssignmentHistoryResponse] | list[TaskStatusHistoryResponse]
    ],
    status_code=status.HTTP_200_OK,
    summary="Get task assignment and status history",
    description="Fetches audit trail of all assignment and status changes for a task.",
)
async def get_task_history(
    task_id: UUID,
    db: SessionDep,
) -> dict[str, Any]:
    """GET /tasks/{task_id}/history - Task history."""
    assignments, statuses = await TaskService.get_task_history(db, task_id)
    return {
        "assignments": [to_assignment_history_response(a) for a in assignments],
        "statuses": [to_status_history_response(s) for s in statuses],
    }


@router.get(
    "/{task_id}/activity",
    response_model=list[ActivityLogResponse],
    status_code=status.HTTP_200_OK,
    summary="Get task activity logs",
    description="Fetches all activity audit logs for a task.",
)
async def get_task_activity(
    task_id: UUID,
    db: SessionDep,
) -> list[ActivityLogResponse]:
    """GET /tasks/{task_id}/activity - Task activity logs."""
    logs = await TaskService.get_task_activity(db, task_id)
    return [to_activity_log_response(log) for log in logs]


@router.get(
    "/{task_id}/notifications",
    response_model=list[NotificationResponse],
    status_code=status.HTTP_200_OK,
    summary="Get task notifications",
    description="Fetches all notifications generated for a task.",
)
async def get_task_notifications(
    task_id: UUID,
    db: SessionDep,
) -> list[NotificationResponse]:
    """GET /tasks/{task_id}/notifications - Task notifications."""
    notifications = await TaskService.get_task_notifications(db, task_id)
    return [to_notification_response(n) for n in notifications]
