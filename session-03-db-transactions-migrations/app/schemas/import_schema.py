from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RawTaskPayload(BaseModel):
    """Raw task payload as received from external third-party systems."""

    title: str = Field(..., min_length=1, max_length=255)
    project_title: str = Field(..., min_length=1, max_length=255)
    assignee_email: str = Field(..., description="Email of assignee to resolve in PostgreSQL")
    priority: str = Field(default="medium")
    description: str | None = Field(default=None, max_length=2000)


class RawTaskImportRequest(BaseModel):
    """Request DTO for submitting a raw task import."""

    source: str = Field(default="external_csv_import", description="Origin source system")
    payload: RawTaskPayload


class RawTaskImportResponse(BaseModel):
    """Response DTO for a raw task import audit document in MongoDB."""

    id: str = Field(..., description="MongoDB BSON ObjectId string")
    source: str
    payload: dict[str, Any]
    processed_status: str = Field(..., description="pending | success | failed")
    postgres_task_id: UUID | None = Field(default=None, description="Linked PostgreSQL Task UUID if successful")
    error_message: str | None = Field(default=None, description="Validation error message if failed")
    received_at: datetime
    processed_at: datetime | None = None
