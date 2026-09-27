from __future__ import annotations

import uuid

from sqlalchemy import UUID, Column, String
from sqlalchemy.orm import relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "user"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    username = Column(String(255), nullable=False, unique=True)
    email = Column(String(255), nullable=False, unique=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="user")

    # Relationships
    owned_projects = relationship(
        "Project",
        back_populates="owner",
        foreign_keys="Project.owner_id",
    )
    assigned_tasks = relationship(
        "Task",
        back_populates="assigned_to_user",
        foreign_keys="Task.assigned_to",
    )
    created_tasks = relationship(
        "Task",
        back_populates="created_by_user",
        foreign_keys="Task.assigned_by",
    )
    project_memberships = relationship(
        "ProjectMember",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, email={self.email})>"
