from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus
from app.models.task_assignment_history import TaskAssignmentHistory
from app.models.task_status_history import TaskStatusHistory


class TaskRepository:
    """Repository handling database operations for Task and task-history entities."""

    @staticmethod
    async def get_by_id(db: AsyncSession, task_id: UUID) -> Task | None:
        """Fetch task by UUID primary key."""
        result = await db.execute(select(Task).where(Task.id == task_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(
        db: AsyncSession,
        *,
        limit: int = 10,
        offset: int = 0,
        **filters,
    ) -> tuple[list[Task], int]:
        """Fetch paginated list of tasks with optional dynamic filters."""
        query = select(Task)

        for key, value in filters.items():
            if value is not None and hasattr(Task, key):
                query = query.where(getattr(Task, key) == value)

        count_query = select(func.count()).select_from(query.subquery())
        total = (await db.execute(count_query)).scalar_one()

        result = await db.execute(query.offset(offset).limit(limit))
        tasks = list(result.scalars().all())
        return tasks, total

    @staticmethod
    async def create(db: AsyncSession, **kwargs) -> Task:
        """Create and persist a new task entity in the database."""
        task = Task(**kwargs)
        db.add(task)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def update(db: AsyncSession, task: Task, **kwargs) -> Task:
        """Update any attributes on an existing task entity dynamically."""
        for key, value in kwargs.items():
            if hasattr(task, key):
                setattr(task, key, value)
        await db.commit()
        await db.refresh(task)
        return task

    @staticmethod
    async def update_status(
        db: AsyncSession,
        task: Task,
        status: TaskStatus,
    ) -> Task:
        """Update status on an existing task (wraps generic update)."""
        return await TaskRepository.update(db, task, status=status)

    @staticmethod
    def stage_update_status(
        db: AsyncSession,
        task: Task,
        status: TaskStatus,
    ) -> None:
        """Stage status update on an existing task without committing."""
        task.status = status
        db.add(task)

    # ------------------------------------------------------------------
    # Write operations for transaction-safe assignment (staged, no commit)
    # ------------------------------------------------------------------

    @staticmethod
    def stage_task_assignment(
        db: AsyncSession,
        task: Task,
        *,
        assignee_id: UUID,
        assigned_by_id: UUID,
        new_status: TaskStatus | None,
        now: datetime,
    ) -> None:
        """Stage task assignee/status update in the current session (no commit)."""
        task.assigned_to = assignee_id
        task.assigned_by = assigned_by_id
        if new_status is not None and new_status != task.status:
            task.status = new_status
        task.updated_at = now
        db.add(task)

    @staticmethod
    def add_assignment_history(
        db: AsyncSession,
        *,
        task_id: UUID,
        previous_assignee_id: UUID | None,
        new_assignee_id: UUID,
        assigned_by_id: UUID,
        created_at: datetime,
    ) -> TaskAssignmentHistory:
        """Stage a new TaskAssignmentHistory record (no commit)."""
        record = TaskAssignmentHistory(
            task_id=task_id,
            previous_assignee_id=previous_assignee_id,
            new_assignee_id=new_assignee_id,
            assigned_by_id=assigned_by_id,
            created_at=created_at,
        )
        db.add(record)
        return record

    @staticmethod
    def add_status_history(
        db: AsyncSession,
        *,
        task_id: UUID,
        previous_status: TaskStatus,
        new_status: TaskStatus,
        changed_by_id: UUID,
        created_at: datetime,
    ) -> TaskStatusHistory:
        """Stage a new TaskStatusHistory record (no commit)."""
        record = TaskStatusHistory(
            task_id=task_id,
            previous_status=previous_status,
            new_status=new_status,
            changed_by_id=changed_by_id,
            created_at=created_at,
        )
        db.add(record)
        return record

    # ------------------------------------------------------------------
    # Read operations for assignment audit trail
    # ------------------------------------------------------------------

    @staticmethod
    async def get_assignment_history(
        db: AsyncSession, task_id: UUID
    ) -> list[TaskAssignmentHistory]:
        """Fetch all assignment history entries for a given task, ordered chronologically."""
        stmt = (
            select(TaskAssignmentHistory)
            .where(TaskAssignmentHistory.task_id == task_id)
            .order_by(TaskAssignmentHistory.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_status_history(
        db: AsyncSession, task_id: UUID
    ) -> list[TaskStatusHistory]:
        """Fetch all status history entries for a given task, ordered chronologically."""
        stmt = (
            select(TaskStatusHistory)
            .where(TaskStatusHistory.task_id == task_id)
            .order_by(TaskStatusHistory.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
