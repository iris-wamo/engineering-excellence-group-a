"""Project-scoped authorization checks used by the service layer.

Rules (see docs/rbac-authorization-matrix.md):
- Admins have full access to every project.
- A user's rights inside a project come from their ``project_member`` row:
  ``manager`` runs the project, ``member`` works on their own tasks.
- Users outside a project get 404 for it and everything in it, so the API
  does not reveal which projects or tasks exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.roles import ProjectRole, UserRole
from app.core.exceptions import ForbiddenError
from app.models.user import User
from app.repositories.project_repository import ProjectRepository


@dataclass(frozen=True)
class ProjectAccess:
    """What the acting user may do inside one project."""

    is_admin: bool
    project_role: ProjectRole | None

    @property
    def can_manage(self) -> bool:
        return self.is_admin or self.project_role == ProjectRole.MANAGER


def is_admin(user: User) -> bool:
    return user.role == UserRole.ADMIN


async def get_project_access(
    db: AsyncSession, project_id: UUID, user: User
) -> ProjectAccess | None:
    """Return the user's access to the project, or None when they have none."""
    if is_admin(user):
        return ProjectAccess(is_admin=True, project_role=None)
    role = await ProjectRepository.get_member_role(db, project_id, user.id)
    if role is None:
        return None
    return ProjectAccess(is_admin=False, project_role=ProjectRole(role))


async def require_project_access(
    db: AsyncSession,
    project_id: UUID,
    user: User,
    *,
    not_found: HTTPException,
) -> ProjectAccess:
    """Any role in the project (or admin); raise ``not_found`` otherwise."""
    access = await get_project_access(db, project_id, user)
    if access is None:
        raise not_found
    return access


async def require_project_manager(
    db: AsyncSession,
    project_id: UUID,
    user: User,
    *,
    not_found: HTTPException,
    message: str = "Only a manager of this project or an admin can do this",
) -> ProjectAccess:
    """Manager of the project (or admin); 404 for outsiders, 403 for members."""
    access = await require_project_access(db, project_id, user, not_found=not_found)
    if not access.can_manage:
        raise ForbiddenError(message)
    return access
