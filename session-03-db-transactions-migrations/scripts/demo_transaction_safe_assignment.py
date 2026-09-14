"""
Demo 01: Transaction-Safe Task Assignment Flow & Database Constraints
---------------------------------------------------------------------
Demonstrates:
1. 5-step atomic task assignment transaction (Task + AssignmentHistory + StatusHistory + ActivityLog + Notification).
2. Atomic rollback on mid-transaction failure (proving zero partial writes).
3. Re-assignment audit tracking (preserving previous -> new assignee lineage).
4. Database-level constraint enforcement (unique slug, unique email, foreign key integrity).

Usage:
    uv run python -m scripts.demo_transaction_safe_assignment
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.activity_log import ActivityLog
from app.models.notification import Notification
from app.models.project import Project, ProjectStatus
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.task_assignment_history import TaskAssignmentHistory
from app.models.task_status_history import TaskStatusHistory
from app.models.user import User


def print_banner(title: str) -> None:
    print("\n" + "=" * 80)
    print(f"  {title.upper()}")
    print("=" * 80)


def print_step(step_num: int, title: str) -> None:
    print(f"\n[Step {step_num}] {title}")
    print("-" * 60)


async def main() -> None:
    print_banner("Demo 01: Transaction-Safe Task Assignment & DB Constraints")
    print(
        f"Connecting to Database: {settings.DB_NAME} at {settings.DB_HOST}:{settings.DB_PORT}"
    )

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False
    )

    run_id = uuid.uuid4().hex[:6]

    async with session_factory() as db:
        # -------------------------------------------------------------
        # SETUP: Create Users, Project, and Task
        # -------------------------------------------------------------
        print_step(
            1, "Setting up Demo Data (Lead, Backend Dev, Frontend Dev, Project, Task)"
        )

        lead_user = User(
            name=f"Faiza Lead ({run_id})",
            username=f"faiza_lead_{run_id}",
            email=f"faiza.lead.{run_id}@example.com",
            password_hash="hashed_pw_123",
            role="admin",
        )
        backend_dev = User(
            name=f"Khubaib Backend ({run_id})",
            username=f"khubaib_dev_{run_id}",
            email=f"khubaib.dev.{run_id}@example.com",
            password_hash="hashed_pw_123",
            role="developer",
        )
        frontend_dev = User(
            name=f"Huzaifa Frontend ({run_id})",
            username=f"huzaifa_dev_{run_id}",
            email=f"huzaifa.dev.{run_id}@example.com",
            password_hash="hashed_pw_123",
            role="developer",
        )
        db.add_all([lead_user, backend_dev, frontend_dev])
        await db.commit()
        await db.refresh(lead_user)
        await db.refresh(backend_dev)
        await db.refresh(frontend_dev)

        lead_user_id = lead_user.id
        lead_user_name = lead_user.name
        lead_user_email = lead_user.email
        backend_dev_id = backend_dev.id
        backend_dev_name = backend_dev.name
        frontend_dev_id = frontend_dev.id
        frontend_dev_name = frontend_dev.name

        project = Project(
            title="Core Platform Refactor",
            slug=f"core-platform-{run_id}",
            description="Migrating database architecture and ensuring ACID transactions",
            priority="HIGH",
            status=ProjectStatus.ACTIVE,
            owner_id=lead_user_id,
        )
        db.add(project)
        await db.commit()
        await db.refresh(project)

        project_id = project.id
        project_slug = project.slug
        project_title = project.title

        task = Task(
            project_id=project_id,
            title="Implement Transaction Boundary for Task Assignment",
            description="Ensure task assignee, history, status, activity log, and notifications commit atomically.",
            priority=TaskPriority.HIGH,
            status=TaskStatus.TODO,
            assigned_to=None,
            assigned_by=None,
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)

        task_id = task.id
        task_title = task.title

        print(f"Created Lead User    : {lead_user_name} ({lead_user_id})")
        print(f"Created Backend Dev  : {backend_dev_name} ({backend_dev_id})")
        print(f"Created Frontend Dev : {frontend_dev_name} ({frontend_dev_id})")
        print(f"Created Project      : {project_title} [slug: {project_slug}]")
        print(
            f"Created Initial Task : '{task_title}' | Status: {task.status.value} | Assignee: {task.assigned_to}"
        )

        # -------------------------------------------------------------
        # SCENARIO 1: Successful Atomic Assignment Transaction
        # -------------------------------------------------------------
        print_step(2, "SCENARIO 1: Executing 5-Step Transaction-Safe Assignment Flow")
        print(">> Beginning single atomic database transaction...")

        now = datetime.now(UTC).replace(tzinfo=None)
        prev_assignee = task.assigned_to
        prev_status = task.status
        target_status = TaskStatus.IN_PROGRESS

        try:
            # 1. Update Task
            task.assigned_to = backend_dev.id
            task.assigned_by = lead_user.id
            task.status = target_status
            task.updated_at = now
            db.add(task)
            print("   [1/5] Task updated: assigned_to=Backend Dev, status=IN_PROGRESS")

            # 2. Add Assignment History
            assign_hist = TaskAssignmentHistory(
                task_id=task.id,
                previous_assignee_id=prev_assignee,
                new_assignee_id=backend_dev.id,
                assigned_by_id=lead_user.id,
                created_at=now,
            )
            db.add(assign_hist)
            print(
                "   [2/5] TaskAssignmentHistory staged: previous=None -> new=Backend Dev"
            )

            # 3. Add Status History
            status_hist = TaskStatusHistory(
                task_id=task.id,
                previous_status=prev_status,
                new_status=target_status,
                changed_by_id=lead_user.id,
                created_at=now,
            )
            db.add(status_hist)
            print("   [3/5] TaskStatusHistory staged: TODO -> IN_PROGRESS")

            # 4. Add Activity Log
            activity = ActivityLog(
                task_id=task.id,
                actor_id=lead_user.id,
                action="task.assigned",
                details={
                    "previous_assignee_id": None,
                    "new_assignee_id": str(backend_dev.id),
                    "assigned_by_name": lead_user.name,
                    "new_assignee_name": backend_dev.name,
                    "comment": "Sprint 3 high-priority backend deliverable",
                },
                created_at=now,
            )
            db.add(activity)
            print(
                "   [4/5] ActivityLog staged: actor=Lead User, action='task.assigned'"
            )

            # 5. Add Notification
            notif = Notification(
                recipient_id=backend_dev.id,
                task_id=task.id,
                type="task_assignment",
                message=f"You have been assigned to task '{task.title}' by {lead_user.name}.",
                is_read=False,
                created_at=now,
            )
            db.add(notif)
            print("   [5/5] Notification staged: recipient=Backend Dev, unread=True")

            # Atomic commit
            await db.commit()
            print(
                ">> Transaction COMMITTED successfully! All 5 records persisted together."
            )

        except Exception as exc:
            await db.rollback()
            print(f">> ERROR: Transaction rolled back: {exc}")
            raise

        # Verify persisted rows
        print("\n--- Direct Database Inspection (Post-Commit) ---")
        await db.refresh(task)
        print(
            f"Task Table               : ID={task.id} | Assignee={task.assigned_to} | Status={task.status.value}"
        )
        hists = (
            (
                await db.execute(
                    select(TaskAssignmentHistory).where(
                        TaskAssignmentHistory.task_id == task.id
                    )
                )
            )
            .scalars()
            .all()
        )
        print(
            f"TaskAssignmentHistory (x{len(hists)}) : ID={hists[0].id} | New Assignee={hists[0].new_assignee_id}"
        )
        statuses = (
            (
                await db.execute(
                    select(TaskStatusHistory).where(
                        TaskStatusHistory.task_id == task.id
                    )
                )
            )
            .scalars()
            .all()
        )
        print(
            f"TaskStatusHistory (x{len(statuses)})     : ID={statuses[0].id} | {statuses[0].previous_status.value} -> {statuses[0].new_status.value}"
        )
        acts = (
            (
                await db.execute(
                    select(ActivityLog).where(ActivityLog.task_id == task.id)
                )
            )
            .scalars()
            .all()
        )
        print(
            f"ActivityLog (x{len(acts)})           : Action='{acts[0].action}' | Details={acts[0].details}"
        )
        notifs = (
            (
                await db.execute(
                    select(Notification).where(Notification.task_id == task.id)
                )
            )
            .scalars()
            .all()
        )
        print(
            f"Notification (x{len(notifs)})          : Message='{notifs[0].message}' | Read={notifs[0].is_read}"
        )

        task_id = task.id
        lead_user_id = lead_user.id
        backend_dev_id = backend_dev.id
        frontend_dev_id = frontend_dev.id

        # -------------------------------------------------------------
        # SCENARIO 2: Simulated Mid-Transaction Failure & Rollback Proof
        # -------------------------------------------------------------
        print_step(
            3,
            "SCENARIO 2: Simulated Failure at Step 5 (Notification Failure) & Rollback Proof",
        )
        print(
            ">> Attempting to reassign task to Frontend Dev, simulating an exception at Step 5..."
        )

        state_before_task_assignee = task.assigned_to
        count_assign_before = (
            await db.execute(
                select(func.count(TaskAssignmentHistory.id)).where(
                    TaskAssignmentHistory.task_id == task_id
                )
            )
        ).scalar_one()
        count_act_before = (
            await db.execute(
                select(func.count(ActivityLog.id)).where(ActivityLog.task_id == task_id)
            )
        ).scalar_one()
        count_notif_before = (
            await db.execute(
                select(func.count(Notification.id)).where(
                    Notification.task_id == task_id
                )
            )
        ).scalar_one()

        try:
            # 1. Modify Task in session
            task.assigned_to = frontend_dev_id
            db.add(task)
            print("   [1/5] Staged task assignee change -> Frontend Dev")

            # 2. Add Assignment History in session
            db.add(
                TaskAssignmentHistory(
                    task_id=task_id,
                    previous_assignee_id=backend_dev_id,
                    new_assignee_id=frontend_dev_id,
                    assigned_by_id=lead_user_id,
                )
            )
            print("   [2/5] Staged TaskAssignmentHistory (Backend -> Frontend)")

            # 3. Add Activity in session
            db.add(
                ActivityLog(
                    task_id=task_id,
                    actor_id=lead_user_id,
                    action="task.assigned",
                    details={"attempt": "failed_reassignment"},
                )
            )
            print("   [3/5] Staged ActivityLog")

            # Simulate Failure at Step 5
            print(
                "   [4/5] Simulating network/database failure during Notification dispatch..."
            )
            raise RuntimeError(
                "CRITICAL: Notification dispatch failed due to downstream timeout!"
            )

            # 5. Commit (will not be reached)
            await db.commit()

        except RuntimeError as simulated_err:
            print(f"\n   [!] Caught simulated exception: {simulated_err}")
            print(
                "   [!] Executing 'await db.rollback()' to revert all uncommitted changes..."
            )
            await db.rollback()
            print("   [!] Rollback complete.")

        # PROOF OF ROLLBACK
        task = (await db.execute(select(Task).where(Task.id == task_id))).scalar_one()
        count_assign_after = (
            await db.execute(
                select(func.count(TaskAssignmentHistory.id)).where(
                    TaskAssignmentHistory.task_id == task_id
                )
            )
        ).scalar_one()
        count_act_after = (
            await db.execute(
                select(func.count(ActivityLog.id)).where(ActivityLog.task_id == task_id)
            )
        ).scalar_one()
        count_notif_after = (
            await db.execute(
                select(func.count(Notification.id)).where(
                    Notification.task_id == task_id
                )
            )
        ).scalar_one()

        print("\n--- Rollback Proof Verification ---")
        print(
            f"Task Assignee in DB     : {task.assigned_to} (Expected: {state_before_task_assignee} [Backend Dev]) -> {'VERIFIED MATCH' if task.assigned_to == state_before_task_assignee else 'FAILED'}"
        )
        print(
            f"Assignment History Rows : Before={count_assign_before} | After={count_assign_after} (Delta=+0) -> {'ZERO PARTIAL WRITES' if count_assign_before == count_assign_after else 'LEAKED'}"
        )
        print(
            f"Activity Log Rows       : Before={count_act_before} | After={count_act_after} (Delta=+0) -> {'ZERO PARTIAL WRITES' if count_act_before == count_act_after else 'LEAKED'}"
        )
        print(
            f"Notification Rows       : Before={count_notif_before} | After={count_notif_after} (Delta=+0) -> {'ZERO PARTIAL WRITES' if count_notif_before == count_notif_after else 'LEAKED'}"
        )

        # -------------------------------------------------------------
        # SCENARIO 3: Re-assignment Flow & Lineage
        # -------------------------------------------------------------
        print_step(
            4, "SCENARIO 3: Successful Re-assignment Flow (Backend Dev -> Frontend Dev)"
        )
        now_reassign = datetime.now(UTC).replace(tzinfo=None)

        task.assigned_to = frontend_dev_id
        task.assigned_by = lead_user_id
        task.updated_at = now_reassign
        db.add(task)

        reassign_hist = TaskAssignmentHistory(
            task_id=task_id,
            previous_assignee_id=backend_dev_id,
            new_assignee_id=frontend_dev_id,
            assigned_by_id=lead_user_id,
            created_at=now_reassign,
        )
        db.add(reassign_hist)

        reassign_act = ActivityLog(
            task_id=task_id,
            actor_id=lead_user_id,
            action="task.assigned",
            details={
                "previous_assignee_id": str(backend_dev_id),
                "new_assignee_id": str(frontend_dev_id),
                "comment": "Transferred frontend subtasks to Frontend Dev",
            },
            created_at=now_reassign,
        )
        db.add(reassign_act)

        reassign_notif = Notification(
            recipient_id=frontend_dev_id,
            task_id=task_id,
            type="task_assignment",
            message=f"You have been assigned to task '{task.title}'.",
            is_read=False,
            created_at=now_reassign,
        )
        db.add(reassign_notif)

        await db.commit()
        print(">> Re-assignment transaction committed successfully!")

        all_hist = (
            (
                await db.execute(
                    select(TaskAssignmentHistory)
                    .where(TaskAssignmentHistory.task_id == task_id)
                    .order_by(TaskAssignmentHistory.created_at.asc())
                )
            )
            .scalars()
            .all()
        )
        print(f"\nTask Assignment Lineage History ({len(all_hist)} entries):")
        for idx, h in enumerate(all_hist, 1):
            prev_str = (
                f"User {h.previous_assignee_id}"
                if h.previous_assignee_id
                else "None (Unassigned)"
            )
            print(
                f"  {idx}. [Prev: {prev_str}] -> [New: User {h.new_assignee_id}] by [Assigner: User {h.assigned_by_id}] at {h.created_at}"
            )

        # -------------------------------------------------------------
        # SCENARIO 4: Database Constraints Enforcement
        # -------------------------------------------------------------
        print_step(5, "SCENARIO 4: Database-Level Constraints Enforcement")

        # 4a. Unique Email Constraint
        print("4a. Testing UNIQUE constraint on user.email...")
        duplicate_user = User(
            name="Duplicate Email Tester",
            username=f"dup_{run_id}",
            email=lead_user_email,  # duplicate
            password_hash="pw",
            role="user",
        )
        db.add(duplicate_user)
        try:
            await db.commit()
            print("   FAILED: Duplicate email was accepted!")
        except IntegrityError:
            await db.rollback()
            print(
                "   SUCCESS: Postgres rejected duplicate email with IntegrityError (UNIQUE constraint)"
            )

        # 4b. Unique Project Slug Constraint
        print("\n4b. Testing UNIQUE constraint on project.slug...")
        duplicate_project = Project(
            title="Duplicate Slug Project",
            slug=project_slug,  # duplicate slug
            description="Duplicate slug test",
            priority="LOW",
            status=ProjectStatus.ACTIVE,
            owner_id=lead_user_id,
        )
        db.add(duplicate_project)
        try:
            await db.commit()
            print("   FAILED: Duplicate slug was accepted!")
        except IntegrityError:
            await db.rollback()
            print(
                "   SUCCESS: Postgres rejected duplicate slug with IntegrityError (UNIQUE constraint)"
            )

        # 4c. Foreign Key Constraint on Notification Recipient
        print("\n4c. Testing FOREIGN KEY constraint on notification.recipient_id...")
        fake_recipient_id = uuid.uuid4()
        invalid_notif = Notification(
            recipient_id=fake_recipient_id,
            task_id=task_id,
            type="invalid_fk_test",
            message="This should violate foreign key",
        )
        db.add(invalid_notif)
        try:
            await db.commit()
            print("   FAILED: Non-existent recipient ID was accepted!")
        except IntegrityError:
            await db.rollback()
            print(
                "   SUCCESS: Postgres rejected non-existent foreign key with IntegrityError (FOREIGN KEY constraint)"
            )

    await engine.dispose()
    print_banner("All Demo Scenarios Completed Successfully!")


if __name__ == "__main__":
    asyncio.run(main())
