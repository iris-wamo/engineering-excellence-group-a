"""Service-level tests for task status transitions: positive and negative.

These bypass HTTP and call ``TaskService.update_task_status`` directly against
the real test database, so they exercise the full service -> workflow ->
repository -> DB path that the API route uses.

Positive cases (every valid workflow transition):
    todo -> in_progress, in_progress -> in_review, in_review -> done
Each asserts: correct status persisted, history created, activity created,
and no unexpected error.

Negative cases: invalid transitions are rejected by the workflow with a
consistent 409 domain error and leave no state behind.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.exceptions import InvalidStatusTransitionError
from app.models.activity_log import ActivityLog
from app.models.project import Project, ProjectPriority, ProjectStatus
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.task_status_history import TaskStatusHistory
from app.models.user import User
from app.schemas.task import TaskStatusUpdate, TaskStatusValue
from app.services.task_service import TaskService
from app.workflows.task_status_workflow import InvalidTransitionError

# API value -> persisted model value (mirrors the service mapping)
_API_TO_MODEL = {
    TaskStatusValue.TODO: TaskStatus.TODO,
    TaskStatusValue.IN_PROGRESS: TaskStatus.IN_PROGRESS,
    TaskStatusValue.IN_REVIEW: TaskStatus.IN_REVIEW,
    TaskStatusValue.DONE: TaskStatus.DONE,
}


def _make_session_factory():
    engine = create_async_engine(settings.test_database_url, echo=False)
    factory = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


@pytest_asyncio.fixture
async def db():
    """Session used to seed data and to call the service."""
    engine, factory = _make_session_factory()
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def verifier():
    """Separate session/connection used to confirm what was committed."""
    engine, factory = _make_session_factory()
    async with factory() as session:
        yield session
    await engine.dispose()


async def _seed_task(session: AsyncSession, *, status: TaskStatus) -> tuple[User, Task]:
    """Create a user (assignee) + project + task directly through the ORM."""
    tag = str(uuid.uuid4())[:8]
    user = User(
        name=f"Service Tester {tag}",
        username=f"service_tester_{tag}",
        email=f"service_tester_{tag}@example.com",
        password_hash="not-a-real-hash",
        role="user",
    )
    session.add(user)
    await session.flush()

    project = Project(
        title=f"Service Test Project {tag}",
        priority=ProjectPriority.MEDIUM,
        status=ProjectStatus.ACTIVE,
        owner_id=user.id,
    )
    session.add(project)
    await session.flush()

    task = Task(
        project_id=project.id,
        assigned_to=user.id,
        title="Service transition task",
        priority=TaskPriority.MEDIUM,
        status=status,
    )
    session.add(task)
    await session.commit()

    return user, task


async def _fresh_task_status(session: AsyncSession, task_id: uuid.UUID) -> TaskStatus:
    session.expire_all()
    return (
        await session.execute(select(Task.status).where(Task.id == task_id))
    ).scalar_one()


async def _history_rows(
    session: AsyncSession, task_id: uuid.UUID
) -> list[tuple[TaskStatus | None, TaskStatus, uuid.UUID]]:
    """Snapshot history as plain tuples (avoids lazy loads after expiry)."""
    session.expire_all()
    rows = (
        (
            await session.execute(
                select(TaskStatusHistory)
                .where(TaskStatusHistory.task_id == task_id)
                .order_by(TaskStatusHistory.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [(r.previous_status, r.new_status, r.changed_by_id) for r in rows]


async def _activity_rows(
    session: AsyncSession, task_id: uuid.UUID
) -> list[tuple[str, uuid.UUID, dict | None]]:
    """Snapshot activity as plain tuples (avoids lazy loads after expiry)."""
    session.expire_all()
    rows = (
        (
            await session.execute(
                select(ActivityLog)
                .where(ActivityLog.task_id == task_id)
                .order_by(ActivityLog.created_at)
            )
        )
        .scalars()
        .all()
    )
    return [(r.action, r.actor_id, r.details) for r in rows]


# ---------------------------------------------------------------------------
# POSITIVE: every valid transition of the workflow
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start_status", "target"),
    [
        (TaskStatus.TODO, TaskStatusValue.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatusValue.IN_REVIEW),
        (TaskStatus.IN_REVIEW, TaskStatusValue.DONE),
    ],
    ids=[
        "todo_to_in_progress",
        "in_progress_to_review",
        "review_to_done",
    ],
)
@pytest.mark.asyncio
async def test_valid_transition_succeeds(
    db: AsyncSession,
    verifier: AsyncSession,
    start_status: TaskStatus,
    target: TaskStatusValue,
):
    """The service accepts the transition and persists status + audit trail."""
    user, task = await _seed_task(db, status=start_status)
    expected = _API_TO_MODEL[target]

    # Must not raise: no unexpected error for a valid transition
    result = await TaskService.update_task_status(
        db, task.id, TaskStatusUpdate(status=target), actor=user
    )

    # 1. Correct status returned and persisted (verified in another session)
    assert result.status == expected
    assert await _fresh_task_status(verifier, task.id) == expected

    # 2. History created for this exact transition
    history = await _history_rows(verifier, task.id)
    assert history == [(start_status, expected, user.id)]

    # 3. Activity created, describing the same transition
    activities = await _activity_rows(verifier, task.id)
    assert len(activities) == 1
    action, actor_id, details = activities[0]
    assert action == "task.status_changed"
    assert actor_id == user.id
    assert details == {
        "previous_status": start_status.value,
        "new_status": expected.value,
    }


@pytest.mark.asyncio
async def test_full_workflow_through_service(db: AsyncSession, verifier: AsyncSession):
    """todo -> in_progress -> in_review -> done, one audit pair per step."""
    user, task = await _seed_task(db, status=TaskStatus.TODO)

    steps = [
        (TaskStatusValue.IN_PROGRESS, TaskStatus.IN_PROGRESS),
        (TaskStatusValue.IN_REVIEW, TaskStatus.IN_REVIEW),
        (TaskStatusValue.DONE, TaskStatus.DONE),
    ]

    for index, (target, expected) in enumerate(steps, start=1):
        await TaskService.update_task_status(
            db, task.id, TaskStatusUpdate(status=target), actor=user
        )

        assert await _fresh_task_status(verifier, task.id) == expected
        history = await _history_rows(verifier, task.id)
        activities = await _activity_rows(verifier, task.id)
        assert len(history) == index
        assert len(activities) == index
        assert history[-1][1] == expected
        assert activities[-1][0] == "task.status_changed"

    # Final persisted state and full audit chain
    assert await _fresh_task_status(verifier, task.id) == TaskStatus.DONE
    history = await _history_rows(verifier, task.id)
    assert history == [
        (TaskStatus.TODO, TaskStatus.IN_PROGRESS, user.id),
        (TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW, user.id),
        (TaskStatus.IN_REVIEW, TaskStatus.DONE, user.id),
    ]


@pytest.mark.asyncio
async def test_same_status_is_a_noop_without_audit_rows(
    db: AsyncSession, verifier: AsyncSession
):
    """Re-sending the current status succeeds but writes nothing."""
    user, task = await _seed_task(db, status=TaskStatus.IN_PROGRESS)

    result = await TaskService.update_task_status(
        db,
        task.id,
        TaskStatusUpdate(status=TaskStatusValue.IN_PROGRESS),
        actor=user,
    )

    assert result.status == TaskStatus.IN_PROGRESS
    assert await _fresh_task_status(verifier, task.id) == TaskStatus.IN_PROGRESS
    assert await _history_rows(verifier, task.id) == []
    assert await _activity_rows(verifier, task.id) == []


# ---------------------------------------------------------------------------
# NEGATIVE: invalid transitions are rejected and leave no state
# ---------------------------------------------------------------------------

# Every invalid transition required by the domain rules (skips + backwards +
# moves out of terminal states).
_INVALID_TRANSITIONS = [
    (TaskStatus.TODO, TaskStatusValue.IN_REVIEW, "todo_to_review"),
    (TaskStatus.TODO, TaskStatusValue.DONE, "todo_to_done"),
    (TaskStatus.IN_PROGRESS, TaskStatusValue.DONE, "in_progress_to_done"),
    (
        TaskStatus.IN_REVIEW,
        TaskStatusValue.IN_PROGRESS,
        "review_to_in_progress",
    ),
    (TaskStatus.IN_REVIEW, TaskStatusValue.TODO, "review_to_todo"),
    (TaskStatus.DONE, TaskStatusValue.TODO, "done_to_todo"),
    (TaskStatus.DONE, TaskStatusValue.IN_PROGRESS, "done_to_in_progress"),
    (TaskStatus.DONE, TaskStatusValue.IN_REVIEW, "done_to_review"),
    (TaskStatus.IN_PROGRESS, TaskStatusValue.TODO, "in_progress_to_todo"),
]


@pytest.mark.parametrize(
    ("start_status", "target", "_case"),
    _INVALID_TRANSITIONS,
    ids=[case for _, _, case in _INVALID_TRANSITIONS],
)
@pytest.mark.asyncio
async def test_invalid_transition_rejected_without_side_effects(
    db: AsyncSession,
    verifier: AsyncSession,
    start_status: TaskStatus,
    target: TaskStatusValue,
    _case: str,
):
    """Invalid moves fail with the consistent 409 error and persist nothing."""
    user, task = await _seed_task(db, status=start_status)

    # Snapshot the trail before the attempt (should be empty for a fresh task)
    history_before = await _history_rows(verifier, task.id)
    activity_before = await _activity_rows(verifier, task.id)

    with pytest.raises(InvalidStatusTransitionError) as exc_info:
        await TaskService.update_task_status(
            db, task.id, TaskStatusUpdate(status=target), actor=user
        )

    # 1. Consistent domain error: same type, same code, same detail shape
    error = exc_info.value
    assert error.status_code == 409
    assert set(error.detail["error"]) == {"code", "message"}
    assert error.detail["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert error.detail["error"]["message"] == (
        f"Cannot transition task status from '{start_status.value}' "
        f"to '{_API_TO_MODEL[target].value}'"
    )
    # Translated from the workflow's own domain error (rules live there)
    assert isinstance(error.__cause__, InvalidTransitionError)

    # 2. Task status remains unchanged (in memory and in the database)
    assert task.status == start_status
    assert await _fresh_task_status(verifier, task.id) == start_status

    # 3. No incorrect history record was created
    assert await _history_rows(verifier, task.id) == history_before

    # 4. No incorrect activity record was created
    assert await _activity_rows(verifier, task.id) == activity_before

    # 5. No partial DB state remains at all
    assert history_before == []
    assert activity_before == []
    assert await _history_rows(verifier, task.id) == []
    assert await _activity_rows(verifier, task.id) == []


@pytest.mark.asyncio
async def test_invalid_transition_leaves_existing_audit_trail_untouched(
    db: AsyncSession, verifier: AsyncSession
):
    """A rejected move must not add to (or reorder) an existing trail."""
    user, task = await _seed_task(db, status=TaskStatus.TODO)

    # One legitimate transition -> exactly one history + one activity row
    await TaskService.update_task_status(
        db,
        task.id,
        TaskStatusUpdate(status=TaskStatusValue.IN_PROGRESS),
        actor=user,
    )
    history_before = await _history_rows(verifier, task.id)
    activity_before = await _activity_rows(verifier, task.id)
    assert len(history_before) == 1
    assert len(activity_before) == 1

    # in_progress -> done is illegal: nothing may change
    with pytest.raises(InvalidStatusTransitionError):
        await TaskService.update_task_status(
            db,
            task.id,
            TaskStatusUpdate(status=TaskStatusValue.DONE),
            actor=user,
        )

    assert await _fresh_task_status(verifier, task.id) == TaskStatus.IN_PROGRESS
    assert await _history_rows(verifier, task.id) == history_before
    assert await _activity_rows(verifier, task.id) == activity_before


@pytest.mark.asyncio
async def test_every_invalid_transition_uses_the_same_error_contract(db: AsyncSession):
    """Consistency check across all invalid cases: identical error contract."""
    seen: set[tuple[int, str, tuple[str, ...]]] = set()

    for start_status, target, _case in _INVALID_TRANSITIONS:
        user, task = await _seed_task(db, status=start_status)
        with pytest.raises(InvalidStatusTransitionError) as exc_info:
            await TaskService.update_task_status(
                db, task.id, TaskStatusUpdate(status=target), actor=user
            )

        error = exc_info.value
        assert isinstance(error.__cause__, InvalidTransitionError)
        seen.add(
            (
                error.status_code,
                error.detail["error"]["code"],
                tuple(sorted(error.detail["error"])),
            )
        )

    # One and only one contract for every rejection: 409 + code + {code,message}
    assert seen == {(409, "INVALID_STATUS_TRANSITION", ("code", "message"))}
