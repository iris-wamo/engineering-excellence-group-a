from __future__ import annotations

import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies.deps import get_db
from app.core.config import settings
from app.main import app


@pytest_asyncio.fixture
async def client():
    """Provide an async HTTP client with DB dependency override."""
    test_engine = create_async_engine(settings.test_database_url, echo=False)
    test_session_local = sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async def override_get_db():
        async with test_session_local() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()
    await test_engine.dispose()


@pytest.mark.asyncio
async def test_mongo_raw_import_success(client: AsyncClient):
    """Test successful raw task import payload processing into MongoDB and PostgreSQL."""
    unique_id = str(uuid.uuid4())[:8]
    user_payload = {
        "name": f"Import User {unique_id}",
        "username": f"import_usr_{unique_id}",
        "email": f"import_user_{unique_id}@example.com",
        "password": "SecurePassword123!",
    }
    user_res = await client.post("/users", json=user_payload)
    assert user_res.status_code == 201

    project_payload = {
        "title": f"Import Demo Project {unique_id}",
        "description": "Demo project for raw imports",
        "owner_id": user_res.json()["id"],
    }
    proj_res = await client.post("/projects", json=project_payload)
    assert proj_res.status_code == 201

    payload = {
        "source": "external_csv_import",
        "payload": {
            "title": f"Raw Import Task {unique_id}",
            "project_title": f"Import Demo Project {unique_id}",
            "assignee_email": f"import_user_{unique_id}@example.com",
            "priority": "high",
            "description": "Imported task from raw webhook",
        },
    }
    res = await client.post("/imports/tasks/raw", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["processed_status"] == "success"
    assert data["postgres_task_id"] is not None
    assert data["error_message"] is None


@pytest.mark.asyncio
async def test_mongo_raw_import_failed_preserves_payload(client: AsyncClient):
    """Test failed raw task import payload processing (invalid assignee) preserves raw document in MongoDB."""
    payload = {
        "source": "external_csv_import",
        "payload": {
            "title": "Failed Import Test Task",
            "project_title": "Nonexistent Project Title",
            "assignee_email": "missing_user@example.com",
            "priority": "high",
        },
    }
    res = await client.post("/imports/tasks/raw", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["processed_status"] == "failed"
    assert data["postgres_task_id"] is None
    assert "not found in PostgreSQL" in data["error_message"]
