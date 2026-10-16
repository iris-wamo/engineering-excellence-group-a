from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.auth.roles import ProjectRole
from app.models.project import ProjectPriority, ProjectStatus


class ProjectCreate(BaseModel):
    """Request payload schema for creating a new project."""

    title: str = Field(..., min_length=1, max_length=255, description="Project title")
    description: str | None = Field(
        default=None, max_length=1000, description="Project description"
    )
    priority: ProjectPriority
    status: ProjectStatus = Field(default=ProjectStatus.ACTIVE)
    deadline: datetime | None = Field(default=None)
    owner_id: UUID | None = Field(
        default=None,
        description=(
            "Admin only: the manager who will own and manage the project. "
            "Managers always own the projects they create; omit it or pass "
            "your own id."
        ),
    )


class ProjectMemberAdd(BaseModel):
    """Payload for adding a user to a project (as member or manager)."""

    user_id: UUID


class ProjectMemberResponse(BaseModel):
    """A user's membership in a project."""

    user_id: UUID
    name: str
    username: str
    email: str
    role: ProjectRole


class ProjectResponse(BaseModel):
    """Response DTO schema for project details."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    priority: ProjectPriority
    status: ProjectStatus
    deadline: datetime | None
    owner_id: UUID


class ProjectListResponse(BaseModel):
    """Paginated list response wrapper for projects."""

    items: list[ProjectResponse]
    page: int = Field(..., ge=1, description="Current page number")
    page_size: int = Field(..., ge=1, le=100, description="Items per page")
    total: int = Field(..., ge=0, description="Total matching projects count")
