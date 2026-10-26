from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    UUID,
    CheckConstraint,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.auth.roles import ProjectRole
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


class ProjectMember(Base):
    __tablename__ = "project_member"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    member_role: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ProjectRole.MEMBER.value,
        server_default=ProjectRole.MEMBER.value,
    )

    __table_args__ = (
        PrimaryKeyConstraint("project_id", "user_id"),
        CheckConstraint(
            "member_role IN ('manager', 'member')",
            name="ck_project_member_role_valid",
        ),
        # "Which projects is this user in?" runs on every authorised request.
        Index("ix_project_member_user_id", "user_id"),
    )

    # Relationships
    project: Mapped[Project] = relationship(
        "Project",
        back_populates="members",
    )
    user: Mapped[User] = relationship(
        "User",
        back_populates="project_memberships",
    )

    def __repr__(self) -> str:
        return f"<ProjectMember(project_id={self.project_id}, user_id={self.user_id}, role={self.member_role})>"
