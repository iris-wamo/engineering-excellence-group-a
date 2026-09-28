from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    AssignedByNotFoundError,
    AssigneeNotFoundError,
    ProjectNotFoundError,
    SimulatedAssignmentFailureError,
    TaskNotFoundError,
)
from app.models.activity_log import ActivityLog
from app.models.notification import Notification
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.task_assignment_history import TaskAssignmentHistory
from app.models.task_status_history import TaskStatusHistory
from app.repositories.activity_log_repository import ActivityLogRepository
from app.repositories.notification_repository import NotificationRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.repositories.user_repository import UserRepository
from app.schemas.task import (
    ActivityLogResponse,
    NotificationResponse,
    TaskAssignmentHistoryResponse,
    TaskAssignRequest,
    TaskAssignResponse,
    TaskCreate,
    TaskPriorityValue,
    TaskResponse,
    TaskStatusHistoryResponse,
    TaskStatusUpdate,
    TaskStatusValue,
)

# API uses lowercase REST values; DB enums stay UPPERCASE (existing migrations).
_STATUS_TO_MODEL = {
    TaskStatusValue.TODO: TaskStatus.TODO,
    TaskStatusValue.IN_PROGRESS: TaskStatus.IN_PROGRESS,
    TaskStatusValue.DONE: TaskStatus.DONE,
}
_STATUS_TO_API = {v: k for k, v in _STATUS_TO_MODEL.items()}

_PRIORITY_TO_MODEL = {
    TaskPriorityValue.LOW: TaskPriority.LOW,
    TaskPriorityValue.MEDIUM: TaskPriority.MEDIUM,
    TaskPriorityValue.HIGH: TaskPriority.HIGH,
}
_PRIORITY_TO_API = {v: k for k, v in _PRIORITY_TO_MODEL.items()}


def to_task_response(task: Task) -> TaskResponse:
    """Map a Task ORM row to the public API response shape."""
    return TaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        priority=_PRIORITY_TO_API.get(task.priority, TaskPriorityValue.MEDIUM),
        status=_STATUS_TO_API.get(task.status, TaskStatusValue.TODO),
        project_id=task.project_id,
        assignee_id=task.assigned_to,
        estimated_time=task.estimated_time,
        deadline=task.deadline,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def to_assignment_history_response(
    history: TaskAssignmentHistory,
) -> TaskAssignmentHistoryResponse:
    """Map a TaskAssignmentHistory ORM row to API response shape."""
    return TaskAssignmentHistoryResponse(
        id=history.id,
        task_id=history.task_id,
        previous_assignee_id=history.previous_assignee_id,
        new_assignee_id=history.new_assignee_id,
        assigned_by_id=history.assigned_by_id,
        created_at=history.created_at,
    )


def to_status_history_response(
    history: TaskStatusHistory,
) -> TaskStatusHistoryResponse:
    """Map a TaskStatusHistory ORM row to API response shape."""
    return TaskStatusHistoryResponse(
        id=history.id,
        task_id=history.task_id,
        previous_status=_STATUS_TO_API.get(history.previous_status)
        if history.previous_status
        else None,
        new_status=_STATUS_TO_API.get(history.new_status, TaskStatusValue.TODO),
        changed_by_id=history.changed_by_id,
        created_at=history.created_at,
    )


def to_activity_log_response(activity: ActivityLog) -> ActivityLogResponse:
    """Map an ActivityLog ORM row to API response shape."""
    return ActivityLogResponse(
        id=activity.id,
        task_id=activity.task_id,
        actor_id=activity.actor_id,
        action=activity.action,
        details=activity.details,
        created_at=activity.created_at,
    )


def to_notification_response(notification: Notification) -> NotificationResponse:
    """Map a Notification ORM row to API response shape."""
    return NotificationResponse(
        id=notification.id,
        recipient_id=notification.recipient_id,
        task_id=notification.task_id,
        type=notification.type,
        message=notification.message,
        is_read=notification.is_read,
        created_at=notification.created_at,
    )


def to_task_assign_response(
    task: Task,
    assignment_history: TaskAssignmentHistory,
    status_history: TaskStatusHistory | None,
    activity_log: ActivityLog,
    notification: Notification,
) -> TaskAssignResponse:
    """Map all transaction-safe assignment entities to the composite response shape."""
    return TaskAssignResponse(
        task=to_task_response(task),
        assignment_history=to_assignment_history_response(assignment_history),
        status_history=to_status_history_response(status_history)
        if status_history
        else None,
        activity_log=to_activity_log_response(activity_log),
        notification=to_notification_response(notification),
        message="Task assigned successfully within atomic transaction boundary",
    )


