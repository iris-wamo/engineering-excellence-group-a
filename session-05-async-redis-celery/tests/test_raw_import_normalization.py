from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from bson import ObjectId

from app.schemas.import_schema import RawImportStatus, RawTaskImportRequest
from app.services.import_service import COLLECTION_NAME, ImportService


class _InsertResult:
    def __init__(self, inserted_id: ObjectId) -> None:
        self.inserted_id = inserted_id


class _FakeCursor:
    def __init__(self, docs: list[dict]) -> None:
        self._docs = docs

    def sort(self, *_args):
        return self

    def __aiter__(self):
        self._iter = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[ObjectId, dict] = {}
        self.inserted: list[dict] = []
        self.updates: list[dict] = []

    async def insert_one(self, doc: dict) -> _InsertResult:
        inserted_id = ObjectId()
        stored = {**doc, "_id": inserted_id}
        self.docs[inserted_id] = stored
        self.inserted.append(stored.copy())
        return _InsertResult(inserted_id)

    async def update_one(self, filter_: dict, update: dict) -> None:
        self.updates.append({"filter": filter_, "update": update})
        doc = self.docs[filter_["_id"]]
        doc.update(update.get("$set", {}))

    def find(self, query_filter: dict) -> _FakeCursor:
        docs = [
            doc
            for doc in self.docs.values()
            if all(doc.get(key) == value for key, value in query_filter.items())
        ]
        return _FakeCursor(docs)


class _FakeMongo:
    def __init__(self) -> None:
        self.collection = _FakeCollection()

    def __getitem__(self, name: str) -> _FakeCollection:
        assert name == COLLECTION_NAME
        return self.collection


@pytest.mark.asyncio
async def test_raw_import_stores_pending_then_creates_normalized_record(monkeypatch):
    db_pg = SimpleNamespace(rollback=AsyncMock())
    db_mongo = _FakeMongo()
    project = SimpleNamespace(id=uuid4())
    assignee = SimpleNamespace(id=uuid4())
    task = SimpleNamespace(id=uuid4(), title="Imported task")

    monkeypatch.setattr(
        ImportService,
        "_find_project_by_title",
        AsyncMock(return_value=project),
    )
    monkeypatch.setattr(
        ImportService,
        "_find_assignee_by_email",
        AsyncMock(return_value=assignee),
    )

    async def _create_task(_db, *, payload, project, assignee, now):  # noqa: ARG001
        assert payload.title == "Imported task"
        assert payload.priority == "high"
        assert isinstance(now, datetime)
        return task

    monkeypatch.setattr(ImportService, "_create_normalized_task", _create_task)

    response = await ImportService.process_raw_import(
        db_pg,
        db_mongo,
        RawTaskImportRequest(
            source="vendor_csv",
            payload={
                "title": "Imported task",
                "project_title": "Customer Portal",
                "assignee_email": "owner@example.com",
                "priority": "high",
                "description": "Created by a partner feed",
            },
        ),
    )

    inserted = db_mongo.collection.inserted[0]
    assert inserted["processed_status"] == RawImportStatus.PENDING
    assert inserted["payload"]["title"] == "Imported task"
    assert inserted["trace_id"] == response.trace_id

    stored = next(iter(db_mongo.collection.docs.values()))
    assert stored["processed_status"] == RawImportStatus.COMPLETED
    assert stored["postgres_task_id"] == str(task.id)
    assert stored["normalized_records"][0]["task_id"] == str(task.id)
    assert stored["error_message"] is None

    assert response.processed_status == RawImportStatus.COMPLETED
    assert response.import_id == response.id
    assert response.postgres_task_id == task.id
    assert response.normalized_records[0].project_id == project.id
    db_pg.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_payload_remains_stored_with_failure_reason(monkeypatch):
    db_pg = SimpleNamespace(rollback=AsyncMock())
    db_mongo = _FakeMongo()
    find_project = AsyncMock()
    monkeypatch.setattr(ImportService, "_find_project_by_title", find_project)

    response = await ImportService.process_raw_import(
        db_pg,
        db_mongo,
        RawTaskImportRequest(
            source="webhook",
            payload={
                "project_title": "Customer Portal",
                "assignee_email": "owner@example.com",
                "priority": "high",
            },
        ),
    )

    stored = next(iter(db_mongo.collection.docs.values()))
    assert stored["payload"]["project_title"] == "Customer Portal"
    assert stored["processed_status"] == RawImportStatus.FAILED
    assert stored["postgres_task_id"] is None
    assert stored["normalized_records"] == []
    assert "Invalid raw task payload" in stored["failure_reason"]

    assert response.processed_status == RawImportStatus.FAILED
    assert response.postgres_task_id is None
    assert response.normalized_records == []
    assert "Invalid raw task payload" in response.error_message
    find_project.assert_not_awaited()
    db_pg.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_raw_imports_filters_by_processing_status():
    db_mongo = _FakeMongo()
    completed_id = ObjectId()
    failed_id = ObjectId()
    db_mongo.collection.docs = {
        completed_id: {
            "_id": completed_id,
            "import_id": str(completed_id),
            "trace_id": "trace-completed",
            "source": "vendor_csv",
            "payload": {"title": "Complete"},
            "processed_status": RawImportStatus.COMPLETED.value,
            "postgres_task_id": str(uuid4()),
            "normalized_records": [],
            "error_message": None,
            "received_at": datetime(2026, 1, 1),
            "processed_at": datetime(2026, 1, 1),
        },
        failed_id: {
            "_id": failed_id,
            "import_id": str(failed_id),
            "trace_id": "trace-failed",
            "source": "vendor_csv",
            "payload": {"title": "Failed"},
            "processed_status": RawImportStatus.FAILED.value,
            "postgres_task_id": None,
            "normalized_records": [],
            "error_message": "bad project",
            "received_at": datetime(2026, 1, 2),
            "processed_at": datetime(2026, 1, 2),
        },
    }

    results = await ImportService.list_raw_imports(
        db_mongo,
        status_filter=RawImportStatus.FAILED,
    )

    assert len(results) == 1
    assert results[0].id == str(failed_id)
    assert results[0].processed_status == RawImportStatus.FAILED
    assert results[0].error_message == "bad project"
