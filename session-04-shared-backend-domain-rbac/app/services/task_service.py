from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import (
    is_admin,
    require_project_access,
    require_project_manager,
)
from app.core.exceptions import (
    AssigneeNotFoundError,
    AssigneeNotInProjectError,
    ForbiddenError,
    ProjectNotFoundError,
    SimulatedAssignmentFailureError,
    StatusChangeForbiddenError,
    TaskNotFoundError,
)
from app.models.activity_log import ActivityLog
from app.models.notification import Notification
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.task_assignment_history import TaskAssignmentHistory
from app.models.task_status_history import TaskStatusHistory
from app.models.user import User
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
from app.workflows.task_status_workflow import TaskStatusWorkflow

# API uses lowercase REST values; DB enums stay UPPERCASE (existing migrations).
_STATUS_TO_MODEL = {
    TaskStatusValue.TODO: TaskStatus.TODO,
    TaskStatusValue.IN_PROGRESS: TaskStatus.IN_PROGRESS,
    TaskStatusValue.IN_REVIEW: TaskStatus.IN_REVIEW,
    TaskStatusValue.DONE: TaskStatus.DONE,
    TaskStatusValue.CANCELLED: TaskStatus.CANCELLED,
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


async def _ensure_assignee_in_project(
    db: AsyncSession, project_id: UUID, assignee_id: UUID
) -> User:
    """The assignee must exist (404) and belong to the task's project (422)."""
    assignee = await UserRepository.get_by_id(db, assignee_id)
    if assignee is None:
        raise AssigneeNotFoundError()
    if await ProjectRepository.get_member_role(db, project_id, assignee_id) is None:
        raise AssigneeNotInProjectError()
    return assignee


class TaskService:
    """Business logic service layer for Task management."""

    @staticmethod
    async def create_task(db: AsyncSession, payload: TaskCreate, actor: User) -> Task:
        """Create a new task after validating project and optional assignee.

        Admins and project managers may assign the task to any project member.
        Members may create tasks only for themselves: the task is assigned to
        them, and naming another assignee is forbidden (403). Like the status
        endpoint, members cannot create a task as ``cancelled`` (403).
        """
        access = await require_project_access(
            db, payload.project_id, actor, not_found=ProjectNotFoundError()
        )
        project = await ProjectRepository.get_by_id(db, payload.project_id)
        if project is None:
            raise ProjectNotFoundError()

        assignee_id = payload.assignee_id
        if not access.can_manage:
            if assignee_id is not None and assignee_id != actor.id:
                raise ForbiddenError(
                    "Members can only create tasks assigned to themselves"
                )
            if payload.status == TaskStatusValue.CANCELLED:
                raise StatusChangeForbiddenError()
            assignee_id = actor.id

        if assignee_id is not None:
            await _ensure_assignee_in_project(db, payload.project_id, assignee_id)

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
            assigned_to=assignee_id,
            assigned_by=actor.id if assignee_id is not None else None,
            estimated_time=payload.estimated_time,
            deadline=deadline,
        )

    @staticmethod
    async def get_tasks(
        db: AsyncSession,
        actor: User,
        *,
        page: int = 1,
        page_size: int = 10,
        status: TaskStatusValue | None = None,
        priority: TaskPriorityValue | None = None,
        project_id: UUID | None = None,
        assignee_id: UUID | None = None,
    ) -> tuple[list[Task], int]:
        """Fetch tasks; non-admins only see tasks in projects they belong to."""
        offset = (page - 1) * page_size
        return await TaskRepository.get_all(
            db,
            limit=page_size,
            offset=offset,
            member_user_id=None if is_admin(actor) else actor.id,
            status=_STATUS_TO_MODEL[status] if status else None,
            priority=_PRIORITY_TO_MODEL[priority] if priority else None,
            project_id=project_id,
            assigned_to=assignee_id,
        )

    @staticmethod
    async def get_task(db: AsyncSession, task_id: UUID, actor: User) -> Task:
        """Fetch a task in a project the actor belongs to, else TaskNotFoundError."""
        task = await TaskRepository.get_by_id(db, task_id)
        if task is None:
            raise TaskNotFoundError()
        await require_project_access(
            db, task.project_id, actor, not_found=TaskNotFoundError()
        )
        return task

    @staticmethod
    async def _ensure_can_change_status(
        db: AsyncSession, task: Task, actor: User, target_status: TaskStatus
    ) -> None:
        """Enforce the RBAC rule for status changes.

        - Outside the task's project (and not admin): 404, as if it did not exist.
        - Admins and managers of the project: any status change.
        - Members: only on tasks assigned to them, and never to ``cancelled``.
        Anyone else in the project gets 403.
        """
        access = await require_project_access(
            db, task.project_id, actor, not_found=TaskNotFoundError()
        )
        if access.can_manage:
            return
        if task.assigned_to == actor.id and target_status != TaskStatus.CANCELLED:
            return

        raise StatusChangeForbiddenError()

    @staticmethod
    async def update_task_status(
        db: AsyncSession,
        task_id: UUID,
        payload: TaskStatusUpdate,
        actor: User,
    ) -> Task:
        """Update task status and atomically record TaskStatusHistory and ActivityLog.

        Authorization (assignee/project manager/admin) is enforced before
        any write. Invalid workflow transitions raise the domain
        InvalidTransitionError for the API layer to translate. The audit trail
        always records the acting user.

        Transaction safety (Session 3 pattern): the status update, the history
        record, and the activity log are staged on one session and committed
        exactly once. Any failure rolls all of them back, so a failed
        transition can never leave partial state behind.
        """
        task = await TaskRepository.get_by_id(db, task_id)
        if task is None:
            raise TaskNotFoundError()

        target_status = _STATUS_TO_MODEL[payload.status]
        await TaskService._ensure_can_change_status(db, task, actor, target_status)

        prev_status = task.status

        # If status did not change, return early without recording audit history
        if target_status == prev_status:
            return task

        # Business rule lives in the workflow; API layer translates domain errors.
        TaskStatusWorkflow.validate(prev_status, target_status)

        now = datetime.now(UTC).replace(tzinfo=None)
        actor_id = actor.id

        # ---- Single transaction boundary ---------------------------------
        # Everything below commits together or not at all.
        try:
            # 1. Task status update (staged, not committed)
            TaskRepository.stage_update_status(db, task, target_status)

            # 2. Status history (staged, not committed)
            TaskRepository.add_status_history(
                db,
                task_id=task.id,
                previous_status=prev_status,
                new_status=target_status,
                changed_by_id=actor_id,
                created_at=now,
            )

            # 3. Activity log (staged, not committed)
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

            # Surface any DB-level error before COMMIT so it is rolled back
            await db.flush()

            # All three writes succeeded -> COMMIT atomically
            await db.commit()
        except Exception:
            # Any failure (validation-agnostic writes, flush, commit) -> undo all
            await db.rollback()
            raise

        # Transaction already committed: load the persisted row
        await db.refresh(task)
        return task

    @staticmethod
    async def assign_task(
        db: AsyncSession,
        task_id: UUID,
        payload: TaskAssignRequest,
        actor: User,
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

        Authorization: only a manager of the task's project or an admin may
        assign (members 403, outsiders 404). The assignee must belong to the
        project, and the acting user is recorded as the assigner.
        """
        task = await TaskRepository.get_by_id(db, task_id)
        if task is None:
            raise TaskNotFoundError()

        await require_project_manager(
            db,
            task.project_id,
            actor,
            not_found=TaskNotFoundError(),
            message="Only a manager of this project or an admin can assign tasks",
        )

        new_assignee = await _ensure_assignee_in_project(
            db, task.project_id, payload.assignee_id
        )
        assigned_by_user = actor

        now = datetime.now(UTC).replace(tzinfo=None)
        prev_assignee_id = task.assigned_to
        prev_status = task.status
        target_status = (
            _STATUS_TO_MODEL[payload.new_status] if payload.new_status else prev_status
        )
        status_changed = target_status != prev_status

        # Same workflow engine as PATCH /tasks/{id}/status; API translates domain errors.
        if status_changed:
            TaskStatusWorkflow.validate(prev_status, target_status)

        try:
            # Step 1: Stage task assignee/status update via Repository
            TaskRepository.stage_task_assignment(
                db,
                task,
                assignee_id=payload.assignee_id,
                assigned_by_id=assigned_by_user.id,
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
                assigned_by_id=assigned_by_user.id,
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
                    changed_by_id=assigned_by_user.id,
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
                actor_id=assigned_by_user.id,
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
        db: AsyncSession, task_id: UUID, actor: User
    ) -> tuple[list[TaskAssignmentHistory], list[TaskStatusHistory]]:
        """Retrieve full assignment and status history for a task."""
        await TaskService.get_task(db, task_id, actor)

        assignments = await TaskRepository.get_assignment_history(db, task_id)
        statuses = await TaskRepository.get_status_history(db, task_id)
        return assignments, statuses

    @staticmethod
    async def get_task_activity(
        db: AsyncSession, task_id: UUID, actor: User
    ) -> list[ActivityLog]:
        """Retrieve all activity logs for a task."""
        await TaskService.get_task(db, task_id, actor)

        return await ActivityLogRepository.get_by_task_id(db, task_id)

    @staticmethod
    async def get_task_notifications(
        db: AsyncSession, task_id: UUID, actor: User
    ) -> list[Notification]:
        """Retrieve all notifications for a task."""
        await TaskService.get_task(db, task_id, actor)

        return await NotificationRepository.get_by_task_id(db, task_id)
