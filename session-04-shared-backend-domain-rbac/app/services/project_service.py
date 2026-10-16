from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import (
    is_admin,
    require_project_access,
    require_project_manager,
)
from app.auth.roles import ProjectRole, UserRole
from app.core.exceptions import (
    AlreadyProjectMemberError,
    ForbiddenError,
    InvalidRoleAssignmentError,
    ProjectMemberNotFoundError,
    ProjectNotFoundError,
)
from app.models.project import Project, ProjectStatus
from app.models.user import User
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectMemberResponse
from app.services.user_service import UserService


def to_member_response(member_role: str, user: User) -> ProjectMemberResponse:
    return ProjectMemberResponse(
        user_id=user.id,
        name=user.name,
        username=user.username,
        email=user.email,
        role=ProjectRole(member_role),
    )


async def _require_manager_role(db: AsyncSession, user_id: UUID) -> User:
    """Fetch a user who may manage projects (global role ``manager``)."""
    user = await UserService.get_user(db, user_id)
    if user.role != UserRole.MANAGER:
        raise InvalidRoleAssignmentError(
            "Projects can only be managed by users with the manager role"
        )
    return user


class ProjectService:
    """Business logic service layer for Project management."""

    @staticmethod
    async def create_project(
        db: AsyncSession, payload: ProjectCreate, actor: User
    ) -> Project:
        """Create a project and its manager membership in one transaction.

        - Admin: may hand the project to a manager via ``owner_id``; without
          it the admin owns the project and no manager is assigned yet.
        - Manager: always owns and manages the project they create.
        Route-level authorization already rejects members (403).
        """
        manager_id: UUID | None
        if is_admin(actor):
            if payload.owner_id is not None:
                manager = await _require_manager_role(db, payload.owner_id)
                manager_id = manager.id
            else:
                manager_id = None
            owner_id = manager_id or actor.id
        else:
            if payload.owner_id is not None and payload.owner_id != actor.id:
                raise ForbiddenError(
                    "Managers can only create projects that they manage themselves"
                )
            owner_id = manager_id = actor.id

        data = payload.model_dump(exclude={"owner_id"})

        # Strip timezone info to match DB column type (TIMESTAMP WITHOUT TIME ZONE)
        if data.get("deadline") and data["deadline"].tzinfo is not None:
            data["deadline"] = data["deadline"].replace(tzinfo=None)

        try:
            project = ProjectRepository.stage_create(db, owner_id=owner_id, **data)
            await db.flush()
            if manager_id is not None:
                ProjectRepository.stage_add_member(
                    db,
                    project_id=project.id,
                    user_id=manager_id,
                    member_role=ProjectRole.MANAGER,
                )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        await db.refresh(project)
        return project

    @staticmethod
    async def get_all_projects(
        db: AsyncSession,
        actor: User,
        *,
        page: int = 1,
        page_size: int = 10,
        project_status: ProjectStatus | None = None,
        owner_id: UUID | None = None,
    ) -> tuple[list[Project], int]:
        """Admins see every project; everyone else sees projects they belong to."""
        offset = (page - 1) * page_size

        return await ProjectRepository.get_all(
            db,
            limit=page_size,
            offset=offset,
            project_status=project_status,
            owner_id=owner_id,
            member_user_id=None if is_admin(actor) else actor.id,
        )

    @staticmethod
    async def get_project(db: AsyncSession, project_id: UUID, actor: User) -> Project:
        """Fetch a project the actor belongs to (or any, for admins), else 404."""
        await require_project_access(
            db, project_id, actor, not_found=ProjectNotFoundError()
        )
        project = await ProjectRepository.get_by_id(db, project_id)
        if project is None:
            raise ProjectNotFoundError()

        return project

    @staticmethod
    async def list_members(
        db: AsyncSession, project_id: UUID, actor: User
    ) -> list[ProjectMemberResponse]:
        """List a project's members; visible to anyone in the project."""
        await ProjectService.get_project(db, project_id, actor)
        rows = await ProjectRepository.list_members(db, project_id)
        return [to_member_response(m.member_role, u) for m, u in rows]

    @staticmethod
    async def add_member(
        db: AsyncSession, project_id: UUID, user_id: UUID, actor: User
    ) -> ProjectMemberResponse:
        """Add a user to the project as a member (project manager or admin)."""
        await require_project_manager(
            db, project_id, actor, not_found=ProjectNotFoundError()
        )
        if await ProjectRepository.get_by_id(db, project_id) is None:
            raise ProjectNotFoundError()
        user = await UserService.get_user(db, user_id)
        if await ProjectRepository.get_membership(db, project_id, user_id):
            raise AlreadyProjectMemberError()

        try:
            ProjectRepository.stage_add_member(
                db,
                project_id=project_id,
                user_id=user_id,
                member_role=ProjectRole.MEMBER,
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return to_member_response(ProjectRole.MEMBER, user)

    @staticmethod
    async def assign_manager(
        db: AsyncSession, project_id: UUID, user_id: UUID
    ) -> ProjectMemberResponse:
        """Admin only: make a manager-role user a manager of an existing project.

        An existing member is promoted in place; repeating the call is a no-op.
        """
        if await ProjectRepository.get_by_id(db, project_id) is None:
            raise ProjectNotFoundError()
        user = await _require_manager_role(db, user_id)

        membership = await ProjectRepository.get_membership(db, project_id, user_id)
        try:
            if membership is None:
                ProjectRepository.stage_add_member(
                    db,
                    project_id=project_id,
                    user_id=user_id,
                    member_role=ProjectRole.MANAGER,
                )
            else:
                membership.member_role = ProjectRole.MANAGER
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return to_member_response(ProjectRole.MANAGER, user)

    @staticmethod
    async def remove_member(
        db: AsyncSession, project_id: UUID, user_id: UUID, actor: User
    ) -> None:
        """Remove someone from a project.

        Project managers can remove members; only admins can remove a manager.
        """
        access = await require_project_manager(
            db, project_id, actor, not_found=ProjectNotFoundError()
        )
        membership = await ProjectRepository.get_membership(db, project_id, user_id)
        if membership is None:
            raise ProjectMemberNotFoundError()
        if membership.member_role == ProjectRole.MANAGER and not access.is_admin:
            raise ForbiddenError("Only an admin can remove a project manager")

        try:
            await ProjectRepository.stage_remove_member(db, membership)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
