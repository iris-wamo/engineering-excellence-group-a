"""Exercise the real Session 4 HTTP adapters without external database services."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.deps import get_db
from app.auth.dependencies import get_current_user
from app.auth.roles import UserRole
from app.core.config import Settings
from app.core.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    NotAuthenticatedError,
    StatusChangeForbiddenError,
    TaskNotFoundError,
)
from app.main import app, application
from app.models.user import User
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from app.services.user_service import UserService


@pytest_asyncio.fixture
async def foundation_client():
    """Restore dependency overrides even after failures; no DB connection is opened."""
    original_overrides = app.dependency_overrides.copy()

    async def fake_db():
        yield None

    async def fake_user():
        return User(id=uuid4(), role=UserRole.ADMIN.value)

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_current_user] = fake_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=application), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


@pytest.mark.asyncio
async def test_health_response_is_unchanged_and_traced(foundation_client):
    response = await foundation_client.get(
        "/health", headers={"X-Request-ID": "health-123"}
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-request-id"] == "health-123"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,owner,method",
    [
        ("/users", UserService, "get_users"),
        ("/projects", ProjectService, "get_all_projects"),
        ("/tasks", TaskService, "get_tasks"),
    ],
)
async def test_paginated_routes_preserve_contract(
    foundation_client, monkeypatch, path, owner, method
):
    service = AsyncMock(return_value=([], 0))
    monkeypatch.setattr(owner, method, service)
    response = await foundation_client.get(path, params={"page": 3, "page_size": 20})
    assert response.status_code == 200
    assert response.json() == {"items": [], "page": 3, "page_size": 20, "total": 0}
    kwargs = service.await_args.kwargs
    expected = (
        {"limit": 20, "offset": 40}
        if path == "/users"
        else {"page": 3, "page_size": 20}
    )
    for key, value in expected.items():
        assert kwargs[key] == value


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/users", "/projects", "/tasks"])
@pytest.mark.parametrize(
    "query", ["page=0", "page_size=0", "page_size=101", "page=invalid"]
)
async def test_invalid_pagination_remains_422(foundation_client, path, query):
    response = await foundation_client.get(f"{path}?{query}")
    assert response.status_code == 422
    assert response.headers["x-request-id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status,code,message",
    [
        (TaskNotFoundError, 404, "TASK_NOT_FOUND", "Task not found"),
        (
            EmailAlreadyExistsError,
            409,
            "EMAIL_ALREADY_EXISTS",
            "User with this email already exists",
        ),
        (
            NotAuthenticatedError,
            401,
            "UNAUTHORIZED",
            "Not authenticated",
        ),
        (
            InvalidCredentialsError,
            401,
            "INVALID_CREDENTIALS",
            "Incorrect username/email or password",
        ),
        (
            StatusChangeForbiddenError,
            403,
            "STATUS_CHANGE_FORBIDDEN",
            "Only the assignee, a manager of the project, or an admin can change a task's status; only managers and admins can cancel a task",
        ),
    ],
)
async def test_app_errors_preserve_http_contract(
    foundation_client, monkeypatch, error, status, code, message
):
    monkeypatch.setattr(TaskService, "get_task", AsyncMock(side_effect=error()))
    response = await foundation_client.get(f"/tasks/{uuid4()}")
    assert response.status_code == status
    assert response.json() == {"detail": {"error": {"code": code, "message": message}}}
    assert response.headers["x-request-id"]
    if status == 401:
        assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_protected_route_still_requires_bearer_token(foundation_client):
    app.dependency_overrides.pop(get_current_user)
    response = await foundation_client.get("/tasks")
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.headers["x-request-id"]


def test_app_settings_extend_shared_base_without_changing_db_aliases(monkeypatch):
    for key in ("DATABASE_URL", "TEST_DATABASE_URL", "MONGO_URI", "ENVIRONMENT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "testing")
    monkeypatch.setenv("POSTGRES_USER", "fixture_user")
    monkeypatch.setenv("POSTGRES_PASSWORD", "fixture_password")
    monkeypatch.setenv("POSTGRES_DB", "fixture_db")
    monkeypatch.setenv("POSTGRES_HOST", "localhost")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    config = Settings(_env_file=None)
    assert config.ENVIRONMENT == "testing"
    assert (
        config.DATABASE_URL
        == "postgresql+asyncpg://fixture_user:fixture_password@localhost:5432/fixture_db"
    )


def test_openapi_lists_existing_pagination_parameters():
    schema = app.openapi()
    for path in ("/users", "/projects", "/tasks"):
        params = {
            p["name"]: p["schema"] for p in schema["paths"][path]["get"]["parameters"]
        }
        assert params["page"]["minimum"] == 1
        assert params["page_size"]["maximum"] == 100
        assert "data" not in params
