from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies.deps import PaginationParams, SessionDep
from app.schemas.user import UserCreate, UserListResponse, UserResponse
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["Users"])


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user",
    description="Registers a new user in the system after validating email and username uniqueness.",
)
async def create_user(
    payload: UserCreate,
    db: SessionDep,
    response: Response,
) -> UserResponse:
    """POST /users - Create a new user."""
    user = await UserService.create_user(db, payload)
    response.headers["location"] = f"/users/{user.id}"
    return UserResponse.model_validate(user)


@router.get(
    "",
    response_model=UserListResponse,
    status_code=status.HTTP_200_OK,
    summary="List users",
    description="Retrieve a paginated list of users.",
)
async def get_users(
    db: SessionDep,
    pagination: PaginationParams = Depends(),
) -> UserListResponse:
    """GET /users - Paginated user list."""
    users, total = await UserService.get_users(
        db, limit=pagination.limit, offset=pagination.offset
    )
    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in users],
        page=pagination.page,
        page_size=pagination.page_size,
        total=total,
    )


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get user by ID",
    description="Fetch details for a specific user by UUID.",
)
async def get_user(
    user_id: UUID,
    db: SessionDep,
) -> UserResponse:
    """GET /users/{user_id} - Retrieve user by UUID."""
    user = await UserService.get_user(db, user_id)
    return UserResponse.model_validate(user)
