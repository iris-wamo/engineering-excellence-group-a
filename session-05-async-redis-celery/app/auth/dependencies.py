"""FastAPI dependencies for authentication and global-role authorization.

Attach ``get_current_user`` at router level (``APIRouter(dependencies=...)``)
so every route on a protected router requires a valid bearer token; routes
that need the user object also declare ``CurrentUserDep`` (FastAPI resolves
it once per request). Project-scoped rules live in ``app.auth.permissions``
and are enforced by the service layer.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.api.dependencies.deps import SessionDep
from app.auth.roles import UserRole
from app.auth.tokens import TokenValidationError, decode_access_token
from app.core.exceptions import ForbiddenError, NotAuthenticatedError
from app.models.user import User
from app.repositories.user_repository import UserRepository

# auto_error=False so a missing token raises our own 401 envelope.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


async def get_current_user(
    db: SessionDep,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    """Resolve the acting user from the bearer token (401 otherwise).

    The user is re-read from the database on every request, so a deleted or
    demoted user loses access immediately, whatever the token says.
    """
    if not token:
        raise NotAuthenticatedError()
    try:
        user_id = decode_access_token(token)
    except TokenValidationError as exc:
        raise NotAuthenticatedError("Invalid or expired token") from exc

    user = await UserRepository.get_by_id(db, user_id)
    if user is None:
        raise NotAuthenticatedError("Invalid or expired token")
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], Awaitable[User]]:
    """Dependency factory: 403 unless the user's global role is in ``roles``."""
    allowed = frozenset(roles)

    async def _require(user: CurrentUserDep) -> User:
        if user.role not in allowed:
            raise ForbiddenError()
        return user

    return _require


require_admin = require_roles(UserRole.ADMIN)
AdminDep = Annotated[User, Depends(require_admin)]
