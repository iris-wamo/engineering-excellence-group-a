"""Versioned task domain events."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

TASK_EVENT_VERSION = 1


class TaskEventType(StrEnum):
    ASSIGNED = "task.assigned"
    STATUS_CHANGED = "task.status_changed"


class TaskEventData(BaseModel):
    from_status: str | None = None
    to_status: str | None = None
    assignee_id: UUID | None = None


class TaskEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    type: TaskEventType
    version: int = TASK_EVENT_VERSION
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor_id: UUID
    task_id: UUID
    project_id: UUID
    data: TaskEventData = Field(default_factory=TaskEventData)
