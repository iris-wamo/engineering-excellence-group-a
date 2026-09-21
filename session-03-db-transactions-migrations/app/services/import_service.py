from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.task import TaskPriority, TaskStatus
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.schemas.import_schema import RawTaskImportRequest, RawTaskImportResponse

COLLECTION_NAME = "raw_task_imports"


class ImportService:
    """Service handling MongoDB raw payload traceability and PostgreSQL normalization."""

    @staticmethod
    async def process_raw_import(
        db_pg: AsyncSession,
        db_mongo: AsyncIOMotorDatabase[Any],
        request: RawTaskImportRequest,
    ) -> RawTaskImportResponse:
        """Process a raw task import payload through MongoDB audit store and PostgreSQL relational store.

        Steps:
        1. Store raw payload in MongoDB collection 'raw_task_imports' with status='pending'.
        2. Validate project existence by title in PostgreSQL.
        3. Validate assignee existence by email in PostgreSQL.
        4. Create normalized Task record in PostgreSQL.
        5. On Success: Update MongoDB doc -> status='success', postgres_task_id=task.id.
        6. On Failure: Catch error, update MongoDB doc -> status='failed', error_message=str(e).
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        payload_dict = request.payload.model_dump()

        # Step 1: Insert raw payload into MongoDB audit store as 'pending'
        mongo_doc = {
            "source": request.source,
            "payload": payload_dict,
            "processed_status": "pending",
            "postgres_task_id": None,
            "error_message": None,
            "received_at": now,
            "processed_at": None,
        }
        insert_result = await db_mongo[COLLECTION_NAME].insert_one(mongo_doc)
        mongo_id = str(insert_result.inserted_id)

        try:
            # Step 2: Look up Project by title in PostgreSQL
            project_stmt = select(Project).where(Project.title == request.payload.project_title)
            project_res = await db_pg.execute(project_stmt)
            project = project_res.scalar_one_or_none()

            if project is None:
                raise ValueError(
                    f"Project with title '{request.payload.project_title}' not found in PostgreSQL"
                )

            # Step 3: Look up Assignee User by email in PostgreSQL
            user_stmt = select(User).where(User.email == request.payload.assignee_email)
            user_res = await db_pg.execute(user_stmt)
            user = user_res.scalar_one_or_none()

            if user is None:
                raise ValueError(
                    f"Assignee with email '{request.payload.assignee_email}' not found in PostgreSQL"
                )

            # Step 4: Map priority string to TaskPriority Enum
            priority_map = {
                "low": TaskPriority.LOW,
                "medium": TaskPriority.MEDIUM,
                "high": TaskPriority.HIGH,
            }
            priority_enum = priority_map.get(
                request.payload.priority.lower(), TaskPriority.MEDIUM
            )

            # Step 5: Create normalized Task record in PostgreSQL via TaskRepository
            task = await TaskRepository.create(
                db_pg,
                project_id=project.id,
                title=request.payload.title,
                description=request.payload.description,
                priority=priority_enum,
                status=TaskStatus.TODO,
                assigned_to=user.id,
                created_at=now,
                updated_at=now,
            )

            # Step 6: Update MongoDB audit doc on SUCCESS
            processed_time = datetime.now(timezone.utc).replace(tzinfo=None)
            await db_mongo[COLLECTION_NAME].update_one(
                {"_id": insert_result.inserted_id},
                {
                    "$set": {
                        "processed_status": "success",
                        "postgres_task_id": str(task.id),
                        "error_message": None,
                        "processed_at": processed_time,
                    }
                },
            )

            return RawTaskImportResponse(
                id=mongo_id,
                source=request.source,
                payload=payload_dict,
                processed_status="success",
                postgres_task_id=task.id,
                error_message=None,
                received_at=now,
                processed_at=processed_time,
            )

        except Exception as e:
            # Step 7: Update MongoDB audit doc on FAILURE (Preserve raw payload for traceability)
            await db_pg.rollback()
            error_str = str(e)
            processed_time = datetime.now(timezone.utc).replace(tzinfo=None)

            await db_mongo[COLLECTION_NAME].update_one(
                {"_id": insert_result.inserted_id},
                {
                    "$set": {
                        "processed_status": "failed",
                        "postgres_task_id": None,
                        "error_message": error_str,
                        "processed_at": processed_time,
                    }
                },
            )

            return RawTaskImportResponse(
                id=mongo_id,
                source=request.source,
                payload=payload_dict,
                processed_status="failed",
                postgres_task_id=None,
                error_message=error_str,
                received_at=now,
                processed_at=processed_time,
            )

    @staticmethod
    async def list_raw_imports(
        db_mongo: AsyncIOMotorDatabase[Any],
        status_filter: str | None = None,
    ) -> list[RawTaskImportResponse]:
        """Query MongoDB collection 'raw_task_imports' with optional status filter."""
        query_filter: dict[str, Any] = {}
        if status_filter:
            query_filter["processed_status"] = status_filter

        cursor = db_mongo[COLLECTION_NAME].find(query_filter).sort("received_at", -1)
        results: list[RawTaskImportResponse] = []

        async for doc in cursor:
            pg_id = (
                UUID(doc["postgres_task_id"])
                if doc.get("postgres_task_id")
                else None
            )
            results.append(
                RawTaskImportResponse(
                    id=str(doc["_id"]),
                    source=doc.get("source", "external_csv_import"),
                    payload=doc.get("payload", {}),
                    processed_status=doc.get("processed_status", "pending"),
                    postgres_task_id=pg_id,
                    error_message=doc.get("error_message"),
                    received_at=doc.get("received_at", datetime.now(timezone.utc).replace(tzinfo=None)),
                    processed_at=doc.get("processed_at"),
                )
            )

        return results
