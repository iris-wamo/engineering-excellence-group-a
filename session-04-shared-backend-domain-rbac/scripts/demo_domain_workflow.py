"""
Demo 02: Task Status Domain Workflow (Session 4)
------------------------------------------------
Proves, over the real HTTP path (HTTP -> API -> Service -> Workflow -> DB):

1. The rules live in the workflow: the allowed graph is read from
   TaskStatusWorkflow, not hardcoded in the route/service.
2. A valid transition succeeds and is persisted with its audit trail
   (task_status_history + activity_log).
3. Invalid transitions fail with one consistent 409 domain error and leave
   no partial state (status unchanged, no history, no activity).
4. Same-status requests are idempotent no-ops (no audit rows written).
5. Authorization is enforced (403 for an unrelated user).

Usage:
    uv run python -m scripts.demo_domain_workflow
"""

from __future__ import annotations

import asyncio
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.api.dependencies.deps import get_db
from app.core.config import settings
from app.main import app
from app.models.activity_log import ActivityLog
from app.models.task import Task, TaskStatus
from app.models.task_status_history import TaskStatusHistory
from app.workflows.task_status_workflow import TaskStatusWorkflow

PASS = "PASS"
FAIL = "FAIL"
failures: list[str] = []


def print_banner(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title.upper()}")
    print("=" * 80)


def print_step(step: str, title: str) -> None:
    print(f"\n[Step {step}] {title}")
    print("-" * 72)


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = PASS if condition else FAIL
    if not condition:
        failures.append(label)
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{mark}] {label}{suffix}")


