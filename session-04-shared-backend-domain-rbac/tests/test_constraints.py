import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.activity_log import ActivityLog
from app.models.notification import Notification
from app.models.project import Project, ProjectStatus
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.task_assignment_history import TaskAssignmentHistory
from app.models.user import User


@pytest_asyncio.fixture
async def db_session():
    """Provide an isolated database session for direct SQL and constraint tests."""
    engine = create_async_engine(settings.test_database_url, echo=False)
    session_factory = sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _create_test_user(db: AsyncSession, suffix: str) -> User:
    user = User(
        name=f"Constraint User {suffix}",
        username=f"constraint_user_{suffix}",
        email=f"constraint_{suffix}@example.com",
        password_hash="SecurePassword123!",
        role="user",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _create_test_project(
    db: AsyncSession, owner_id: uuid.UUID, slug: str
) -> Project:
    project = Project(
        title=f"Project {slug}",
        slug=slug,
        description="Constraint test project",
        priority="MEDIUM",
        status=ProjectStatus.ACTIVE,
        owner_id=owner_id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@pytest.mark.asyncio
async def test_db_constraint_unique_user_email(db_session: AsyncSession):
    """Test that Postgres enforces the UNIQUE constraint on user.email."""
    suffix = uuid.uuid4().hex[:8]
    user1 = await _create_test_user(db_session, suffix)

    # Attempt to insert a second user with duplicate email
    duplicate_user = User(
        name="Duplicate Email User",
        username=f"unique_username_{suffix}",
        email=user1.email,  # duplicate email
        password_hash="SecurePassword123!",
        role="user",
    )
    db_session.add(duplicate_user)
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()

    assert (
        "user_email_key" in str(exc_info.value).lower()
        or "unique" in str(exc_info.value).lower()
    )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_db_constraint_unique_user_username(db_session: AsyncSession):
    """Test that Postgres enforces the UNIQUE constraint on user.username."""
    suffix = uuid.uuid4().hex[:8]
    user1 = await _create_test_user(db_session, suffix)

    duplicate_user = User(
        name="Duplicate Username User",
        username=user1.username,  # duplicate username
        email=f"unique_email_{suffix}@example.com",
        password_hash="SecurePassword123!",
        role="user",
    )
    db_session.add(duplicate_user)
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()

    assert (
        "user_username_key" in str(exc_info.value).lower()
        or "unique" in str(exc_info.value).lower()
    )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_db_constraint_unique_project_slug(db_session: AsyncSession):
    """Test that Postgres enforces the UNIQUE constraint on project.slug."""
    suffix = uuid.uuid4().hex[:8]
    user = await _create_test_user(db_session, suffix)
    slug = f"unique-slug-{suffix}"

    await _create_test_project(db_session, user.id, slug)

    # Attempt to create second project with the exact same slug
    duplicate_project = Project(
        title="Duplicate Slug Project",
        slug=slug,
        description="Duplicate slug test",
        priority="MEDIUM",
        status=ProjectStatus.ACTIVE,
        owner_id=user.id,
    )
    db_session.add(duplicate_project)
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()

    assert (
        "project_slug_key" in str(exc_info.value).lower()
        or "unique" in str(exc_info.value).lower()
    )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_db_constraint_foreign_key_task_project(db_session: AsyncSession):
    """Test that Postgres enforces FK integrity: task cannot reference non-existent project."""
    suffix = uuid.uuid4().hex[:8]
    user = await _create_test_user(db_session, suffix)
    non_existent_project_id = uuid.uuid4()

    invalid_task = Task(
        title="Invalid FK Task",
        project_id=non_existent_project_id,
        assigned_to=user.id,
        priority=TaskPriority.MEDIUM,
        status=TaskStatus.TODO,
    )
    db_session.add(invalid_task)
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()

    assert (
        "foreignkey" in str(exc_info.value).lower()
        or "violates foreign key constraint" in str(exc_info.value).lower()
    )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_db_constraint_foreign_key_notification_recipient(
    db_session: AsyncSession,
):
    """Test that Postgres enforces FK integrity on notification recipient."""
    suffix = uuid.uuid4().hex[:8]
    user = await _create_test_user(db_session, suffix)
    project = await _create_test_project(db_session, user.id, f"slug-{suffix}")

    task = Task(
        title="Valid Task",
        project_id=project.id,
        assigned_to=user.id,
        priority=TaskPriority.MEDIUM,
        status=TaskStatus.TODO,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    invalid_notification = Notification(
        recipient_id=uuid.uuid4(),  # non-existent recipient
        task_id=task.id,
        type="test_alert",
        message="Should fail due to FK violation",
        is_read=False,
    )
    db_session.add(invalid_notification)
    with pytest.raises(IntegrityError) as exc_info:
        await db_session.commit()

    assert (
        "foreignkey" in str(exc_info.value).lower()
        or "violates foreign key constraint" in str(exc_info.value).lower()
    )
    await db_session.rollback()


@pytest.mark.asyncio
async def test_cascade_delete_task_removes_dependent_records(db_session: AsyncSession):
    """Test CASCADE delete on task entity deletes associated history and activity logs."""
    suffix = uuid.uuid4().hex[:8]
    user = await _create_test_user(db_session, suffix)
    project = await _create_test_project(db_session, user.id, f"cascade-slug-{suffix}")

    task = Task(
        title="Task to Delete",
        project_id=project.id,
        assigned_to=user.id,
        priority=TaskPriority.MEDIUM,
        status=TaskStatus.TODO,
    )
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)

    # Add assignment history and activity log
    hist = TaskAssignmentHistory(
        task_id=task.id,
        previous_assignee_id=None,
        new_assignee_id=user.id,
        assigned_by_id=user.id,
    )
    act = ActivityLog(
        task_id=task.id,
        actor_id=user.id,
        action="task.created",
        details={"info": "Initial creation"},
    )
    notif = Notification(
        recipient_id=user.id,
        task_id=task.id,
        type="task_assignment",
        message="Assigned",
    )
    db_session.add_all([hist, act, notif])
    await db_session.commit()

    # Delete task
    await db_session.delete(task)
    await db_session.commit()

    # Verify dependent records are cascaded
    remaining_hist = (
        (
            await db_session.execute(
                select(TaskAssignmentHistory).where(
                    TaskAssignmentHistory.task_id == task.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining_hist) == 0

    remaining_act = (
        (
            await db_session.execute(
                select(ActivityLog).where(ActivityLog.task_id == task.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining_act) == 0

    remaining_notif = (
        (
            await db_session.execute(
                select(Notification).where(Notification.task_id == task.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(remaining_notif) == 0
