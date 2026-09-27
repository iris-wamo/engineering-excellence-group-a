from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ProjectNotFoundError
from app.models.project import Project, ProjectStatus
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate
from app.services.user_service import UserService


class ProjectService:
    """Business logic service layer for Project management."""

    @staticmethod
    async def create_project(db: AsyncSession, payload: ProjectCreate) -> Project:
        """Create a new project with the provided details."""
        # Validate that the owner exists
        await UserService.get_user(db, payload.owner_id)

        data = payload.model_dump()

        # Strip timezone info to match DB column type (TIMESTAMP WITHOUT TIME ZONE)
        if data.get("deadline") and data["deadline"].tzinfo is not None:
            data["deadline"] = data["deadline"].replace(tzinfo=None)

        return await ProjectRepository.create(db, **data)

    @staticmethod
    async def get_all_projects(
        db: AsyncSession,
        *,
        page: int = 1,
        page_size: int = 10,
        project_status: ProjectStatus | None = None,
        owner_id: UUID | None = None,
    ) -> tuple[list[Project], int]:
        """Fetch a paginated list of projects with optional filters."""
        offset = (page - 1) * page_size

        return await ProjectRepository.get_all(
            db,
            limit=page_size,
            offset=offset,
            project_status=project_status,
            owner_id=owner_id,
        )

    @staticmethod
    async def get_project(db: AsyncSession, project_id: UUID) -> Project:
        """Fetch a project by UUID or raise ProjectNotFoundError."""
        project = await ProjectRepository.get_by_id(db, project_id)
        if project is None:
            raise ProjectNotFoundError()

        return project
