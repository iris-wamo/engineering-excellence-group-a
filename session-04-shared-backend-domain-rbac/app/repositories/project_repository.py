from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.roles import ProjectRole
from app.models.project import Project, ProjectStatus
from app.models.project_member import ProjectMember
from app.models.user import User


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
        member_user_id: UUID | None = None,
    ) -> tuple[list[Project], int]:
        """Fetch paginated list of projects with optional filters.

        ``member_user_id`` limits the result to projects that user belongs to.
        """
        query = select(Project)

        if project_status:
            query = query.where(Project.status == project_status)

        if owner_id:
            query = query.where(Project.owner_id == owner_id)

        if member_user_id:
            query = query.where(
                Project.id.in_(ProjectRepository.project_ids_for_user(member_user_id))
            )

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
    def project_ids_for_user(user_id: UUID):
        """Subquery of the ids of every project ``user_id`` belongs to."""
        return select(ProjectMember.project_id).where(ProjectMember.user_id == user_id)

    @staticmethod
    async def get_member_role(
        db: AsyncSession, project_id: UUID, user_id: UUID
    ) -> str | None:
        """Return the user's member_role in the project, or None if not a member."""
        result = await db.execute(
            select(ProjectMember.member_role).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_membership(
        db: AsyncSession, project_id: UUID, user_id: UUID
    ) -> ProjectMember | None:
        """Fetch the membership row for a user in a project."""
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_members(
        db: AsyncSession, project_id: UUID
    ) -> list[tuple[ProjectMember, User]]:
        """Return every membership in a project together with its user."""
        result = await db.execute(
            select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id)
            .order_by(ProjectMember.member_role, User.username)
        )
        return [(member, user) for member, user in result.all()]

    @staticmethod
    def stage_create(db: AsyncSession, **kwargs) -> Project:
        """Stage a new project in the session without committing."""
        project = Project(**kwargs)
        db.add(project)
        return project

    @staticmethod
    def stage_add_member(
        db: AsyncSession, *, project_id: UUID, user_id: UUID, member_role: str
    ) -> ProjectMember:
        """Stage a new membership row without committing."""
        member = ProjectMember(
            project_id=project_id, user_id=user_id, member_role=member_role
        )
        db.add(member)
        return member

    @staticmethod
    async def stage_remove_member(db: AsyncSession, member: ProjectMember) -> None:
        """Stage deletion of a membership row without committing."""
        await db.delete(member)

    @staticmethod
    async def downgrade_managerships(db: AsyncSession, user_id: UUID) -> None:
        """Turn every manager membership of ``user_id`` into a member one (no commit)."""
        await db.execute(
            update(ProjectMember)
            .where(
                ProjectMember.user_id == user_id,
                ProjectMember.member_role == ProjectRole.MANAGER,
            )
            .values(member_role=ProjectRole.MEMBER)
        )

    @staticmethod
    async def create(db: AsyncSession, **kwargs) -> Project:
        """Create and persist a new project entity in the database."""
        project = Project(**kwargs)
        db.add(project)
        await db.commit()
        await db.refresh(project)
        return project