async def main() -> None:
    print_banner("Demo 02: Task Status Domain Workflow")

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    tag = uuid.uuid4().hex[:6]

    async def db_state(task_id: str) -> tuple[TaskStatus, int, int]:
        async with factory() as session:
            task_uuid = uuid.UUID(task_id)
            status = (
                await session.execute(select(Task.status).where(Task.id == task_uuid))
            ).scalar_one()
            history = (
                (
                    await session.execute(
                        select(TaskStatusHistory).where(
                            TaskStatusHistory.task_id == task_uuid
                        )
                    )
                )
                .scalars()
                .all()
            )
            activity = (
                (
                    await session.execute(
                        select(ActivityLog).where(ActivityLog.task_id == task_uuid)
                    )
                )
                .scalars()
                .all()
            )
            return status, len(history), len(activity)

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://demo"
        ) as client:
            print_step("1", "Workflow rules are defined in the workflow itself")
            for status in TaskStatus:
                allowed = TaskStatusWorkflow.allowed_next(status)
                targets = ", ".join(s.value for s in sorted(allowed)) or "(terminal)"
                print(f"  {status.value:<12} -> {targets}")
            check(
                "todo -> in_progress is legal",
                TaskStatusWorkflow.can_transition(
                    TaskStatus.TODO, TaskStatus.IN_PROGRESS
                ),
            )
            check(
                "todo -> done is illegal",
                not TaskStatusWorkflow.can_transition(TaskStatus.TODO, TaskStatus.DONE),
            )

            print_step("2", "Seed data over HTTP")
            owner = (
                await client.post(
                    "/users",
                    json={
                        "name": f"Workflow Demo Owner {tag}",
                        "username": f"wf_demo_owner_{tag}",
                        "email": f"wf_demo_owner_{tag}@example.com",
                        "password": "SecurePassword123!",
                    },
                )
            ).json()
            stranger = (
                await client.post(
                    "/users",
                    json={
                        "name": f"Workflow Demo Stranger {tag}",
                        "username": f"wf_demo_stranger_{tag}",
                        "email": f"wf_demo_stranger_{tag}@example.com",
                        "password": "SecurePassword123!",
                    },
                )
            ).json()
            project = (
                await client.post(
                    "/projects",
                    json={
                        "title": f"Workflow Demo Project {tag}",
                        "priority": "MEDIUM",
                        "status": "ACTIVE",
                        "owner_id": owner["id"],
                    },
                )
            ).json()
            task = (
                await client.post(
                    "/tasks",
                    json={
                        "title": "Implement the status transition engine",
                        "project_id": project["id"],
                        "assignee_id": owner["id"],
                    },
                )
            ).json()
            print(f"  owner    = {owner['id']}")
            print(f"  stranger = {stranger['id']}")
            print(f"  project  = {project['id']}")
            print(f"  task     = {task['id']}")
            check("task starts in 'todo'", task["status"] == "todo", task["status"])

            print_step("3", "Valid transition: todo -> in_progress")
            response = await client.patch(
                f"/tasks/{task['id']}/status",
                json={"status": "in_progress"},
                headers={"X-User-ID": owner["id"]},
            )
            body = response.json()
            print(f"  HTTP {response.status_code}  body.status={body['status']}")
            check("API returns 200", response.status_code == 200)

            status, history, activity = await db_state(task["id"])
            check(
                "DB status is IN_PROGRESS",
                status == TaskStatus.IN_PROGRESS,
                status.value,
            )
            check("exactly 1 history row", history == 1, str(history))
            check("exactly 1 activity row", activity == 1, str(activity))

            trail = (await client.get(f"/tasks/{task['id']}/history")).json()[
                "statuses"
            ]
            acts = (await client.get(f"/tasks/{task['id']}/activity")).json()
            print(
                f"  history  : prev={trail[0]['previous_status']} "
                f"new={trail[0]['new_status']} by={trail[0]['changed_by_id']}"
            )
            print(f"  activity : {acts[0]['action']} details={acts[0]['details']}")

            print_step("4", "Same status again -> idempotent no-op (no new rows)")
            response = await client.patch(
                f"/tasks/{task['id']}/status",
                json={"status": "in_progress"},
                headers={"X-User-ID": owner["id"]},
            )
            status, history, activity = await db_state(task["id"])
            check("API returns 200", response.status_code == 200)
            check("no extra history row", history == 1, str(history))
            check("no extra activity row", activity == 1, str(activity))

            print_step("5", "Invalid transitions -> 409 with one consistent error")
            invalid_cases = [
                ("done", "skips the review step"),
                ("todo", "moves backwards"),
            ]
            for target, label in invalid_cases:
                response = await client.patch(
                    f"/tasks/{task['id']}/status",
                    json={"status": target},
                    headers={"X-User-ID": owner["id"]},
                )
                payload = response.json()["detail"]["error"]
                print(
                    f"  in_progress -> {target:<11} ({label}) "
                    f"HTTP {response.status_code} {payload['code']}: {payload['message']}"
                )
                check(f"{target} rejected with 409", response.status_code == 409)
                check(
                    f"{target} uses the shared error code",
                    payload["code"] == "INVALID_STATUS_TRANSITION",
                )

            status, history, activity = await db_state(task["id"])
            check(
                "status still IN_PROGRESS after rejections",
                status == TaskStatus.IN_PROGRESS,
                status.value,
            )
            check("no partial history rows", history == 1, str(history))
            check("no partial activity rows", activity == 1, str(activity))

            print_step("6", "Finish the workflow, then try to leave a terminal state")
            for target in ("in_review", "done"):
                response = await client.patch(
                    f"/tasks/{task['id']}/status",
                    json={"status": target},
                    headers={"X-User-ID": owner["id"]},
                )
                print(f"  -> {target:<11} HTTP {response.status_code}")
                check(f"{target} accepted", response.status_code == 200)

            response = await client.patch(
                f"/tasks/{task['id']}/status",
                json={"status": "todo"},
                headers={"X-User-ID": owner["id"]},
            )
            payload = response.json()["detail"]["error"]
            print(
                f"  done -> todo        HTTP {response.status_code} {payload['code']}"
            )
            check("terminal state is frozen (409)", response.status_code == 409)

            status, history, activity = await db_state(task["id"])
            check("final DB status is DONE", status == TaskStatus.DONE, status.value)
            check("3 history rows for 3 accepted moves", history == 3, str(history))
            check("3 activity rows for 3 accepted moves", activity == 3, str(activity))

            print_step("7", "Authorization: unrelated user may not change status")
            other_task = (
                await client.post(
                    "/tasks",
                    json={
                        "title": "Guarded task",
                        "project_id": project["id"],
                        "assignee_id": owner["id"],
                    },
                )
            ).json()
            response = await client.patch(
                f"/tasks/{other_task['id']}/status",
                json={"status": "in_progress"},
                headers={"X-User-ID": stranger["id"]},
            )
            payload = response.json()["detail"]["error"]
            print(
                f"  HTTP {response.status_code} {payload['code']}: {payload['message']}"
            )
            check("stranger is forbidden (403)", response.status_code == 403)
            status, history, activity = await db_state(other_task["id"])
            check("guarded task unchanged", status == TaskStatus.TODO, status.value)
            check("no audit rows for rejected attempt", history == 0 and activity == 0)

            print_step("8", "Missing identity")
            response = await client.patch(
                f"/tasks/{other_task['id']}/status", json={"status": "in_progress"}
            )
            payload = response.json()["detail"]["error"]
            print(f"  HTTP {response.status_code} {payload['code']}")
            check("missing X-User-ID is 401", response.status_code == 401)
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()

    print_banner("Result")
    if failures:
        print(f"  {len(failures)} check(s) FAILED: {failures}")
    else:
        print("  All demo checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
