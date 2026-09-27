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
async def test_health_check(client: AsyncClient):
    """Test 1: Verify health check endpoint returns HTTP 200 OK."""
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_user_success(client: AsyncClient):
    """Test 2: Verify POST /users creates a user and returns HTTP 201 Created."""
    unique_id = str(uuid.uuid4())[:8]
    payload = {
        "name": f"User {unique_id}",
        "username": f"user_{unique_id}",
        "email": f"user_{unique_id}@example.com",
        "password": "SecurePassword123!",
    }
    response = await client.post("/users", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == f"user_{unique_id}"
    assert data["role"] == "user"
    assert "password" not in data


@pytest.mark.asyncio
async def test_get_user_not_found(client: AsyncClient):
    """Test 3: Verify GET /users/{id} returns HTTP 404 Not Found for missing user."""
    random_uuid = str(uuid.uuid4())
    response = await client.get(f"/users/{random_uuid}")
    assert response.status_code == 404
