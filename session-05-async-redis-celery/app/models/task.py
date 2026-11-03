from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import UUID, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.activity_log import ActivityLog
    from app.models.notification import Notification
    from app.models.project import Project
    from app.models.task_assignment_history import TaskAssignmentHistory
    from app.models.task_status_history import TaskStatusHistory
    from app.models.user import User


class TaskStatus(enum.StrEnum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    IN_REVIEW = "IN_REVIEW"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class TaskPriority(enum.StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"


class Task(Base):
    __tablename__ = "task"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project.id", ondelete="CASCADE")
    )
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority), nullable=False, default=TaskPriority.MEDIUM
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus), nullable=False, default=TaskStatus.TODO
    )
    estimated_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
    )

    # Relationships
    project: Mapped[Project] = relationship(
        "Project",
        back_populates="tasks",
    )
    assigned_to_user: Mapped[User | None] = relationship(
        "User",
        back_populates="assigned_tasks",
        foreign_keys=[assigned_to],
    )

    created_by_user: Mapped[User | None] = relationship(
        "User",
        back_populates="created_tasks",
        foreign_keys=[assigned_by],
    )
    assignment_history: Mapped[list[TaskAssignmentHistory]] = relationship(
        "TaskAssignmentHistory",
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    status_history: Mapped[list[TaskStatusHistory]] = relationship(
        "TaskStatusHistory",
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    activity_logs: Mapped[list[ActivityLog]] = relationship(
        "ActivityLog",
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notifications: Mapped[list[Notification]] = relationship(
        "Notification",
        back_populates="task",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Task(id={self.id}, title={self.title}, status={self.status})>"
