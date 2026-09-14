from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity_log import ActivityLog


class ActivityLogRepository:
    """Repository handling database operations for the ActivityLog entity."""

    @staticmethod
    def stage_create(
        db: AsyncSession,
        *,
        task_id: UUID,
        actor_id: UUID,
        action: str,
        details: dict[str, Any] | None = None,
        created_at: datetime,
    ) -> ActivityLog:
        """Stage a new ActivityLog record in session without committing."""
        record = ActivityLog(
            task_id=task_id,
            actor_id=actor_id,
            action=action,
            details=details,
            created_at=created_at,
        )
        db.add(record)
        return record

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        task_id: UUID,
        actor_id: UUID,
        action: str,
        details: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> ActivityLog:
        """Create and commit a new ActivityLog record."""
        record = ActivityLog(
            task_id=task_id,
            actor_id=actor_id,
            action=action,
            details=details,
            created_at=created_at,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record

    @staticmethod
    async def get_by_id(db: AsyncSession, log_id: UUID) -> ActivityLog | None:
        """Fetch activity log by UUID primary key."""
        result = await db.execute(select(ActivityLog).where(ActivityLog.id == log_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_task_id(db: AsyncSession, task_id: UUID) -> list[ActivityLog]:
        """Fetch all activity logs for a given task, ordered chronologically descending."""
        stmt = (
            select(ActivityLog)
            .where(ActivityLog.task_id == task_id)
            .order_by(ActivityLog.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
