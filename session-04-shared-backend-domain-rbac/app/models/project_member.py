from __future__ import annotations

from sqlalchemy import UUID, Column, ForeignKey, PrimaryKeyConstraint, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class ProjectMember(Base):
    __tablename__ = "project_member"

    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id = Column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), primary_key=True
    )
    member_role = Column(String(50), nullable=False, default="member")

    __table_args__ = (PrimaryKeyConstraint("project_id", "user_id"),)

    # Relationships
    project = relationship(
        "Project",
        back_populates="members",
    )
    user = relationship(
        "User",
        back_populates="project_memberships",
    )

    def __repr__(self) -> str:
        return f"<ProjectMember(project_id={self.project_id}, user_id={self.user_id}, role={self.member_role})>"
