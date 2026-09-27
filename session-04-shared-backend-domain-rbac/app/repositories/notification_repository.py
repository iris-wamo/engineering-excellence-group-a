from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


class NotificationRepository:
    """Repository handling database operations for the Notification entity."""

    @staticmethod
    def stage_create(
        db: AsyncSession,
        *,
        recipient_id: UUID,
        task_id: UUID,
        type: str,
        message: str,
        created_at: datetime,
        is_read: bool = False,
    ) -> Notification:
        """Stage a new Notification record in session without committing."""
        record = Notification(
            recipient_id=recipient_id,
            task_id=task_id,
            type=type,
            message=message,
            is_read=is_read,
            created_at=created_at,
        )
        db.add(record)
        return record

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        recipient_id: UUID,
        task_id: UUID,
        type: str,
        message: str,
        created_at: datetime | None = None,
        is_read: bool = False,
    ) -> Notification:
        """Create and commit a new Notification record."""
        record = Notification(
            recipient_id=recipient_id,
            task_id=task_id,
            type=type,
            message=message,
            is_read=is_read,
            created_at=created_at,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record

    @staticmethod
    async def get_by_id(db: AsyncSession, notification_id: UUID) -> Notification | None:
        """Fetch notification by UUID primary key."""
        result = await db.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_task_id(db: AsyncSession, task_id: UUID) -> list[Notification]:
        """Fetch all notifications related to a given task, ordered chronologically descending."""
        stmt = (
            select(Notification)
            .where(Notification.task_id == task_id)
            .order_by(Notification.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_recipient_id(
        db: AsyncSession, recipient_id: UUID
    ) -> list[Notification]:
        """Fetch all notifications for a given recipient user, ordered chronologically descending."""
        stmt = (
            select(Notification)
            .where(Notification.recipient_id == recipient_id)
            .order_by(Notification.created_at.desc())
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())
