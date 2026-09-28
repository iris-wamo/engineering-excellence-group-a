from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import UUID, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class TaskAssignmentHistory(Base):
    __tablename__ = "task_assignment_history"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task.id", ondelete="CASCADE"), nullable=False
    )
    previous_assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    new_assignee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    assigned_by_id: Mapped[uuid.UUID] = mapped_column(
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
        back_populates="assignment_history",
    )
    previous_assignee: Mapped[User | None] = relationship(
        "User",
        foreign_keys=[previous_assignee_id],
    )
    new_assignee: Mapped[User] = relationship(
        "User",
        foreign_keys=[new_assignee_id],
    )
    assigned_by: Mapped[User] = relationship(
        "User",
        foreign_keys=[assigned_by_id],
    )

    def __repr__(self) -> str:
        return (
            f"<TaskAssignmentHistory(id={self.id}, task_id={self.task_id}, "
            f"new_assignee_id={self.new_assignee_id})>"
        )
