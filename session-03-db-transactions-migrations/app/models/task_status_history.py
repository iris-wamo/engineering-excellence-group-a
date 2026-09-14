from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import UUID, DateTime, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.task import TaskStatus

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class TaskStatusHistory(Base):
    __tablename__ = "task_status_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task.id", ondelete="CASCADE"), nullable=False
    )
    previous_status: Mapped[TaskStatus | None] = mapped_column(
        Enum(TaskStatus), nullable=True
    )
    new_status: Mapped[TaskStatus] = mapped_column(Enum(TaskStatus), nullable=False)
    changed_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
    )

    # Relationships
    task: Mapped[Task] = relationship(
        "Task",
        back_populates="status_history",
    )
    changed_by: Mapped[User] = relationship(
        "User",
        foreign_keys=[changed_by_id],
    )

    def __repr__(self) -> str:
        return (
            f"<TaskStatusHistory(id={self.id}, task_id={self.task_id}, "
            f"new_status={self.new_status})>"
        )
