"""Signup, password hashing, login, JWT validation and 401 behaviour."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.models.user import User
from tests.auth_helpers import TEST_PASSWORD, create_db_user


def _signup_payload(**overrides) -> dict:
    tag = uuid.uuid4().hex[:10]
    payload = {
        "name": f"Signup {tag}",
        "username": f"signup_{tag}",
        "email": f"signup_{tag}@example.com",
        "password": TEST_PASSWORD,
    }
    payload.update(overrides)
    return payload


async def _login(client: AsyncClient, username: str, password: str = TEST_PASSWORD):
    return await client.post(
        "/auth/login", data={"username": username, "password": password}
    )


def _error_code(response) -> str:
    return response.json()["detail"]["error"]["code"]


# ---------------------------------------------------------------------------
# Signup + hashing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_creates_member_and_hashes_password(
    client: AsyncClient, session_factory
):
    payload = _signup_payload()
    response = await client.post("/auth/signup", json=payload)

    assert response.status_code == 201, response.text
    data = response.json()
    assert data["role"] == "member"
    assert "password" not in data and "password_hash" not in data

    async with session_factory() as session:
        stored = (
            await session.execute(select(User).where(User.id == uuid.UUID(data["id"])))
        ).scalar_one()
    assert stored.password_hash != TEST_PASSWORD
    assert stored.password_hash.startswith("$argon2id$")


@pytest.mark.asyncio
async def test_signup_ignores_requested_role(client: AsyncClient):
    response = await client.post("/auth/signup", json=_signup_payload(role="admin"))

    assert response.status_code == 201
    assert response.json()["role"] == "member"


@pytest.mark.asyncio
async def test_signup_rejects_duplicate_email(client: AsyncClient):
    payload = _signup_payload()
    assert (await client.post("/auth/signup", json=payload)).status_code == 201

    again = await client.post(
        "/auth/signup", json=_signup_payload(email=payload["email"])
    )
    assert again.status_code == 409
    assert _error_code(again) == "EMAIL_ALREADY_EXISTS"


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("login_with", ["username", "email"])
async def test_login_returns_bearer_token(client: AsyncClient, login_with: str):
    payload = _signup_payload()
    await client.post("/auth/signup", json=payload)

    response = await _login(client, payload[login_with])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    me = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["username"] == payload["username"]


@pytest.mark.asyncio
async def test_login_wrong_password_and_unknown_user_look_the_same(
    client: AsyncClient,
):
    payload = _signup_payload()
    await client.post("/auth/signup", json=payload)

    wrong_password = await _login(client, payload["username"], "not-the-password")
    unknown_user = await _login(client, f"ghost_{uuid.uuid4().hex[:8]}")

    for response in (wrong_password, unknown_user):
        assert response.status_code == 401
        assert _error_code(response) == "INVALID_CREDENTIALS"
    assert wrong_password.json() == unknown_user.json()


@pytest.mark.asyncio
async def test_login_rejects_legacy_non_argon2_hash(
    client: AsyncClient, session_factory
):
    """Accounts hashed with the old SHA-256 scheme fail login cleanly (401, not 500)."""
    user = await create_db_user(session_factory)
    async with session_factory() as session:
        stored = await session.get(User, user.id)
        stored.password_hash = (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b"
        )
        await session.commit()

    response = await _login(client, user.username)
    assert response.status_code == 401
    assert _error_code(response) == "INVALID_CREDENTIALS"


# ---------------------------------------------------------------------------
# JWT validation -> 401
# ---------------------------------------------------------------------------


def _token(sub: str, *, secret: str | None = None, **claims) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": sub,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **claims,
    }
    return jwt.encode(
        payload, secret or settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


async def _me(client: AsyncClient, token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    return await client.get("/auth/me", headers=headers)


@pytest.mark.asyncio
async def test_me_requires_token(client: AsyncClient):
    response = await _me(client, None)
    assert response.status_code == 401
    assert _error_code(response) == "UNAUTHORIZED"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.asyncio
async def test_expired_token_is_rejected(client: AsyncClient, session_factory):
    user = await create_db_user(session_factory)
    past = datetime.now(UTC) - timedelta(hours=1)
    token = _token(str(user.id), iat=past, exp=past + timedelta(minutes=5))

    response = await _me(client, token)
    assert response.status_code == 401
    assert _error_code(response) == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_token_signed_with_another_secret_is_rejected(
    client: AsyncClient, session_factory
):
    user = await create_db_user(session_factory)
    token = _token(str(user.id), secret="an-attacker-controlled-secret-0123456789abcd")

    assert (await _me(client, token)).status_code == 401


@pytest.mark.asyncio
async def test_tampered_token_is_rejected(client: AsyncClient, session_factory):
    user = await create_db_user(session_factory)
    header, payload, signature = _token(str(user.id)).split(".")
    tampered = f"{header}.{payload}.{signature[:-4]}AAAA"

    assert (await _me(client, tampered)).status_code == 401


@pytest.mark.asyncio
async def test_unsigned_alg_none_token_is_rejected(
    client: AsyncClient, session_factory
):
    user = await create_db_user(session_factory)
    token = jwt.encode(
        {"sub": str(user.id), "type": "access", "exp": 9999999999, "iat": 0},
        key=None,
        algorithm="none",
    )

    assert (await _me(client, token)).status_code == 401


@pytest.mark.asyncio
async def test_token_for_deleted_user_is_rejected(client: AsyncClient, session_factory):
    user = await create_db_user(session_factory)
    token = _token(str(user.id))
    assert (await _me(client, token)).status_code == 200

    async with session_factory() as session:
        await session.execute(delete(User).where(User.id == user.id))
        await session.commit()

    assert (await _me(client, token)).status_code == 401


@pytest.mark.asyncio
async def test_role_claim_in_token_is_not_trusted(client: AsyncClient, session_factory):
    """A member forging role=admin in a validly signed token still gets 403."""
    member = await create_db_user(session_factory)
    token = _token(str(member.id), role="admin")

    response = await client.post(
        "/users",
        json=_signup_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert _error_code(response) == "FORBIDDEN"
