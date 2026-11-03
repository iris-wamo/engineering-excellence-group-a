from __future__ import annotations

import enum
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RawImportStatus(enum.StrEnum):
    """Processing states for a raw import audit document."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"


class RawTaskPriority(enum.StrEnum):
    """Supported priority values from external task imports."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RawTaskPayload(BaseModel):
    """Validated task payload after the raw document has been stored."""

    title: str = Field(..., min_length=1, max_length=255)
    project_title: str = Field(..., min_length=1, max_length=255)
    assignee_email: EmailStr = Field(
        ...,
        description="Email of assignee to resolve in PostgreSQL",
    )
    priority: RawTaskPriority = Field(default=RawTaskPriority.MEDIUM)
    description: str | None = Field(default=None, max_length=2000)


class RawTaskImportRequest(BaseModel):
    """Request DTO for submitting a raw task import."""

    source: str = Field(
        default="external_csv_import", description="Origin source system"
    )
    payload: dict[str, Any] = Field(
        ...,
        description=(
            "Raw third-party task payload. It is stored before validation so failed "
            "imports remain traceable."
        ),
    )


class NormalizedTaskRecord(BaseModel):
    """PostgreSQL task record created from a completed raw import."""

    task_id: UUID
    title: str
    project_id: UUID
    assignee_id: UUID
    priority: RawTaskPriority
    status: str


class RawTaskImportResponse(BaseModel):
    """Response DTO for a raw task import audit document in MongoDB."""

    id: str = Field(..., description="MongoDB BSON ObjectId string")
    import_id: str = Field(..., description="Stable import identifier for tracing")
    trace_id: str = Field(..., description="Correlation ID for the import attempt")
    source: str
    payload: dict[str, Any]
    processed_status: RawImportStatus = Field(
        ...,
        description="pending | completed | failed",
    )
    postgres_task_id: UUID | None = Field(
        default=None,
        description="Linked PostgreSQL Task UUID if successful",
    )
    normalized_records: list[NormalizedTaskRecord] = Field(default_factory=list)
    error_message: str | None = Field(
        default=None,
        description="Validation or normalization error message if failed",
    )
    received_at: datetime
    processed_at: datetime | None = None
