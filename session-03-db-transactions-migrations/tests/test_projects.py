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
    """Simple fixture to provide an async HTTP test client."""
    test_engine = create_async_engine(settings.test_database_url, echo=False)
    test_session_local = sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
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
async def test_create_project_success(client: AsyncClient):
    """Test POST /projects creates a project and returns HTTP 201 Created."""
    # Create a user first (required for foreign key constraint)
    user_payload = {
        "name": "Project Owner",
        "username": f"owner_{uuid.uuid4().hex[:8]}",
        "email": f"owner_{uuid.uuid4().hex[:8]}@example.com",
        "password": "SecurePassword123!",
    }
    user_response = await client.post("/users", json=user_payload)
    assert user_response.status_code == 201
    owner_id = user_response.json()["id"]

    # Now create project
    payload = {
        "title": "Test Project",
        "description": "A test project description",
        "priority": "HIGH",
        "status": "ACTIVE",
        "deadline": "2025-12-31T23:59:59",
        "owner_id": owner_id,
    }
    response = await client.post("/projects", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Project"
    assert data["description"] == "A test project description"
    assert data["priority"] == "HIGH"
    assert data["status"] == "ACTIVE"
    assert data["owner_id"] == owner_id
    assert "id" in data


@pytest.mark.asyncio
async def test_get_project_by_id_success(client: AsyncClient):
    """Test GET /projects/{id} returns specific project."""
    # Create a user first
    user_payload = {
        "name": "Get by ID Owner",
        "username": f"get_owner_{uuid.uuid4().hex[:8]}",
        "email": f"get_{uuid.uuid4().hex[:8]}@example.com",
        "password": "SecurePassword123!",
    }
    user_response = await client.post("/users", json=user_payload)
    assert user_response.status_code == 201
    owner_id = user_response.json()["id"]

    # Create a project
    create_response = await client.post(
        "/projects",
        json={
            "title": "Get by ID Project",
            "priority": "MEDIUM",
            "owner_id": owner_id,
        },
    )
    project_id = create_response.json()["id"]

    # Get by ID
    response = await client.get(f"/projects/{project_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == project_id
    assert data["title"] == "Get by ID Project"
    assert data["priority"] == "MEDIUM"


@pytest.mark.asyncio
async def test_get_project_by_id_not_found(client: AsyncClient):
    """Test GET /projects/{id} returns HTTP 404 for non-existent project."""
    random_uuid = str(uuid.uuid4())
    response = await client.get(f"/projects/{random_uuid}")
    assert response.status_code == 404
