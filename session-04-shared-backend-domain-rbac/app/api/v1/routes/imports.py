from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.api.dependencies.deps import SessionDep
from app.db.mongodb import get_mongo_db
from app.schemas.import_schema import (
    RawImportStatus,
    RawTaskImportRequest,
    RawTaskImportResponse,
)
from app.services.import_service import ImportService

router = APIRouter(prefix="/imports/tasks", tags=["Imports"])


@router.post(
    "/raw",
    response_model=RawTaskImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Process raw task import payload",
    description=(
        "Stores third-party raw JSON task payload in MongoDB audit store ('raw_task_imports'), "
        "marks it pending, validates and normalizes records into PostgreSQL ('task' table), "
        "then marks the import completed or failed with trace and failure details."
    ),
)
async def process_raw_import(
    request: RawTaskImportRequest,
    db_pg: SessionDep,
    db_mongo: AsyncIOMotorDatabase[Any] = Depends(get_mongo_db),
) -> RawTaskImportResponse:
    """POST /imports/tasks/raw - Process raw import payload."""
    return await ImportService.process_raw_import(db_pg, db_mongo, request)


@router.get(
    "/raw",
    response_model=list[RawTaskImportResponse],
    status_code=status.HTTP_200_OK,
    summary="List raw import audit records from MongoDB",
    description="Queries MongoDB collection 'raw_task_imports' with optional status filter (pending, completed, failed).",
)
async def list_raw_imports(
    status_filter: RawImportStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by processed status: pending | completed | failed",
    ),
    db_mongo: AsyncIOMotorDatabase[Any] = Depends(get_mongo_db),
) -> list[RawTaskImportResponse]:
    """GET /imports/tasks/raw - Retrieve raw import documents from MongoDB."""
    return await ImportService.list_raw_imports(db_mongo, status_filter=status_filter)
