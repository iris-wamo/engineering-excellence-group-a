"""Fixtures for the auth/RBAC suite: an HTTP client and a small org chart."""

from __future__ import annotations

from dataclasses import dataclass

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies.deps import get_db
from app.auth.roles import UserRole
from app.core.config import settings
from app.main import app
from tests.auth_helpers import bearer, create_db_user


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(settings.test_database_url, echo=False)
    factory = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    """Unauthenticated client; pass ``headers=`` per request."""

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


@dataclass
class Actor:
    id: str
    username: str
    email: str
    headers: dict[str, str]


@dataclass
class World:
    """admin; manager alice runs project P; bob is a manager elsewhere;
    members carol and dave are in P; erin is in no project."""

    admin: Actor
    alice: Actor
    bob: Actor
    carol: Actor
    dave: Actor
    erin: Actor
    project_id: str
    carol_task_id: str
    dave_task_id: str


async def _actor(session_factory, role: UserRole, prefix: str) -> Actor:
    user = await create_db_user(session_factory, role=role, prefix=prefix)
    return Actor(str(user.id), user.username, user.email, bearer(user.id))


@pytest_asyncio.fixture
async def world(client: AsyncClient, session_factory) -> World:
    admin = await _actor(session_factory, UserRole.ADMIN, "admin")
    alice = await _actor(session_factory, UserRole.MANAGER, "alice")
    bob = await _actor(session_factory, UserRole.MANAGER, "bob")
    carol = await _actor(session_factory, UserRole.MEMBER, "carol")
    dave = await _actor(session_factory, UserRole.MEMBER, "dave")
    erin = await _actor(session_factory, UserRole.MEMBER, "erin")

    # alice creates P herself and becomes its manager
    res = await client.post(
        "/projects",
        json={"title": "RBAC Project", "priority": "MEDIUM"},
        headers=alice.headers,
    )
    assert res.status_code == 201, res.text
    project_id = res.json()["id"]

    for member in (carol, dave):
        res = await client.post(
            f"/projects/{project_id}/members",
            json={"user_id": member.id},
            headers=alice.headers,
        )
        assert res.status_code == 201, res.text

    task_ids = {}
    for member in (carol, dave):
        res = await client.post(
            "/tasks",
            json={
                "title": f"{member.username} task",
                "project_id": project_id,
                "assignee_id": member.id,
            },
            headers=alice.headers,
        )
        assert res.status_code == 201, res.text
        task_ids[member.username] = res.json()["id"]

    return World(
        admin=admin,
        alice=alice,
        bob=bob,
        carol=carol,
        dave=dave,
        erin=erin,
        project_id=project_id,
        carol_task_id=task_ids[carol.username],
        dave_task_id=task_ids[dave.username],
    )
