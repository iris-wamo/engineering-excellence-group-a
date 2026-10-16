"""Helpers for authenticated API tests.

Users are inserted straight into the test database (so tests can create an
admin without an admin), and tokens are minted with the app's own signer.
"""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient

from app.auth.passwords import hash_password
from app.auth.roles import UserRole
from app.auth.tokens import create_access_token
from app.models.user import User

TEST_PASSWORD = "SecurePassword123!"


def bearer(user_id: Any) -> dict[str, str]:
    """Authorization header carrying a valid access token for ``user_id``."""
    token = create_access_token(uuid.UUID(str(user_id)), UserRole.MEMBER).token
    return {"Authorization": f"Bearer {token}"}


# Sends an empty Authorization header, overriding a client's default token.
NO_AUTH: dict[str, str] = {"Authorization": ""}


async def create_db_user(
    session_factory: Any,
    *,
    role: UserRole = UserRole.MEMBER,
    password: str = TEST_PASSWORD,
    prefix: str = "user",
) -> User:
    """Insert a user with a real Argon2 hash and return it."""
    suffix = uuid.uuid4().hex[:10]
    async with session_factory() as session:
        user = User(
            name=f"{prefix.title()} {suffix}",
            username=f"{prefix}_{suffix}",
            email=f"{prefix}_{suffix}@example.com",
            password_hash=hash_password(password),
            role=role,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def admin_headers(session_factory: Any) -> dict[str, str]:
    """Create a fresh admin and return its Authorization header."""
    admin = await create_db_user(session_factory, role=UserRole.ADMIN, prefix="admin")
    return bearer(admin.id)


async def promote_to_manager(client: AsyncClient, user_id: str) -> None:
    """Admin client: give ``user_id`` the global manager role."""
    response = await client.patch(f"/users/{user_id}/role", json={"role": "manager"})
    assert response.status_code == 200, response.text


async def add_project_member(
    client: AsyncClient, project_id: str, user_id: str
) -> None:
    """Admin/manager client: add ``user_id`` to the project (no-op if already in)."""
    response = await client.post(
        f"/projects/{project_id}/members", json={"user_id": user_id}
    )
    assert response.status_code in (201, 409), response.text