class TaskService:
    """Business logic service layer for Task management."""

    @staticmethod
    async def create_task(db: AsyncSession, payload: TaskCreate) -> Task:
        """Create a new task after validating project and optional assignee."""
        project = await ProjectRepository.get_by_id(db, payload.project_id)
        if project is None:
            raise ProjectNotFoundError()

        if payload.assignee_id is not None:
            assignee = await UserRepository.get_by_id(db, payload.assignee_id)
            if assignee is None:
                raise AssigneeNotFoundError()

        # Strip timezone info to match DB column type (TIMESTAMP WITHOUT TIME ZONE)
        deadline = payload.deadline
        if deadline is not None and deadline.tzinfo is not None:
            deadline = deadline.replace(tzinfo=None)

        return await TaskRepository.create(
            db,
            title=payload.title,
            description=payload.description,
            priority=_PRIORITY_TO_MODEL[payload.priority],
            status=_STATUS_TO_MODEL[payload.status],
            project_id=payload.project_id,
            assigned_to=payload.assignee_id,
            estimated_time=payload.estimated_time,
            deadline=deadline,
        )

    @staticmethod
    async def get_tasks(
        db: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 10,
        status: TaskStatusValue | None = None,
        priority: TaskPriorityValue | None = None,
        project_id: UUID | None = None,
        assignee_id: UUID | None = None,
    ) -> tuple[list[Task], int]:
        """Fetch a paginated list of tasks with optional filters."""
        offset = (page - 1) * page_size
        return await TaskRepository.get_all(
            db,
            limit=page_size,
            offset=offset,
            status=_STATUS_TO_MODEL[status] if status else None,
            priority=_PRIORITY_TO_MODEL[priority] if priority else None,
            project_id=project_id,
            assigned_to=assignee_id,
        )

    @staticmethod
    async def get_task(db: AsyncSession, task_id: UUID) -> Task:
        """Fetch a task by UUID or raise TaskNotFoundError."""
        task = await TaskRepository.get_by_id(db, task_id)
        if task is None:
            raise TaskNotFoundError()
        return task

    @staticmethod
    async def update_task_status(
        db: AsyncSession,
        task_id: UUID,
        payload: TaskStatusUpdate,
        changed_by_id: UUID | None = None,
    ) -> Task:
        """Update task status and atomically record TaskStatusHistory and ActivityLog.

        If changed_by_id is provided or task has assigned_by/assigned_to, the actor is recorded.
        The operations run within a single transaction boundary to ensure audit trail consistency.
        """
        task = await TaskRepository.get_by_id(db, task_id)
        if task is None:
            raise TaskNotFoundError()

        target_status = _STATUS_TO_MODEL[payload.status]
        prev_status = task.status

        # If status did not change, return early without recording audit history
        if target_status == prev_status:
            return task

        now = datetime.now(UTC).replace(tzinfo=None)
        actor_id = changed_by_id or task.assigned_by or task.assigned_to

        try:
            # 1. Stage task status update
            TaskRepository.stage_update_status(db, task, target_status)

            # 2. Record status history if actor is identifiable
            if actor_id:
                TaskRepository.add_status_history(
                    db,
                    task_id=task.id,
                    previous_status=prev_status,
                    new_status=target_status,
                    changed_by_id=actor_id,
                    created_at=now,
                )

                # 3. Record activity log
                ActivityLogRepository.stage_create(
                    db,
                    task_id=task.id,
                    actor_id=actor_id,
                    action="task.status_changed",
                    details={
                        "previous_status": prev_status.value,
                        "new_status": target_status.value,
                    },
                    created_at=now,
                )

            await db.commit()
            await db.refresh(task)
            return task
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def assign_task(
        db: AsyncSession,
        task_id: UUID,
        payload: TaskAssignRequest,
        *,
        simulate_failure: bool = False,
        simulate_failure_step: int = 5,
    ) -> tuple[
        Task,
        TaskAssignmentHistory,
        TaskStatusHistory | None,
        ActivityLog,
        Notification,
    ]:
        """Execute a 5-step atomic task assignment within a single transaction boundary.

        Steps performed atomically:
        1. Update task assignee and optional new status.
        2. Insert TaskAssignmentHistory (records previous -> new assignee).
        3. Insert TaskStatusHistory (if status transition occurred).
        4. Insert ActivityLog (records actor, action, and JSON audit details).
        5. Insert Notification (alerts the new assignee).

        Database write operations are delegated to the Repository layer.
        The Service layer controls the transaction boundary (commit/rollback).
        If any error occurs or simulate_failure is enabled, the transaction is rolled back,
        ensuring zero partial writes.
        """
        task = await TaskRepository.get_by_id(db, task_id)
        if task is None:
            raise TaskNotFoundError()

        new_assignee = await UserRepository.get_by_id(db, payload.assignee_id)
        if new_assignee is None:
            raise AssigneeNotFoundError()

        assigned_by_user = await UserRepository.get_by_id(db, payload.assigned_by_id)
        if assigned_by_user is None:
            raise AssignedByNotFoundError()

        now = datetime.now(UTC).replace(tzinfo=None)
        prev_assignee_id = task.assigned_to
        prev_status = task.status
        target_status = (
            _STATUS_TO_MODEL[payload.new_status] if payload.new_status else prev_status
        )
        status_changed = target_status != prev_status

        try:
            # Step 1: Stage task assignee/status update via Repository
            TaskRepository.stage_task_assignment(
                db,
                task,
                assignee_id=payload.assignee_id,
                assigned_by_id=payload.assigned_by_id,
                new_status=target_status if status_changed else None,
                now=now,
            )

            if simulate_failure and simulate_failure_step == 1:
                raise SimulatedAssignmentFailureError(
                    "Simulated failure at Step 1 (Task Update)"
                )

            # Step 2: Stage assignment history record via Repository
            assignment_history = TaskRepository.add_assignment_history(
                db,
                task_id=task.id,
                previous_assignee_id=prev_assignee_id,
                new_assignee_id=payload.assignee_id,
                assigned_by_id=payload.assigned_by_id,
                created_at=now,
            )

            if simulate_failure and simulate_failure_step == 2:
                raise SimulatedAssignmentFailureError(
                    "Simulated failure at Step 2 (Assignment History)"
                )

            # Step 3: Stage status history record via Repository (if status changed)
            status_history: TaskStatusHistory | None = None
            if status_changed:
                status_history = TaskRepository.add_status_history(
                    db,
                    task_id=task.id,
                    previous_status=prev_status,
                    new_status=target_status,
                    changed_by_id=payload.assigned_by_id,
                    created_at=now,
                )

            if simulate_failure and simulate_failure_step == 3:
                raise SimulatedAssignmentFailureError(
                    "Simulated failure at Step 3 (Status History)"
                )

            # Step 4: Stage activity log record via Repository
            activity_details: dict[str, Any] = {
                "previous_assignee_id": str(prev_assignee_id)
                if prev_assignee_id
                else None,
                "new_assignee_id": str(payload.assignee_id),
                "assigned_by_name": assigned_by_user.name,
                "new_assignee_name": new_assignee.name,
            }
            if payload.comment:
                activity_details["comment"] = payload.comment
            if status_changed:
                activity_details["status_transition"] = (
                    f"{prev_status.value} -> {target_status.value}"
                )

            activity_log = ActivityLogRepository.stage_create(
                db,
                task_id=task.id,
                actor_id=payload.assigned_by_id,
                action="task.assigned",
                details=activity_details,
                created_at=now,
            )

            if simulate_failure and simulate_failure_step == 4:
                raise SimulatedAssignmentFailureError(
                    "Simulated failure at Step 4 (Activity Log)"
                )

            # Step 5: Stage notification record via NotificationRepository
            notification = NotificationRepository.stage_create(
                db,
                recipient_id=payload.assignee_id,
                task_id=task.id,
                type="task_assignment",
                message=f"You have been assigned to task '{task.title}' by {assigned_by_user.name}.",
                created_at=now,
            )

            if simulate_failure and simulate_failure_step == 5:
                raise SimulatedAssignmentFailureError(
                    "Simulated failure at Step 5 (Notification Dispatch)"
                )

            # Atomically commit all staged records in transaction boundary
            await db.commit()
            await db.refresh(task)
            await db.refresh(assignment_history)
            if status_history:
                await db.refresh(status_history)
            await db.refresh(activity_log)
            await db.refresh(notification)

            return (
                task,
                assignment_history,
                status_history,
                activity_log,
                notification,
            )

        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def get_task_history(
        db: AsyncSession, task_id: UUID
    ) -> tuple[list[TaskAssignmentHistory], list[TaskStatusHistory]]:
        """Retrieve full assignment and status history for a task."""
        task = await TaskRepository.get_by_id(db, task_id)
        if task is None:
            raise TaskNotFoundError()

        assignments = await TaskRepository.get_assignment_history(db, task_id)
        statuses = await TaskRepository.get_status_history(db, task_id)
        return assignments, statuses

    @staticmethod
    async def get_task_activity(db: AsyncSession, task_id: UUID) -> list[ActivityLog]:
        """Retrieve all activity logs for a task."""
        task = await TaskRepository.get_by_id(db, task_id)
        if task is None:
            raise TaskNotFoundError()

        return await ActivityLogRepository.get_by_task_id(db, task_id)

    @staticmethod
    async def get_task_notifications(
        db: AsyncSession, task_id: UUID
    ) -> list[Notification]:
        """Retrieve all notifications for a task."""
        task = await TaskRepository.get_by_id(db, task_id)
        if task is None:
            raise TaskNotFoundError()

        return await NotificationRepository.get_by_task_id(db, task_id)
