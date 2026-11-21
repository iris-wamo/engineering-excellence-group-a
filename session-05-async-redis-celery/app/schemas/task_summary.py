"""Schemas for GET /tasks/summary."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SummaryMode(StrEnum):
    ASYNC = "async"
    BLOCKING = "blocking"


class ExternalStatus(StrEnum):
    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"


class ExternalResult(BaseModel):
    status: ExternalStatus
    elapsed_ms: float = Field(..., description="Time spent on the call")
    data: dict[str, Any] | None = None
    detail: str | None = None


class TaskSummaryResponse(BaseModel):
    mode: SummaryMode
    by_status: dict[str, int] = Field(..., description="Task count per status")
    total: int
    overdue: int = Field(
        ..., description="due_date < now() and status is not done/cancelled"
    )
    assigned_to_me: int
    external: ExternalResult
    elapsed_ms: float = Field(..., description="Total server time")
