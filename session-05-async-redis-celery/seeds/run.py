from __future__ import annotations

import asyncio

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.models.activity_log import ActivityLog
from app.models.notification import Notification
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.task import Task
from app.models.task_assignment_history import TaskAssignmentHistory
from app.models.task_status_history import TaskStatusHistory
from app.models.user import User
from seeds.projects import PROJECT_MEMBERS, PROJECTS
from seeds.tasks import (
    ACTIVITY_LOGS,
    NOTIFICATIONS,
    TASK_ASSIGNMENT_HISTORY,
    TASK_STATUS_HISTORY,
    TASKS,
)
from seeds.users import USERS


async def seed_all() -> None:
    engine = create_async_engine(settings.DATABASE_URL, echo=False)

    async with AsyncSession(engine) as session, session.begin():
        await session.execute(insert(User.__table__), USERS)
        await session.execute(insert(Project.__table__), PROJECTS)
        await session.execute(insert(ProjectMember.__table__), PROJECT_MEMBERS)
        await session.execute(insert(Task.__table__), TASKS)
        await session.execute(insert(ActivityLog.__table__), ACTIVITY_LOGS)
        await session.execute(insert(Notification.__table__), NOTIFICATIONS)
        await session.execute(
            insert(TaskAssignmentHistory.__table__),
            TASK_ASSIGNMENT_HISTORY,
        )
        await session.execute(
            insert(TaskStatusHistory.__table__),
            TASK_STATUS_HISTORY,
        )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed_all())
    print("Seed data inserted successfully.")
