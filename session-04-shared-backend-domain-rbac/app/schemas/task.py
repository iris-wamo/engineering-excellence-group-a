from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskStatusValue(enum.StrEnum):
    """API-facing task statuses (lowercase REST values)."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class TaskPriorityValue(enum.StrEnum):
    """API-facing task priorities (lowercase REST values)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskCreate(BaseModel):
    """Request payload for creating a new task."""

    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    priority: TaskPriorityValue = Field(default=TaskPriorityValue.MEDIUM)
    status: TaskStatusValue = Field(default=TaskStatusValue.TODO)
    project_id: UUID = Field(..., description="Project this task belongs to")
    assignee_id: UUID | None = Field(
        default=None,
        description="User assigned to this task",
    )
    estimated_time: int | None = Field(
        default=None,
        ge=0,
        description="Estimated effort in hours",
    )
    deadline: datetime | None = None


class TaskStatusUpdate(BaseModel):
    """Request payload for updating only a task's status."""

    status: TaskStatusValue


class TaskResponse(BaseModel):
    """Response DTO for a single task."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str | None
    priority: TaskPriorityValue
    status: TaskStatusValue
    project_id: UUID | None
    assignee_id: UUID | None
    estimated_time: int | None
    deadline: datetime | None
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    """Paginated list response for tasks."""

    items: list[TaskResponse]
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    total: int = Field(..., ge=0)


class TaskAssignRequest(BaseModel):
    """Request payload for assigning a task to a user atomically."""

    assignee_id: UUID = Field(
        ..., description="UUID of the user being assigned to the task"
    )
    assigned_by_id: UUID = Field(
        ..., description="UUID of the user performing the assignment"
    )
    new_status: TaskStatusValue | None = Field(
        default=None,
        description="Optional status to transition task to (e.g. in_progress)",
    )
    comment: str | None = Field(
        default=None,
        max_length=500,
        description="Optional note/comment recorded in activity log",
    )


class TaskAssignmentHistoryResponse(BaseModel):
    """DTO for a single task assignment history record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    previous_assignee_id: UUID | None
    new_assignee_id: UUID
    assigned_by_id: UUID
    created_at: datetime


class TaskStatusHistoryResponse(BaseModel):
    """DTO for a single task status history record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    previous_status: TaskStatusValue | None
    new_status: TaskStatusValue
    changed_by_id: UUID
    created_at: datetime


class ActivityLogResponse(BaseModel):
    """DTO for an activity log record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    actor_id: UUID
    action: str
    details: dict | None = None
    created_at: datetime


class NotificationResponse(BaseModel):
    """DTO for a notification record."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    recipient_id: UUID
    task_id: UUID
    type: str
    message: str
    is_read: bool
    created_at: datetime


class TaskAssignResponse(BaseModel):
    """DTO for an atomic task assignment result."""

    task: TaskResponse
    assignment_history: TaskAssignmentHistoryResponse
    status_history: TaskStatusHistoryResponse | None = None
    activity_log: ActivityLogResponse
    notification: NotificationResponse
    message: str = "Task assigned successfully within atomic transaction boundary"
