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


async def _create_user(client: AsyncClient) -> str:
    unique_id = str(uuid.uuid4())[:8]
    payload = {
        "name": f"Task User {unique_id}",
        "username": f"task_user_{unique_id}",
        "email": f"task_user_{unique_id}@example.com",
        "password": "SecurePassword123!",
    }
    response = await client.post("/users", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


async def _create_project(client: AsyncClient, owner_id: str) -> str:
    payload = {
        "title": "Task API Project",
        "description": "Project used for task endpoint tests",
        "priority": "MEDIUM",
        "status": "ACTIVE",
        "owner_id": owner_id,
    }
    response = await client.post("/projects", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_create_task_success_includes_timestamps(client: AsyncClient):
    owner_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)

    payload = {
        "title": "Fix login validation bug",
        "description": "Return clear validation error for missing email",
        "project_id": project_id,
        "assignee_id": owner_id,
        "priority": "medium",
        "status": "todo",
    }
    response = await client.post("/tasks", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["title"] == payload["title"]
    assert data["status"] == "todo"
    assert data["priority"] == "medium"
    assert data["created_at"] is not None
    assert data["updated_at"] is not None


@pytest.mark.asyncio
async def test_get_task_not_found(client: AsyncClient):
    response = await client.get(f"/tasks/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_task_status_success(client: AsyncClient):
    owner_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)

    create_payload = {
        "title": "Move status to in progress",
        "project_id": project_id,
        "assignee_id": owner_id,
    }
    create_response = await client.post("/tasks", json=create_payload)
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    update_response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": owner_id},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["status"] == "in_progress"
    assert updated["created_at"] is not None
    assert updated["updated_at"] is not None

    # Verify status history & activity log audit trail created by status update
    history_res = await client.get(f"/tasks/{task_id}/history")
    assert history_res.status_code == 200
    statuses = history_res.json()["statuses"]
    assert len(statuses) == 1
    assert statuses[0]["previous_status"] == "todo"
    assert statuses[0]["new_status"] == "in_progress"
    assert statuses[0]["changed_by_id"] == owner_id

    activity_res = await client.get(f"/tasks/{task_id}/activity")
    assert activity_res.status_code == 200
    activities = activity_res.json()
    assert len(activities) == 1
    assert activities[0]["action"] == "task.status_changed"
    assert activities[0]["actor_id"] == owner_id


@pytest.mark.asyncio
async def test_update_task_status_requires_user_header(client: AsyncClient):
    owner_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)

    create_response = await client.post(
        "/tasks", json={"title": "Header required", "project_id": project_id}
    )
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # Missing X-User-ID header -> 401
    response = await client.patch(
        f"/tasks/{task_id}/status", json={"status": "in_progress"}
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "MISSING_USER_HEADER"

    # Unknown user in header -> 401
    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": str(uuid.uuid4())},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "CURRENT_USER_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_task_status_forbidden_for_unrelated_user(client: AsyncClient):
    owner_id = await _create_user(client)
    stranger_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)

    create_response = await client.post(
        "/tasks",
        json={
            "title": "Stranger cannot change this",
            "project_id": project_id,
            "assignee_id": owner_id,
        },
    )
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # Stranger is not assignee, not project owner, not a member -> 403
    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": stranger_id},
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error"]["code"] == "STATUS_CHANGE_FORBIDDEN"


@pytest.mark.asyncio
async def test_update_task_status_invalid_transition_conflict(client: AsyncClient):
    owner_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)

    create_response = await client.post(
        "/tasks",
        json={
            "title": "Skip the workflow",
            "project_id": project_id,
            "assignee_id": owner_id,
        },
    )
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    # todo -> done skips in_progress/in_review -> 409
    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "done"},
        headers={"X-User-ID": owner_id},
    )
    assert response.status_code == 409
    error = response.json()["detail"]["error"]
    assert error["code"] == "INVALID_STATUS_TRANSITION"
    assert "TODO" in error["message"] and "DONE" in error["message"]


@pytest.mark.asyncio
async def test_task_status_full_workflow(client: AsyncClient):
    owner_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)

    create_response = await client.post(
        "/tasks",
        json={
            "title": "Walk the workflow",
            "project_id": project_id,
            "assignee_id": owner_id,
        },
    )
    assert create_response.status_code == 201
    task_id = create_response.json()["id"]

    for next_status in ("in_progress", "in_review", "done"):
        response = await client.patch(
            f"/tasks/{task_id}/status",
            json={"status": next_status},
            headers={"X-User-ID": owner_id},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == next_status

    # done is terminal -> any further move is 409
    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "todo"},
        headers={"X-User-ID": owner_id},
    )
    assert response.status_code == 409

    history_res = await client.get(f"/tasks/{task_id}/history")
    statuses = history_res.json()["statuses"]
    # History endpoint returns newest first
    assert [s["new_status"] for s in statuses] == [
        "done",
        "in_review",
        "in_progress",
    ]


@pytest.mark.asyncio
async def test_list_tasks_with_filters_and_pagination(client: AsyncClient):
    owner_id = await _create_user(client)
    project_id = await _create_project(client, owner_id)

    for idx in range(2):
        payload = {
            "title": f"List Task {idx}",
            "project_id": project_id,
            "assignee_id": owner_id,
            "priority": "high" if idx == 0 else "medium",
            "status": "todo",
        }
        response = await client.post("/tasks", json=payload)
        assert response.status_code == 201

    response = await client.get(
        f"/tasks?page=1&page_size=10&status=todo&project_id={project_id}&assignee_id={owner_id}"
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert data["total"] >= 1
