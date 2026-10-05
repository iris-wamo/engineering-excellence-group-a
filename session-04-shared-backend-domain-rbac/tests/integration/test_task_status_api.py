"""API/integration tests for the status-transition endpoint.

Exercises the real HTTP path end to end:

    HTTP request -> API route -> Service -> Workflow -> Database

Three things are proven:
1. A valid API transition works (200 + committed DB state + audit trail).
2. An invalid API transition returns the expected, consistent error.
3. The HTTP layer only translates the domain result/error -- it does not
   implement the workflow. This is shown behaviourally: when the workflow's
   verdict is swapped, the API outcome follows the workflow, not the route.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies.deps import get_db
from app.core.config import settings
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.task import Task, TaskStatus
from app.models.task_status_history import TaskStatusHistory
from app.workflows.task_status_workflow import (
    InvalidTransitionError,
    TaskStatusWorkflow,
)


@pytest_asyncio.fixture
async def test_session():
    """Independent session used to inspect committed state."""
    engine = create_async_engine(settings.test_database_url, echo=False)
    session_factory = sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    """Async HTTP client with DB dependency override."""
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


async def _create_user(client: AsyncClient) -> str:
    unique_id = str(uuid.uuid4())[:8]
    response = await client.post(
        "/users",
        json={
            "name": f"API User {unique_id}",
            "username": f"api_user_{unique_id}",
            "email": f"api_user_{unique_id}@example.com",
            "password": "SecurePassword123!",
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_project(client: AsyncClient, owner_id: str) -> str:
    response = await client.post(
        "/projects",
        json={
            "title": "API Path Project",
            "priority": "MEDIUM",
            "status": "ACTIVE",
            "owner_id": owner_id,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _create_task(client: AsyncClient, project_id: str, assignee_id: str) -> str:
    response = await client.post(
        "/tasks",
        json={
            "title": "API path task",
            "project_id": project_id,
            "assignee_id": assignee_id,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _db_status(session: AsyncSession, task_uuid: uuid.UUID) -> TaskStatus:
    session.expire_all()
    return (
        await session.execute(select(Task.status).where(Task.id == task_uuid))
    ).scalar_one()


async def _counts(session: AsyncSession, task_uuid: uuid.UUID) -> dict[str, int]:
    session.expire_all()
    history = (
        (
            await session.execute(
                select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    )
    activity = (
        (
            await session.execute(
                select(ActivityLog).where(ActivityLog.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    )
    return {"history": len(history), "activity": len(activity)}


# ---------------------------------------------------------------------------
# 1. Valid API transition works through the whole path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_valid_transition_end_to_end(
    client: AsyncClient, test_session: AsyncSession
):
    """HTTP 200 in, committed DB state + audit trail out."""
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    assert await _db_status(test_session, task_uuid) == TaskStatus.TODO

    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": actor_id},
    )

    # API layer: 200 + response DTO reflects the domain result
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == task_id
    assert body["status"] == "in_progress"

    # Database layer: state and audit trail really changed
    assert await _db_status(test_session, task_uuid) == TaskStatus.IN_PROGRESS
    assert await _counts(test_session, task_uuid) == {"history": 1, "activity": 1}


# ---------------------------------------------------------------------------
# 2. Invalid API transition returns the expected error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_invalid_transition_returns_expected_error(
    client: AsyncClient, test_session: AsyncSession
):
    """todo -> done over HTTP: 409 with the domain error translated 1:1."""
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    response = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "done"},
        headers={"X-User-ID": actor_id},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "error": {
                "code": "INVALID_STATUS_TRANSITION",
                "message": ("Cannot transition task status from 'TODO' to 'DONE'"),
            }
        }
    }

    # Nothing was written by the rejected API call
    assert await _db_status(test_session, task_uuid) == TaskStatus.TODO
    assert await _counts(test_session, task_uuid) == {"history": 0, "activity": 0}


@pytest.mark.asyncio
async def test_api_error_contract_matches_service_and_domain_outcomes(
    client: AsyncClient,
):
    """Every HTTP status is a translation of a service/domain outcome."""
    actor_id = await _create_user(client)
    stranger_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)

    def _error_code(response) -> str:
        payload = response.json()
        assert set(payload) == {"detail"}
        assert set(payload["detail"]) == {"error"}
        assert set(payload["detail"]["error"]) == {"code", "message"}
        return payload["detail"]["error"]["code"]

    # 401 -- identity missing / unknown (API dependency)
    missing = await client.patch(
        f"/tasks/{task_id}/status", json={"status": "in_progress"}
    )
    assert missing.status_code == 401
    assert _error_code(missing) == "MISSING_USER_HEADER"

    unknown = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": str(uuid.uuid4())},
    )
    assert unknown.status_code == 401
    assert _error_code(unknown) == "CURRENT_USER_NOT_FOUND"

    # 403 -- RBAC decision made in the service
    forbidden = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": stranger_id},
    )
    assert forbidden.status_code == 403
    assert _error_code(forbidden) == "STATUS_CHANGE_FORBIDDEN"

    # 404 -- task lookup outcome
    not_found = await client.patch(
        f"/tasks/{uuid.uuid4()}/status",
        json={"status": "in_progress"},
        headers={"X-User-ID": actor_id},
    )
    assert not_found.status_code == 404
    assert _error_code(not_found) == "TASK_NOT_FOUND"

    # 409 -- workflow verdict
    conflict = await client.patch(
        f"/tasks/{task_id}/status",
        json={"status": "done"},
        headers={"X-User-ID": actor_id},
    )
    assert conflict.status_code == 409
    assert _error_code(conflict) == "INVALID_STATUS_TRANSITION"


# ---------------------------------------------------------------------------
# 3. The HTTP layer only translates -- the workflow makes the decision
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_follows_workflow_when_workflow_rejects_valid_move(
    client: AsyncClient, test_session: AsyncSession, monkeypatch
):
    """Workflow says no to todo -> in_progress -> the API returns 409.

    If the route implemented its own rules, a normally-valid move would still
    return 200 regardless of the workflow's verdict.
    """
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    def _reject(cls, current, target):  # noqa: ARG001
        raise InvalidTransitionError(
            current=current, target=target, allowed=frozenset()
        )

    with monkeypatch.context() as m:
        m.setattr(TaskStatusWorkflow, "validate", classmethod(_reject))
        response = await client.patch(
            f"/tasks/{task_id}/status",
            json={"status": "in_progress"},
            headers={"X-User-ID": actor_id},
        )

    assert response.status_code == 409
    assert response.json()["detail"]["error"]["code"] == "INVALID_STATUS_TRANSITION"
    # The route did not "know better" than the workflow
    assert await _db_status(test_session, task_uuid) == TaskStatus.TODO
    assert await _counts(test_session, task_uuid) == {"history": 0, "activity": 0}


@pytest.mark.asyncio
async def test_api_follows_workflow_when_workflow_accepts_invalid_move(
    client: AsyncClient, test_session: AsyncSession, monkeypatch
):
    """Workflow says yes to todo -> done -> the API returns 200.

    The route is not enforcing the transition graph itself: swapping the
    workflow's verdict changes the HTTP outcome and the persisted state.
    """
    actor_id = await _create_user(client)
    project_id = await _create_project(client, actor_id)
    task_id = await _create_task(client, project_id, actor_id)
    task_uuid = uuid.UUID(task_id)

    with monkeypatch.context() as m:
        m.setattr(
            TaskStatusWorkflow,
            "validate",
            classmethod(lambda _cls, _current, _target: None),
        )
        response = await client.patch(
            f"/tasks/{task_id}/status",
            json={"status": "done"},
            headers={"X-User-ID": actor_id},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "done"
    assert await _db_status(test_session, task_uuid) == TaskStatus.DONE
    assert await _counts(test_session, task_uuid) == {"history": 1, "activity": 1}
