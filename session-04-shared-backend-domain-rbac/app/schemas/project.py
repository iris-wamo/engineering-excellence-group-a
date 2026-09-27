from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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
    owner_id: UUID


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
