from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, ProjectStatus


class ProjectRepository:
    """Repository handling database operations for the Project entity."""

    @staticmethod
    async def get_by_id(db: AsyncSession, project_id: UUID) -> Project | None:
        """Fetch project by UUID primary key."""
        result = await db.execute(select(Project).where(Project.id == project_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_all(
        db: AsyncSession,
        *,
        limit: int = 10,
        offset: int = 0,
        project_status: ProjectStatus | None = None,
        owner_id: UUID | None = None,
    ) -> tuple[list[Project], int]:
        """Fetch paginated list of projects with optional filters."""
        query = select(Project)

        if project_status:
            query = query.where(Project.status == project_status)

        if owner_id:
            query = query.where(Project.owner_id == owner_id)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total_result = await db.execute(count_query)
        total = total_result.scalar_one()

        # Apply pagination
        query = query.offset(offset).limit(limit)
        result = await db.execute(query)
        projects = list(result.scalars().all())

        return projects, total

    @staticmethod
    async def create(db: AsyncSession, **kwargs) -> Project:
        """Create and persist a new project entity in the database."""
        project = Project(**kwargs)
        db.add(project)
        await db.commit()
        await db.refresh(project)
        return project
