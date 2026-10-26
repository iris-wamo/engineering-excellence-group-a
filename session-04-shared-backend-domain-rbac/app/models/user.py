from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import UUID, CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.roles import UserRole
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.project_member import ProjectMember
    from app.models.task import Task


class User(Base):
    __tablename__ = "user"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'manager', 'member')", name="ck_user_role_valid"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=UserRole.MEMBER.value,
        server_default=UserRole.MEMBER.value,
    )

    # Relationships
    owned_projects: Mapped[list[Project]] = relationship(
        "Project",
        back_populates="owner",
        foreign_keys="Project.owner_id",
    )
    assigned_tasks: Mapped[list[Task]] = relationship(
        "Task",
        back_populates="assigned_to_user",
        foreign_keys="Task.assigned_to",
    )
    created_tasks: Mapped[list[Task]] = relationship(
        "Task",
        back_populates="created_by_user",
        foreign_keys="Task.assigned_by",
    )
    project_memberships: Mapped[list[ProjectMember]] = relationship(
        "ProjectMember",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, email={self.email})>"
