from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies.deps import PaginationParams, SessionDep
from app.models.project import ProjectStatus
from app.schemas.project import ProjectCreate, ProjectListResponse, ProjectResponse
from app.services.project_service import ProjectService

router = APIRouter(
    prefix="/projects",
    tags=["Projects"],
)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new project",
)
async def create_project(
    payload: ProjectCreate,
    db: SessionDep,
) -> ProjectResponse:
    """POST /projects - Create a new project."""
    project = await ProjectService.create_project(db, payload)
    return ProjectResponse.model_validate(project)


@router.get(
    "",
    response_model=ProjectListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all projects",
    description="Retrieve a paginated list of projects with optional filters.",
)
async def list_projects(
    db: SessionDep,
    pagination: PaginationParams = Depends(),
    project_status: ProjectStatus | None = Query(None, description="Filter by status"),
    owner_id: UUID | None = Query(None, description="Filter by owner ID"),
) -> ProjectListResponse:
    """GET /projects - Paginated project list with optional filters."""
    projects, total = await ProjectService.get_all_projects(
        db,
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
    description="Fetch details for a specific project by UUID.",
)
async def get_project(
    project_id: UUID,
    db: SessionDep,
) -> ProjectResponse:
    """GET /projects/{project_id} - Retrieve project by UUID."""
    project = await ProjectService.get_project(db, project_id)
    return ProjectResponse.model_validate(project)
