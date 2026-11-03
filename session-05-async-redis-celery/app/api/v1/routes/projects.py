from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.dependencies.deps import PaginationParams, SessionDep
from app.auth.dependencies import (
    AdminDep,
    CurrentUserDep,
    get_current_user,
    require_roles,
)
from app.auth.roles import UserRole
from app.models.project import ProjectStatus
from app.models.user import User
from app.schemas.project import (
    ProjectCreate,
    ProjectListResponse,
    ProjectMemberAdd,
    ProjectMemberResponse,
    ProjectResponse,
)
from app.services.project_service import ProjectService

router = APIRouter(
    prefix="/projects",
    tags=["Projects"],
    dependencies=[Depends(get_current_user)],
)

ProjectCreatorDep = Annotated[
    User, Depends(require_roles(UserRole.ADMIN, UserRole.MANAGER))
]


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
    description=(
        "Admins and managers only (members 403). A manager becomes the "
        "project's owner and manager. An admin may pass `owner_id` to hand the "
        "project to a manager-role user."
    ),
)
async def create_project(
    payload: ProjectCreate,
    db: SessionDep,
    creator: ProjectCreatorDep,
) -> ProjectResponse:
    """POST /projects - Create a new project."""
    project = await ProjectService.create_project(db, payload, actor=creator)
    return ProjectResponse.model_validate(project)


@router.get(
    "",
    response_model=ProjectListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all projects",
    description=(
        "Retrieve a paginated list of projects with optional filters. Admins "
        "see every project; everyone else sees the projects they belong to."
    ),
)
async def list_projects(
    db: SessionDep,
    current_user: CurrentUserDep,
    pagination: PaginationParams = Depends(),
    project_status: ProjectStatus | None = Query(None, description="Filter by status"),
    owner_id: UUID | None = Query(None, description="Filter by owner ID"),
) -> ProjectListResponse:
    """GET /projects - Paginated project list with optional filters."""
    projects, total = await ProjectService.get_all_projects(
        db,
        current_user,
        page=pagination.page,
        page_size=pagination.page_size,
        project_status=project_status,
        owner_id=owner_id,
    )

    return ProjectListResponse(
        items=[ProjectResponse.model_validate(p) for p in projects],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Get project by ID",
    description=(
        "Fetch details for a specific project by UUID. Returns 404 for projects "
        "you do not belong to."
    ),
)
async def get_project(
    project_id: UUID,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> ProjectResponse:
    """GET /projects/{project_id} - Retrieve project by UUID."""
    project = await ProjectService.get_project(db, project_id, current_user)
    return ProjectResponse.model_validate(project)


@router.get(
    "/{project_id}/members",
    response_model=list[ProjectMemberResponse],
    status_code=status.HTTP_200_OK,
    summary="List project members",
    description="Anyone in the project (or an admin) can see who belongs to it.",
)
async def list_project_members(
    project_id: UUID,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> list[ProjectMemberResponse]:
    """GET /projects/{project_id}/members - Project membership list."""
    return await ProjectService.list_members(db, project_id, current_user)


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member to a project",
    description=(
        "Managers of the project and admins only. Adds the user with the "
        "`member` project role (409 if already in the project)."
    ),
)
async def add_project_member(
    project_id: UUID,
    payload: ProjectMemberAdd,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> ProjectMemberResponse:
    """POST /projects/{project_id}/members - Add a project member."""
    return await ProjectService.add_member(
        db, project_id, payload.user_id, current_user
    )


@router.post(
    "/{project_id}/managers",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign a manager to a project (admin)",
    description=(
        "Admin only. Makes a user with the global `manager` role a manager of "
        "this project; an existing member is promoted. A manager can manage "
        "many projects."
    ),
)
async def assign_project_manager(
    project_id: UUID,
    payload: ProjectMemberAdd,
    db: SessionDep,
    _admin: AdminDep,
) -> ProjectMemberResponse:
    """POST /projects/{project_id}/managers - Assign a project manager."""
    return await ProjectService.assign_manager(db, project_id, payload.user_id)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove someone from a project",
    description=(
        "Managers of the project can remove members; only admins can remove a manager."
    ),
)
async def remove_project_member(
    project_id: UUID,
    user_id: UUID,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    """DELETE /projects/{project_id}/members/{user_id} - Remove a member."""
    await ProjectService.remove_member(db, project_id, user_id, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
