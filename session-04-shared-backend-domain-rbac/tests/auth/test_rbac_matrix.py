"""Allowed and denied cases for every row of the RBAC matrix.

World (see conftest): admin; alice manages project P; bob is a manager with no
access to P; carol and dave are members of P with one task each; erin belongs
to no project.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.auth.conftest import World


def _code(response) -> str:
    return response.json()["detail"]["error"]["code"]


async def _status(client: AsyncClient, task_id: str, status: str, actor):
    return await client.patch(
        f"/tasks/{task_id}/status", json={"status": status}, headers=actor.headers
    )


def _new_user(**extra) -> dict:
    tag = uuid.uuid4().hex[:10]
    return {
        "name": f"New {tag}",
        "username": f"new_{tag}",
        "email": f"new_{tag}@example.com",
        "password": "SecurePassword123!",
        **extra,
    }


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_admin_creates_users_with_roles(client: AsyncClient, world: World):
    created = await client.post(
        "/users", json=_new_user(role="manager"), headers=world.admin.headers
    )
    assert created.status_code == 201
    assert created.json()["role"] == "manager"

    for actor in (world.alice, world.carol):
        denied = await client.post("/users", json=_new_user(), headers=actor.headers)
        assert denied.status_code == 403
        assert _code(denied) == "FORBIDDEN"


@pytest.mark.asyncio
async def test_non_admins_only_see_people_in_their_projects(
    client: AsyncClient, world: World
):
    listing = await client.get("/users?page_size=100", headers=world.carol.headers)
    assert listing.status_code == 200
    visible = {u["id"] for u in listing.json()["items"]}
    assert {world.carol.id, world.dave.id, world.alice.id} <= visible
    assert world.erin.id not in visible and world.bob.id not in visible

    assert (
        await client.get(f"/users/{world.dave.id}", headers=world.carol.headers)
    ).status_code == 200
    hidden = await client.get(f"/users/{world.erin.id}", headers=world.carol.headers)
    assert hidden.status_code == 404

    # erin is in no project: she only sees herself
    solo = await client.get("/users", headers=world.erin.headers)
    assert [u["id"] for u in solo.json()["items"]] == [world.erin.id]

    assert (
        await client.get(f"/users/{world.erin.id}", headers=world.admin.headers)
    ).status_code == 200


@pytest.mark.asyncio
async def test_only_admin_changes_roles_and_not_their_own(
    client: AsyncClient, world: World
):
    promoted = await client.patch(
        f"/users/{world.erin.id}/role",
        json={"role": "manager"},
        headers=world.admin.headers,
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "manager"

    denied = await client.patch(
        f"/users/{world.dave.id}/role",
        json={"role": "admin"},
        headers=world.alice.headers,
    )
    assert denied.status_code == 403

    own = await client.patch(
        f"/users/{world.admin.id}/role",
        json={"role": "member"},
        headers=world.admin.headers,
    )
    assert own.status_code == 409
    assert _code(own) == "CANNOT_CHANGE_OWN_ROLE"


@pytest.mark.asyncio
async def test_demoting_a_manager_downgrades_their_project_role(
    client: AsyncClient, world: World
):
    demoted = await client.patch(
        f"/users/{world.alice.id}/role",
        json={"role": "member"},
        headers=world.admin.headers,
    )
    assert demoted.status_code == 200

    members = await client.get(
        f"/projects/{world.project_id}/members", headers=world.alice.headers
    )
    roles = {m["user_id"]: m["role"] for m in members.json()}
    assert roles[world.alice.id] == "member"

    # She can still see P but can no longer run it.
    denied = await client.post(
        f"/projects/{world.project_id}/members",
        json={"user_id": world.erin.id},
        headers=world.alice.headers,
    )
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manager_creates_project_and_becomes_its_manager(
    client: AsyncClient, world: World
):
    res = await client.post(
        "/projects",
        json={"title": "Bob's project", "priority": "LOW"},
        headers=world.bob.headers,
    )
    assert res.status_code == 201
    project = res.json()
    assert project["owner_id"] == world.bob.id

    members = await client.get(
        f"/projects/{project['id']}/members", headers=world.bob.headers
    )
    assert [(m["user_id"], m["role"]) for m in members.json()] == [
        (world.bob.id, "manager")
    ]


@pytest.mark.asyncio
async def test_manager_cannot_create_project_for_someone_else(
    client: AsyncClient, world: World
):
    res = await client.post(
        "/projects",
        json={"title": "Not mine", "priority": "LOW", "owner_id": world.alice.id},
        headers=world.bob.headers,
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_create_project(client: AsyncClient, world: World):
    res = await client.post(
        "/projects",
        json={"title": "Nope", "priority": "LOW"},
        headers=world.carol.headers,
    )
    assert res.status_code == 403
    assert _code(res) == "FORBIDDEN"


@pytest.mark.asyncio
async def test_admin_creates_project_for_a_manager(client: AsyncClient, world: World):
    res = await client.post(
        "/projects",
        json={"title": "Admin-made", "priority": "HIGH", "owner_id": world.bob.id},
        headers=world.admin.headers,
    )
    assert res.status_code == 201
    project_id = res.json()["id"]
    assert res.json()["owner_id"] == world.bob.id

    # bob now runs it
    added = await client.post(
        f"/projects/{project_id}/members",
        json={"user_id": world.erin.id},
        headers=world.bob.headers,
    )
    assert added.status_code == 201

    # A member-role user cannot be handed a project
    invalid = await client.post(
        "/projects",
        json={"title": "Bad owner", "priority": "LOW", "owner_id": world.carol.id},
        headers=world.admin.headers,
    )
    assert invalid.status_code == 422
    assert _code(invalid) == "INVALID_ROLE_ASSIGNMENT"


@pytest.mark.asyncio
async def test_admin_assigns_existing_project_to_another_manager(
    client: AsyncClient, world: World
):
    # bob cannot touch P yet
    before = await client.get(
        f"/projects/{world.project_id}", headers=world.bob.headers
    )
    assert before.status_code == 404

    assigned = await client.post(
        f"/projects/{world.project_id}/managers",
        json={"user_id": world.bob.id},
        headers=world.admin.headers,
    )
    assert assigned.status_code == 200
    assert assigned.json()["role"] == "manager"

    # bob now manages P alongside alice; alice still manages it too
    reassigned = await client.post(
        f"/tasks/{world.carol_task_id}/assign",
        json={"assignee_id": world.dave.id},
        headers=world.bob.headers,
    )
    assert reassigned.status_code == 200

    # only admins assign managers, and only manager-role users can be assigned
    by_manager = await client.post(
        f"/projects/{world.project_id}/managers",
        json={"user_id": world.bob.id},
        headers=world.alice.headers,
    )
    assert by_manager.status_code == 403
    to_member = await client.post(
        f"/projects/{world.project_id}/managers",
        json={"user_id": world.carol.id},
        headers=world.admin.headers,
    )
    assert to_member.status_code == 422


@pytest.mark.asyncio
async def test_projects_are_invisible_outside_membership(
    client: AsyncClient, world: World
):
    mine = await client.get("/projects?page_size=100", headers=world.carol.headers)
    assert [p["id"] for p in mine.json()["items"]] == [world.project_id]

    none = await client.get("/projects", headers=world.erin.headers)
    assert none.json()["total"] == 0

    hidden = await client.get(
        f"/projects/{world.project_id}", headers=world.erin.headers
    )
    assert hidden.status_code == 404
    assert _code(hidden) == "PROJECT_NOT_FOUND"

    admin_view = await client.get(
        f"/projects/{world.project_id}", headers=world.admin.headers
    )
    assert admin_view.status_code == 200


# ---------------------------------------------------------------------------
# Project membership
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_management_rules(client: AsyncClient, world: World):
    url = f"/projects/{world.project_id}/members"

    # member cannot add, outsider sees nothing
    assert (
        await client.post(
            url, json={"user_id": world.erin.id}, headers=world.carol.headers
        )
    ).status_code == 403
    assert (
        await client.post(
            url, json={"user_id": world.erin.id}, headers=world.erin.headers
        )
    ).status_code == 404

    # manager adds; a duplicate is rejected
    assert (
        await client.post(
            url, json={"user_id": world.erin.id}, headers=world.alice.headers
        )
    ).status_code == 201
    duplicate = await client.post(
        url, json={"user_id": world.erin.id}, headers=world.alice.headers
    )
    assert duplicate.status_code == 409
    assert _code(duplicate) == "ALREADY_PROJECT_MEMBER"

    # manager removes a member, but not a manager; admin can
    assert (
        await client.delete(f"{url}/{world.erin.id}", headers=world.alice.headers)
    ).status_code == 204
    await client.post(
        f"/projects/{world.project_id}/managers",
        json={"user_id": world.bob.id},
        headers=world.admin.headers,
    )
    assert (
        await client.delete(f"{url}/{world.bob.id}", headers=world.alice.headers)
    ).status_code == 403
    assert (
        await client.delete(f"{url}/{world.bob.id}", headers=world.admin.headers)
    ).status_code == 204


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_creates_tasks_only_for_themselves(
    client: AsyncClient, world: World
):
    own = await client.post(
        "/tasks",
        json={"title": "Carol's own", "project_id": world.project_id},
        headers=world.carol.headers,
    )
    assert own.status_code == 201
    assert own.json()["assignee_id"] == world.carol.id

    for_dave = await client.post(
        "/tasks",
        json={
            "title": "For Dave",
            "project_id": world.project_id,
            "assignee_id": world.dave.id,
        },
        headers=world.carol.headers,
    )
    assert for_dave.status_code == 403

    outsider = await client.post(
        "/tasks",
        json={"title": "Erin's", "project_id": world.project_id},
        headers=world.erin.headers,
    )
    assert outsider.status_code == 404


@pytest.mark.asyncio
async def test_task_assignee_must_be_in_the_project(client: AsyncClient, world: World):
    res = await client.post(
        "/tasks",
        json={
            "title": "For an outsider",
            "project_id": world.project_id,
            "assignee_id": world.erin.id,
        },
        headers=world.alice.headers,
    )
    assert res.status_code == 422
    assert _code(res) == "ASSIGNEE_NOT_IN_PROJECT"


@pytest.mark.asyncio
async def test_tasks_are_invisible_outside_membership(
    client: AsyncClient, world: World
):
    listed = await client.get(
        f"/tasks?project_id={world.project_id}&page_size=100",
        headers=world.carol.headers,
    )
    assert {world.carol_task_id, world.dave_task_id} <= {
        t["id"] for t in listed.json()["items"]
    }

    erin_list = await client.get("/tasks", headers=world.erin.headers)
    assert erin_list.json()["total"] == 0

    for suffix in ("", "/history", "/activity", "/notifications"):
        hidden = await client.get(
            f"/tasks/{world.carol_task_id}{suffix}", headers=world.erin.headers
        )
        assert hidden.status_code == 404, suffix
        visible = await client.get(
            f"/tasks/{world.carol_task_id}{suffix}", headers=world.dave.headers
        )
        assert visible.status_code == 200, suffix


@pytest.mark.asyncio
async def test_status_change_ownership_rules(client: AsyncClient, world: World):
    # member: own task yes, someone else's no
    assert (
        await _status(client, world.carol_task_id, "in_progress", world.carol)
    ).status_code == 200
    other = await _status(client, world.dave_task_id, "in_progress", world.carol)
    assert other.status_code == 403
    assert _code(other) == "STATUS_CHANGE_FORBIDDEN"

    # member cannot cancel, even their own task
    cancel = await _status(client, world.carol_task_id, "cancelled", world.carol)
    assert cancel.status_code == 403

    # manager and admin can move and cancel any task in the project
    assert (
        await _status(client, world.dave_task_id, "in_progress", world.alice)
    ).status_code == 200
    assert (
        await _status(client, world.dave_task_id, "cancelled", world.admin)
    ).status_code == 200
    assert (
        await _status(client, world.carol_task_id, "cancelled", world.alice)
    ).status_code == 200

    # outsider: the task does not exist for them
    assert (
        await _status(client, world.carol_task_id, "in_review", world.erin)
    ).status_code == 404


@pytest.mark.asyncio
async def test_only_managers_and_admins_assign_tasks(client: AsyncClient, world: World):
    url = f"/tasks/{world.carol_task_id}/assign"
    payload = {"assignee_id": world.dave.id}

    member = await client.post(url, json=payload, headers=world.carol.headers)
    assert member.status_code == 403

    outsider = await client.post(url, json=payload, headers=world.bob.headers)
    assert outsider.status_code == 404

    manager = await client.post(url, json=payload, headers=world.alice.headers)
    assert manager.status_code == 200
    assert manager.json()["assignment_history"]["assigned_by_id"] == world.alice.id

    admin = await client.post(
        url, json={"assignee_id": world.carol.id}, headers=world.admin.headers
    )
    assert admin.status_code == 200


# ---------------------------------------------------------------------------
# Imports (admin only; the admin path itself is covered by test_mongo_import)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_imports_are_admin_only(client: AsyncClient, world: World, method):
    for actor in (world.alice, world.carol):
        res = await client.request(
            method, "/imports/tasks/raw", json={}, headers=actor.headers
        )
        assert res.status_code == 403, (method, actor.username)
