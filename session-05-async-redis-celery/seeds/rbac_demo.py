"""RBAC demo seed: admin-created projects, managers, members and their tasks.

    make seed-rbac          # after `make migrate`

Idempotent (re-running inserts nothing new) and refuses to run when
APP_ENV=production. Every account's password is SEED_USER_PASSWORD
(default "Password123!"); log in with the username or email below.

Who can do what with this data:

| Project          | Created by | Manager(s) | Members      |
| ---------------- | ---------- | ---------- | ------------ |
| Customer Portal  | admin      | alice      | carol, dave  |
| Data Platform    | admin      | bob        | dave, erin   |
| Security Audit   | admin      | (none yet) | (none)       |
| Mobile App       | alice      | alice      | carol        |

- alice manages two projects (one assigned by the admin, one she created).
- "Security Audit" is waiting for the admin to assign a manager
  (POST /projects/{id}/managers).
- erin cannot see Customer Portal or Mobile App at all (404).
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.auth.passwords import hash_password
from app.auth.roles import ProjectRole, UserRole
from app.core.config import settings
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.task import Task
from app.models.user import User

DEFAULT_PASSWORD = "Password123!"


def _id(name: str) -> UUID:
    """Stable id per seed row, so re-runs hit the same primary keys."""
    return uuid5(NAMESPACE_URL, f"taskflow-rbac-demo/{name}")


# (key, name, role)
USERS: list[tuple[str, str, UserRole]] = [
    ("admin", "Ada Admin", UserRole.ADMIN),
    ("alice", "Alice Manager", UserRole.MANAGER),
    ("bob", "Bob Manager", UserRole.MANAGER),
    ("carol", "Carol Member", UserRole.MEMBER),
    ("dave", "Dave Member", UserRole.MEMBER),
    ("erin", "Erin Member", UserRole.MEMBER),
]

# (key, title, priority, created_by, manager or None, members)
PROJECTS: list[tuple[str, str, str, str, str | None, list[str]]] = [
    (
        "customer-portal",
        "Customer Portal",
        "HIGH",
        "admin",
        "alice",
        ["carol", "dave"],
    ),
    ("data-platform", "Data Platform", "MEDIUM", "admin", "bob", ["dave", "erin"]),
    ("security-audit", "Security Audit", "HIGH", "admin", None, []),
    ("mobile-app", "Mobile App", "LOW", "alice", "alice", ["carol"]),
]

# (key, project, title, priority, status, assignee or None)
TASKS: list[tuple[str, str, str, str, str, str | None]] = [
    (
        "cp-login",
        "customer-portal",
        "Design login page",
        "HIGH",
        "IN_PROGRESS",
        "carol",
    ),
    ("cp-payments", "customer-portal", "Payment integration", "HIGH", "TODO", "dave"),
    ("cp-a11y", "customer-portal", "Accessibility review", "MEDIUM", "TODO", None),
    ("dp-ingest", "data-platform", "Ingestion pipeline", "HIGH", "IN_REVIEW", "erin"),
    ("dp-schema", "data-platform", "Warehouse schema", "MEDIUM", "TODO", "dave"),
    ("sa-threat", "security-audit", "Threat model", "URGENT", "TODO", None),
    ("ma-shell", "mobile-app", "App shell", "MEDIUM", "TODO", "carol"),
]


def _rows() -> dict[str, list[dict[str, Any]]]:
    password_hash = hash_password(
        os.environ.get("SEED_USER_PASSWORD", DEFAULT_PASSWORD)
    )
    now = datetime.now(UTC).replace(tzinfo=None)

    users = [
        {
            "id": _id(f"user/{key}"),
            "name": name,
            "username": key,
            "email": f"{key}@taskflow.example",
            "password_hash": password_hash,
            "role": role.value,
        }
        for key, name, role in USERS
    ]

    projects, members = [], []
    managers: dict[str, str | None] = {}
    for key, title, priority, created_by, manager, project_members in PROJECTS:
        project_id = _id(f"project/{key}")
        managers[key] = manager
        projects.append(
            {
                "id": project_id,
                "title": title,
                "slug": key,
                "description": f"{title} (RBAC demo, created by {created_by})",
                "priority": priority,
                "status": "ACTIVE",
                "deadline": now + timedelta(days=45),
                # The manager owns the project; an unassigned project stays with
                # the admin who created it.
                "owner_id": _id(f"user/{manager or created_by}"),
            }
        )
        if manager:
            members.append(
                {
                    "project_id": project_id,
                    "user_id": _id(f"user/{manager}"),
                    "member_role": ProjectRole.MANAGER.value,
                }
            )
        members += [
            {
                "project_id": project_id,
                "user_id": _id(f"user/{member}"),
                "member_role": ProjectRole.MEMBER.value,
            }
            for member in project_members
        ]

    tasks = []
    for key, project, title, priority, status, assignee in TASKS:
        assigner = managers[project] or "admin"
        tasks.append(
            {
                "id": _id(f"task/{key}"),
                "project_id": _id(f"project/{project}"),
                "assigned_to": _id(f"user/{assignee}") if assignee else None,
                "assigned_by": _id(f"user/{assigner}") if assignee else None,
                "title": title,
                "description": f"{title} (RBAC demo)",
                "priority": priority,
                "status": status,
                "estimated_time": 240,
                "deadline": now + timedelta(days=14),
                "created_at": now,
                "updated_at": now,
            }
        )

    return {"users": users, "projects": projects, "members": members, "tasks": tasks}


async def seed_rbac_demo() -> dict[str, int]:
    """Insert the demo rows, skipping any that already exist. Returns new-row counts."""
    rows = _rows()
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    inserted: dict[str, int] = {}
    try:
        async with AsyncSession(engine) as session, session.begin():
            for label, table, data in (
                ("users", User.__table__, rows["users"]),
                ("projects", Project.__table__, rows["projects"]),
                ("project members", ProjectMember.__table__, rows["members"]),
                ("tasks", Task.__table__, rows["tasks"]),
            ):
                result = await session.execute(
                    insert(table).values(data).on_conflict_do_nothing()
                )
                inserted[label] = result.rowcount
    finally:
        await engine.dispose()
    return inserted


def main() -> None:
    if settings.ENVIRONMENT.lower() == "production":
        sys.exit("Refusing to seed demo accounts with APP_ENV=production.")
    inserted = asyncio.run(seed_rbac_demo())
    print("RBAC demo seed complete (new rows):")
    for label, count in inserted.items():
        print(f"  {label}: {count}")
    print(
        "\nLog in with any of: "
        + ", ".join(key for key, _, _ in USERS)
        + " (or <name>@taskflow.example)."
        + "\nPassword: $SEED_USER_PASSWORD, default "
        + DEFAULT_PASSWORD
    )


if __name__ == "__main__":
    main()
