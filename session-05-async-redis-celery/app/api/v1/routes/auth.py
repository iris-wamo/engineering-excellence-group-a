from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies.deps import SessionDep
from app.auth.dependencies import CurrentUserDep
from app.auth.tokens import create_access_token
from app.schemas.auth import TokenResponse
from app.schemas.user import UserCreate, UserResponse
from app.services.user_service import UserService

# Public router: signup and login need no token. /auth/me declares its own
# dependency on the current user.
router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Sign up",
    description=(
        "Public. Creates an account with the `member` role; any role in the "
        "body is ignored. Admins can promote users afterwards."
    ),
)
async def signup(
    payload: UserCreate,
    db: SessionDep,
    response: Response,
) -> UserResponse:
    """POST /auth/signup - Register a new member."""
    user = await UserService.create_user(db, payload)
    response.headers["location"] = f"/users/{user.id}"
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in and get an access token",
    description=(
        "Public. OAuth2 password form: `username` accepts a username or an "
        "email. Returns a bearer token; send it as `Authorization: Bearer "
        "<token>`. Wrong credentials return 401 INVALID_CREDENTIALS."
    ),
)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: SessionDep,
) -> TokenResponse:
    """POST /auth/login - Exchange credentials for a JWT access token."""
    user = await UserService.authenticate(db, form.username, form.password)
    token = create_access_token(user.id, user.role)
    return TokenResponse(access_token=token.token, expires_in=token.expires_in)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Current user",
    description="Returns the authenticated user's profile (401 without a valid token).",
)
async def me(current_user: CurrentUserDep) -> UserResponse:
    """GET /auth/me - Who am I."""
    return UserResponse.model_validate(current_user)
