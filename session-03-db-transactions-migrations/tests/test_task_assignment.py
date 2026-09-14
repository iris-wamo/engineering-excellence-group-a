import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies.deps import get_db
from app.core.config import settings
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.notification import Notification
from app.models.task import Task, TaskStatus
from app.models.task_assignment_history import TaskAssignmentHistory
from app.models.task_status_history import TaskStatusHistory


@pytest_asyncio.fixture
async def test_session():
    """Provide a dedicated async session for direct DB assertions."""
    engine = create_async_engine(settings.test_database_url, echo=False)
    session_factory = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


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


async def _create_user(client: AsyncClient, name_prefix: str = "User") -> str:
    unique_id = str(uuid.uuid4())[:8]
    payload = {
        "name": f"{name_prefix} {unique_id}",
        "username": f"user_{unique_id}",
        "email": f"user_{unique_id}@example.com",
        "password": "SecurePassword123!",
    }
    response = await client.post("/users", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


async def _create_project(client: AsyncClient, owner_id: str) -> str:
    unique_id = str(uuid.uuid4())[:8]
    payload = {
        "title": f"Assignment Test Project {unique_id}",
        "slug": f"test-project-{unique_id}",
        "description": "Project for assignment transaction testing",
        "priority": "MEDIUM",
        "status": "ACTIVE",
        "owner_id": owner_id,
    }
    response = await client.post("/projects", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


async def _create_task(
    client: AsyncClient, project_id: str, assignee_id: str | None = None
) -> str:
    payload = {
        "title": "Implement Transaction Safety",
        "description": "Ensure task assignment flow is fully atomic",
        "project_id": project_id,
        "assignee_id": assignee_id,
        "priority": "high",
        "status": "todo",
    }
    response = await client.post("/tasks", json=payload)
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_assign_task_success_all_5_records_created(
    client: AsyncClient, test_session: AsyncSession
):
    """Test full atomic task assignment flow creates all 5 related records."""
    assigner_id = await _create_user(client, "Lead Dev")
    assignee_id = await _create_user(client, "Backend Dev")
    project_id = await _create_project(client, assigner_id)
    task_id = await _create_task(client, project_id)

    payload = {
        "assignee_id": assignee_id,
        "assigned_by_id": assigner_id,
        "new_status": "in_progress",
        "comment": "Assigned for Sprint 3 critical path",
    }

    response = await client.post(f"/tasks/{task_id}/assign", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert (
        data["message"]
        == "Task assigned successfully within atomic transaction boundary"
    )
    assert data["task"]["id"] == task_id
    assert data["task"]["assignee_id"] == assignee_id
    assert data["task"]["status"] == "in_progress"

    # Verify assignment history in response
    assert data["assignment_history"]["task_id"] == task_id
    assert data["assignment_history"]["previous_assignee_id"] is None
    assert data["assignment_history"]["new_assignee_id"] == assignee_id
    assert data["assignment_history"]["assigned_by_id"] == assigner_id

    # Verify status history in response
    assert data["status_history"]["task_id"] == task_id
    assert data["status_history"]["previous_status"] == "todo"
    assert data["status_history"]["new_status"] == "in_progress"
    assert data["status_history"]["changed_by_id"] == assigner_id

    # Verify activity log in response
    assert data["activity_log"]["task_id"] == task_id
    assert data["activity_log"]["actor_id"] == assigner_id
    assert data["activity_log"]["action"] == "task.assigned"
    assert (
        data["activity_log"]["details"]["comment"]
        == "Assigned for Sprint 3 critical path"
    )

    # Verify notification in response
    assert data["notification"]["recipient_id"] == assignee_id
    assert data["notification"]["task_id"] == task_id
    assert data["notification"]["is_read"] is False
    assert "Implement Transaction Safety" in data["notification"]["message"]

    # Verify database state directly via independent session
    task_uuid = uuid.UUID(task_id)
    db_task = (
        await test_session.execute(select(Task).where(Task.id == task_uuid))
    ).scalar_one()
    assert db_task.assigned_to == uuid.UUID(assignee_id)
    assert db_task.assigned_by == uuid.UUID(assigner_id)
    assert db_task.status == TaskStatus.IN_PROGRESS

    # Direct query for assignment history
    assign_hist = (
        (
            await test_session.execute(
                select(TaskAssignmentHistory).where(
                    TaskAssignmentHistory.task_id == task_uuid
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(assign_hist) == 1
    assert assign_hist[0].new_assignee_id == uuid.UUID(assignee_id)
    assert assign_hist[0].previous_assignee_id is None

    # Direct query for status history
    status_hist = (
        (
            await test_session.execute(
                select(TaskStatusHistory).where(TaskStatusHistory.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert len(status_hist) == 1
    assert status_hist[0].previous_status == TaskStatus.TODO
    assert status_hist[0].new_status == TaskStatus.IN_PROGRESS

    # Direct query for activity log
    activities = (
        (
            await test_session.execute(
                select(ActivityLog).where(ActivityLog.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert len(activities) == 1
    assert activities[0].action == "task.assigned"

    # Direct query for notification
    notifications = (
        (
            await test_session.execute(
                select(Notification).where(Notification.task_id == task_uuid)
            )
        )
        .scalars()
        .all()
    )
    assert len(notifications) == 1
    assert notifications[0].recipient_id == uuid.UUID(assignee_id)


@pytest.mark.asyncio
async def test_reassign_task_tracks_previous_assignee(client: AsyncClient):
    """Test re-assigning a task records the old assignee as previous_assignee_id."""
    lead_id = await _create_user(client, "Lead")
    dev_a_id = await _create_user(client, "Dev A")
    dev_b_id = await _create_user(client, "Dev B")
    project_id = await _create_project(client, lead_id)
    task_id = await _create_task(client, project_id, assignee_id=dev_a_id)

    # Initial assignment is Dev A, now reassign to Dev B
    reassign_payload = {
        "assignee_id": dev_b_id,
        "assigned_by_id": lead_id,
        "comment": "Transferring task ownership to Dev B",
    }
    response = await client.post(f"/tasks/{task_id}/assign", json=reassign_payload)
    assert response.status_code == 200

    data = response.json()
    assert data["assignment_history"]["previous_assignee_id"] == dev_a_id
    assert data["assignment_history"]["new_assignee_id"] == dev_b_id
    assert data["task"]["assignee_id"] == dev_b_id


@pytest.mark.asyncio
async def test_assign_task_without_status_change_omits_status_history(
    client: AsyncClient,
):
    """Test assigning a task without status change does not generate a status history record."""
    lead_id = await _create_user(client, "Lead")
    dev_id = await _create_user(client, "Dev")
    project_id = await _create_project(client, lead_id)
    task_id = await _create_task(client, project_id)

    payload = {
        "assignee_id": dev_id,
        "assigned_by_id": lead_id,
    }
    response = await client.post(f"/tasks/{task_id}/assign", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["status_history"] is None


@pytest.mark.asyncio
async def test_assign_task_missing_task_returns_404(client: AsyncClient):
    """Test assigning to a non-existent task returns HTTP 404."""
    user_id = await _create_user(client)
    fake_task_id = str(uuid.uuid4())
    payload = {
        "assignee_id": user_id,
        "assigned_by_id": user_id,
    }
    response = await client.post(f"/tasks/{fake_task_id}/assign", json=payload)
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "TASK_NOT_FOUND"


@pytest.mark.asyncio
async def test_assign_task_missing_assignee_returns_404(client: AsyncClient):
    """Test assigning to a non-existent assignee returns HTTP 404."""
    lead_id = await _create_user(client, "Lead")
    project_id = await _create_project(client, lead_id)
    task_id = await _create_task(client, project_id)

    fake_assignee_id = str(uuid.uuid4())
    payload = {
        "assignee_id": fake_assignee_id,
        "assigned_by_id": lead_id,
    }
    response = await client.post(f"/tasks/{task_id}/assign", json=payload)
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "ASSIGNEE_NOT_FOUND"


@pytest.mark.asyncio
async def test_assign_task_missing_assigned_by_returns_404(client: AsyncClient):
    """Test assigning with a non-existent assigner returns HTTP 404."""
    dev_id = await _create_user(client, "Dev")
    project_id = await _create_project(client, dev_id)
    task_id = await _create_task(client, project_id)

    fake_assigner_id = str(uuid.uuid4())
    payload = {
        "assignee_id": dev_id,
        "assigned_by_id": fake_assigner_id,
    }
    response = await client.post(f"/tasks/{task_id}/assign", json=payload)
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "ASSIGNED_BY_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_step", [1, 2, 3, 4, 5])
async def test_assign_task_atomic_rollback_guarantee_on_failure(
    client: AsyncClient, test_session: AsyncSession, fail_step: int
):
    """
    CRITICAL TRANSACTION SAFETY TEST:
    Prove that if any step in the 5-step assignment flow fails (steps 1 through 5),
    the entire transaction is rolled back:
    - Task assignee remains unmodified.
    - Zero assignment history rows added.
    - Zero status history rows added.
    - Zero activity log rows added.
    - Zero notification rows added.
    """
    lead_id = await _create_user(client, "Lead")
    dev_id = await _create_user(client, "Dev")
    project_id = await _create_project(client, lead_id)
    task_id = await _create_task(client, project_id)
    task_uuid = uuid.UUID(task_id)

    # Initial state capture
    task_before = (
        await test_session.execute(select(Task).where(Task.id == task_uuid))
    ).scalar_one()
    initial_assignee = task_before.assigned_to
    initial_status = task_before.status
    initial_updated_at = task_before.updated_at

    assign_hist_count_before = (
        await test_session.execute(
            select(func.count(TaskAssignmentHistory.id)).where(
                TaskAssignmentHistory.task_id == task_uuid
            )
        )
    ).scalar_one()

    status_hist_count_before = (
        await test_session.execute(
            select(func.count(TaskStatusHistory.id)).where(
                TaskStatusHistory.task_id == task_uuid
            )
        )
    ).scalar_one()

    activity_count_before = (
        await test_session.execute(
            select(func.count(ActivityLog.id)).where(ActivityLog.task_id == task_uuid)
        )
    ).scalar_one()

    notification_count_before = (
        await test_session.execute(
            select(func.count(Notification.id)).where(Notification.task_id == task_uuid)
        )
    ).scalar_one()

    # Trigger assignment with simulated failure at specified step
    payload = {
        "assignee_id": dev_id,
        "assigned_by_id": lead_id,
        "new_status": "in_progress",
        "comment": "Testing rollback guarantee",
    }
    response = await client.post(
        f"/tasks/{task_id}/assign?simulate_failure=true&simulate_failure_step={fail_step}",
        json=payload,
    )
    assert response.status_code == 500
    assert response.json()["detail"]["error"]["code"] == "SIMULATED_TRANSACTION_FAILURE"

    # PROVE ROLLBACK: Verify independent database session shows zero modifications
    test_session.expire_all()
    task_after = (
        await test_session.execute(select(Task).where(Task.id == task_uuid))
    ).scalar_one()

    # 1. Task assignee unchanged
    assert task_after.assigned_to == initial_assignee
    # 2. Task status unchanged
    assert task_after.status == initial_status
    # 3. Task updated_at unchanged
    assert task_after.updated_at == initial_updated_at

    # 4. Zero assignment history rows added
    assign_hist_count_after = (
        await test_session.execute(
            select(func.count(TaskAssignmentHistory.id)).where(
                TaskAssignmentHistory.task_id == task_uuid
            )
        )
    ).scalar_one()
    assert assign_hist_count_after == assign_hist_count_before

    # 5. Zero status history rows added
    status_hist_count_after = (
        await test_session.execute(
            select(func.count(TaskStatusHistory.id)).where(
                TaskStatusHistory.task_id == task_uuid
            )
        )
    ).scalar_one()
    assert status_hist_count_after == status_hist_count_before

    # 6. Zero activity log rows added
    activity_count_after = (
        await test_session.execute(
            select(func.count(ActivityLog.id)).where(ActivityLog.task_id == task_uuid)
        )
    ).scalar_one()
    assert activity_count_after == activity_count_before

    # 7. Zero notification rows added
    notification_count_after = (
        await test_session.execute(
            select(func.count(Notification.id)).where(Notification.task_id == task_uuid)
        )
    ).scalar_one()
    assert notification_count_after == notification_count_before


@pytest.mark.asyncio
async def test_get_task_history_activity_and_notifications_endpoints(
    client: AsyncClient,
):
    """Test GET endpoints for audit history, activities, and notifications."""
    lead_id = await _create_user(client, "Lead")
    dev_a_id = await _create_user(client, "Dev A")
    dev_b_id = await _create_user(client, "Dev B")
    project_id = await _create_project(client, lead_id)
    task_id = await _create_task(client, project_id)

    # 1. Assign to Dev A with status transition
    await client.post(
        f"/tasks/{task_id}/assign",
        json={
            "assignee_id": dev_a_id,
            "assigned_by_id": lead_id,
            "new_status": "in_progress",
            "comment": "Initial sprint assignment",
        },
    )

    # 2. Reassign to Dev B
    await client.post(
        f"/tasks/{task_id}/assign",
        json={
            "assignee_id": dev_b_id,
            "assigned_by_id": lead_id,
            "comment": "Reassigned to Dev B",
        },
    )

    # GET /tasks/{task_id}/history
    hist_resp = await client.get(f"/tasks/{task_id}/history")
    assert hist_resp.status_code == 200
    hist_data = hist_resp.json()
    assert len(hist_data["assignments"]) == 2
    assert len(hist_data["statuses"]) == 1

    # GET /tasks/{task_id}/activity
    act_resp = await client.get(f"/tasks/{task_id}/activity")
    assert act_resp.status_code == 200
    act_data = act_resp.json()
    assert len(act_data) == 2
    assert act_data[0]["action"] == "task.assigned"

    # GET /tasks/{task_id}/notifications
    notif_resp = await client.get(f"/tasks/{task_id}/notifications")
    assert notif_resp.status_code == 200
    notif_data = notif_resp.json()
    assert len(notif_data) == 2
