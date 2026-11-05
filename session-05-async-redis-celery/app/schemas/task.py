from __future__ import annotations

import enum
from datetime import UTC, datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from taskflow_shared.contracts import IdentifiableSchema, TimestampedSchema
from taskflow_shared.pagination import PaginatedResponse


class TaskStatusValue(enum.StrEnum):
    """API-facing task statuses (lowercase REST values)."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"
    CANCELLED = "cancelled"


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
    due_date: AwareDatetime | None = None

    @field_validator("due_date")
    @classmethod
    def reject_past_due_date(cls, value: datetime | None) -> datetime | None:
        if value is not None and value < datetime.now(UTC):
            raise ValueError("due_date must not be in the past")
        return value


class TaskUpdate(BaseModel):
    """Partial due-date update: omission keeps the value; null clears it."""

    model_config = ConfigDict(extra="forbid")

    due_date: AwareDatetime | None = None


class TaskStatusUpdate(BaseModel):
    """Request payload for updating only a task's status."""

    status: TaskStatusValue


class TaskResponse(IdentifiableSchema, TimestampedSchema):
    """Response DTO for a single task."""

    model_config = ConfigDict(from_attributes=True)

    title: str
    description: str | None
    priority: TaskPriorityValue
    status: TaskStatusValue
    project_id: UUID | None
    assignee_id: UUID | None
    estimated_time: int | None
    deadline: datetime | None
    due_date: AwareDatetime | None = None


class TaskListResponse(PaginatedResponse[TaskResponse]):
    """Paginated list response for tasks."""


class TaskAssignRequest(BaseModel):
    """Request payload for assigning a task to a user atomically.

    The assigning user is always the authenticated caller; it is never taken
    from the request body, so the audit trail cannot be spoofed.
    """

    assignee_id: UUID = Field(
        ..., description="UUID of the user being assigned to the task"
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
