from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response, status

from app.api.dependencies.deps import PaginationParams, SessionDep
from app.auth.dependencies import AdminDep, CurrentUserDep, get_current_user
from app.schemas.user import (
    AdminUserCreate,
    UserListResponse,
    UserResponse,
    UserRoleUpdate,
)
from app.services.user_service import UserService

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new user (admin)",
    description=(
        "Admin only. Creates a user with a chosen global role after validating "
        "email and username uniqueness. Self-service registration is "
        "POST /auth/signup."
    ),
)
async def create_user(
    payload: AdminUserCreate,
    db: SessionDep,
    response: Response,
    _admin: AdminDep,
) -> UserResponse:
    """POST /users - Create a new user."""
    user = await UserService.create_user(db, payload, role=payload.role)
    response.headers["location"] = f"/users/{user.id}"
    return UserResponse.model_validate(user)


@router.get(
    "",
    response_model=UserListResponse,
    status_code=status.HTTP_200_OK,
    summary="List users",
    description=(
        "Admins see every user; everyone else sees themselves and the people "
        "in their projects."
    ),
)
async def get_users(
    db: SessionDep,
    current_user: CurrentUserDep,
    pagination: PaginationParams = Depends(),
) -> UserListResponse:
    """GET /users - Paginated user list."""
    users, total = await UserService.get_users(
        db, current_user, limit=pagination.limit, offset=pagination.offset
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
    description=(
        "Fetch details for a specific user by UUID. Users outside your projects "
        "return 404 (admins can see everyone)."
    ),
)
async def get_user(
    user_id: UUID,
    db: SessionDep,
    current_user: CurrentUserDep,
) -> UserResponse:
    """GET /users/{user_id} - Retrieve user by UUID."""
    user = await UserService.get_visible_user(db, user_id, current_user)
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}/role",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Change a user's global role (admin)",
    description=(
        "Admin only. Demoting a manager to member also turns their project "
        "manager memberships into member ones. Admins cannot change their own "
        "role (409)."
    ),
)
async def change_user_role(
    user_id: UUID,
    payload: UserRoleUpdate,
    db: SessionDep,
    admin: AdminDep,
) -> UserResponse:
    """PATCH /users/{user_id}/role - Change global role."""
    user = await UserService.change_role(db, user_id, payload.role, actor=admin)
    return UserResponse.model_validate(user)
