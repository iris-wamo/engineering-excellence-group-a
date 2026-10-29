from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project
from app.models.task import TaskPriority, TaskStatus
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.schemas.import_schema import (
    NormalizedTaskRecord,
    RawImportStatus,
    RawTaskImportRequest,
    RawTaskImportResponse,
    RawTaskPayload,
)

COLLECTION_NAME = "raw_task_imports"


class ImportNormalizationError(ValueError):
    """Raised when a raw payload cannot be converted to a task record."""


class ImportService:
    """Service handling MongoDB raw payload traceability and PostgreSQL normalization."""

    @staticmethod
    async def process_raw_import(
        db_pg: AsyncSession,
        db_mongo: AsyncIOMotorDatabase[Any],
        request: RawTaskImportRequest,
    ) -> RawTaskImportResponse:
        """Store, validate, normalize, and trace a raw task import.

        The raw document is written first with ``pending`` status. Every later
        outcome updates the same document to either ``completed`` with the
        normalized task reference, or ``failed`` with the reason.
        """
        received_at = ImportService._utc_now()
        trace_id = str(uuid4())
        payload_dict = dict(request.payload)
        import_object_id = await ImportService._store_raw_payload(
            db_mongo=db_mongo,
            source=request.source,
            payload=payload_dict,
            trace_id=trace_id,
            received_at=received_at,
        )
        import_id = str(import_object_id)

        try:
            payload = ImportService._validate_payload(payload_dict)
            project = await ImportService._find_project_by_title(
                db_pg,
                payload.project_title,
            )
            assignee = await ImportService._find_assignee_by_email(
                db_pg,
                str(payload.assignee_email),
            )
            task = await ImportService._create_normalized_task(
                db_pg,
                payload=payload,
                project=project,
                assignee=assignee,
                now=received_at,
            )

            processed_at = ImportService._utc_now()
            normalized_record = NormalizedTaskRecord(
                task_id=task.id,
                title=task.title,
                project_id=project.id,
                assignee_id=assignee.id,
                priority=payload.priority,
                status=TaskStatus.TODO.value,
            )
            await ImportService._mark_import_completed(
                db_mongo=db_mongo,
                import_object_id=import_object_id,
                task_id=task.id,
                normalized_records=[normalized_record],
                processed_at=processed_at,
            )
            return ImportService._build_response(
                import_id=import_id,
                trace_id=trace_id,
                source=request.source,
                payload=payload_dict,
                status=RawImportStatus.COMPLETED,
                task_id=task.id,
                normalized_records=[normalized_record],
                error_message=None,
                received_at=received_at,
                processed_at=processed_at,
            )
        except Exception as exc:
            await db_pg.rollback()
            processed_at = ImportService._utc_now()
            failure_reason = str(exc)
            await ImportService._mark_import_failed(
                db_mongo=db_mongo,
                import_object_id=import_object_id,
                failure_reason=failure_reason,
                processed_at=processed_at,
            )
            return ImportService._build_response(
                import_id=import_id,
                trace_id=trace_id,
                source=request.source,
                payload=payload_dict,
                status=RawImportStatus.FAILED,
                task_id=None,
                normalized_records=[],
                error_message=failure_reason,
                received_at=received_at,
                processed_at=processed_at,
            )

    @staticmethod
    async def list_raw_imports(
        db_mongo: AsyncIOMotorDatabase[Any],
        status_filter: RawImportStatus | None = None,
    ) -> list[RawTaskImportResponse]:
        """Query MongoDB collection 'raw_task_imports' with optional status filter."""
        query_filter: dict[str, Any] = {}
        if status_filter:
            query_filter["processed_status"] = status_filter.value

        cursor = db_mongo[COLLECTION_NAME].find(query_filter).sort("received_at", -1)
        results: list[RawTaskImportResponse] = []

        async for doc in cursor:
            pg_id = (
                UUID(doc["postgres_task_id"]) if doc.get("postgres_task_id") else None
            )
            results.append(
                RawTaskImportResponse(
                    id=str(doc["_id"]),
                    import_id=doc.get("import_id", str(doc["_id"])),
                    trace_id=doc.get("trace_id", ""),
                    source=doc.get("source", "external_csv_import"),
                    payload=doc.get("payload", {}),
                    processed_status=doc.get(
                        "processed_status",
                        RawImportStatus.PENDING,
                    ),
                    postgres_task_id=pg_id,
                    normalized_records=doc.get("normalized_records", []),
                    error_message=doc.get("error_message"),
                    received_at=doc.get("received_at", ImportService._utc_now()),
                    processed_at=doc.get("processed_at"),
                )
            )

        return results

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    async def _store_raw_payload(
        *,
        db_mongo: AsyncIOMotorDatabase[Any],
        source: str,
        payload: dict[str, Any],
        trace_id: str,
        received_at: datetime,
    ) -> Any:
        doc = {
            "import_id": None,
            "trace_id": trace_id,
            "source": source,
            "payload": payload,
            "processed_status": RawImportStatus.PENDING.value,
            "postgres_task_id": None,
            "normalized_records": [],
            "error_message": None,
            "failure_reason": None,
            "received_at": received_at,
            "processed_at": None,
        }
        result = await db_mongo[COLLECTION_NAME].insert_one(doc)
        import_id = str(result.inserted_id)
        await db_mongo[COLLECTION_NAME].update_one(
            {"_id": result.inserted_id},
            {"$set": {"import_id": import_id}},
        )
        return result.inserted_id

    @staticmethod
    def _validate_payload(payload: dict[str, Any]) -> RawTaskPayload:
        try:
            return RawTaskPayload.model_validate(payload)
        except ValidationError as exc:
            message = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
            raise ImportNormalizationError(
                f"Invalid raw task payload: {message}"
            ) from exc

    @staticmethod
    async def _find_project_by_title(db: AsyncSession, title: str) -> Project:
        result = await db.execute(select(Project).where(Project.title == title))
        project = result.scalar_one_or_none()
        if project is None:
            raise ImportNormalizationError(f"Project '{title}' was not found")
        return project

    @staticmethod
    async def _find_assignee_by_email(db: AsyncSession, email: str) -> User:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            raise ImportNormalizationError(f"Assignee '{email}' was not found")
        return user

    @staticmethod
    async def _create_normalized_task(
        db: AsyncSession,
        *,
        payload: RawTaskPayload,
        project: Project,
        assignee: User,
        now: datetime,
    ):
        priority_map = {
            "low": TaskPriority.LOW,
            "medium": TaskPriority.MEDIUM,
            "high": TaskPriority.HIGH,
        }
        return await TaskRepository.create(
            db,
            project_id=project.id,
            title=payload.title.strip(),
            description=payload.description,
            priority=priority_map[payload.priority.value],
            status=TaskStatus.TODO,
            assigned_to=assignee.id,
            created_at=now,
            updated_at=now,
        )

    @staticmethod
    async def _mark_import_completed(
        *,
        db_mongo: AsyncIOMotorDatabase[Any],
        import_object_id: Any,
        task_id: UUID,
        normalized_records: list[NormalizedTaskRecord],
        processed_at: datetime,
    ) -> None:
        await db_mongo[COLLECTION_NAME].update_one(
            {"_id": import_object_id},
            {
                "$set": {
                    "processed_status": RawImportStatus.COMPLETED.value,
                    "postgres_task_id": str(task_id),
                    "normalized_records": [
                        record.model_dump(mode="json") for record in normalized_records
                    ],
                    "error_message": None,
                    "failure_reason": None,
                    "processed_at": processed_at,
                }
            },
        )

    @staticmethod
    async def _mark_import_failed(
        *,
        db_mongo: AsyncIOMotorDatabase[Any],
        import_object_id: Any,
        failure_reason: str,
        processed_at: datetime,
    ) -> None:
        await db_mongo[COLLECTION_NAME].update_one(
            {"_id": import_object_id},
            {
                "$set": {
                    "processed_status": RawImportStatus.FAILED.value,
                    "postgres_task_id": None,
                    "normalized_records": [],
                    "error_message": failure_reason,
                    "failure_reason": failure_reason,
                    "processed_at": processed_at,
                }
            },
        )

    @staticmethod
    def _build_response(
        *,
        import_id: str,
        trace_id: str,
        source: str,
        payload: dict[str, Any],
        status: RawImportStatus,
        task_id: UUID | None,
        normalized_records: list[NormalizedTaskRecord],
        error_message: str | None,
        received_at: datetime,
        processed_at: datetime | None,
    ) -> RawTaskImportResponse:
        return RawTaskImportResponse(
            id=import_id,
            import_id=import_id,
            trace_id=trace_id,
            source=source,
            payload=payload,
            processed_status=status,
            postgres_task_id=task_id,
            normalized_records=normalized_records,
            error_message=error_message,
            received_at=received_at,
            processed_at=processed_at,
        )
