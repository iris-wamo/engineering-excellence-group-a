#!/usr/bin/env python3
"""
Simulate a PostgreSQL Row Lock and Deadlock scenario.

This script opens two concurrent async database connections:
- Transaction 1: Locks Task A, sleeps briefly, then attempts to update Task B.
- Transaction 2: Locks Task B, sleeps briefly, then attempts to update Task A.

PostgreSQL detects the circular wait and raises a DeadlockDetected error (SQLSTATE 40P01).
"""

import asyncio
import os
import uuid
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# Database URL from environment or default local postgres
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://user:123456@localhost:5432/taskflow"
)

# Static UUIDs for the demo
TASK_A_ID = str(uuid.UUID("11111111-1111-1111-1111-111111111111"))
TASK_B_ID = str(uuid.UUID("22222222-2222-2222-2222-222222222222"))
PROJECT_ID = str(uuid.UUID("33333333-3333-3333-3333-333333333333"))
USER_ID = str(uuid.UUID("44444444-4444-4444-4444-444444444444"))


async def setup_test_data(engine):
    """Seed test user, project, and two tasks into PostgreSQL."""
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        async with session.begin():
            # Clean up existing demo data
            await session.execute(text("DELETE FROM task WHERE id IN (:a, :b)"), {"a": TASK_A_ID, "b": TASK_B_ID})
            await session.execute(text("DELETE FROM project WHERE id = :p"), {"p": PROJECT_ID})
            await session.execute(text("DELETE FROM \"user\" WHERE id = :u"), {"u": USER_ID})

            # Create User
            await session.execute(text("""
                INSERT INTO "user" (id, name, username, email, password_hash, role)
                VALUES (:id, 'Deadlock Test User', 'deadlock_user', 'deadlock@example.com', 'hash', 'user')
            """), {"id": USER_ID})

            # Create Project (including required priority column added in migration 616f4258fef2)
            await session.execute(text("""
                INSERT INTO project (id, title, status, priority, owner_id)
                VALUES (:id, 'Deadlock Demo Project', 'ACTIVE', 'MEDIUM', :owner_id)
            """), {"id": PROJECT_ID, "owner_id": USER_ID})

            # Create Task A & Task B
            await session.execute(text("""
                INSERT INTO task (id, project_id, title, status, priority, created_at, updated_at)
                VALUES (:id, :project_id, 'Task A', 'TODO', 'MEDIUM', NOW(), NOW())
            """), {"id": TASK_A_ID, "project_id": PROJECT_ID})

            await session.execute(text("""
                INSERT INTO task (id, project_id, title, status, priority, created_at, updated_at)
                VALUES (:id, :project_id, 'Task B', 'TODO', 'MEDIUM', NOW(), NOW())
            """), {"id": TASK_B_ID, "project_id": PROJECT_ID})

    print("✅ Test data seeded successfully: Task A and Task B created.")


async def transaction_1(engine):
    """Transaction 1: Locks Task A -> sleeps -> Tries to lock Task B."""
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with async_session() as session:
            async with session.begin():
                print("[Transaction 1] BEGIN")
                print("[Transaction 1] Locking Task A...")
                await session.execute(
                    text("UPDATE task SET status = 'IN_PROGRESS' WHERE id = :id"),
                    {"id": TASK_A_ID}
                )
                print("[Transaction 1] Task A locked. Sleeping 1 second...")
                await asyncio.sleep(1.0)

                print("[Transaction 1] Attempting to lock Task B...")
                await session.execute(
                    text("UPDATE task SET status = 'DONE' WHERE id = :id"),
                    {"id": TASK_B_ID}
                )
                print("[Transaction 1] SUCCESS (No deadlock)")
    except Exception as e:
        print(f"\n❌ [Transaction 1 Error]: {type(e).__name__}: {e}\n")


async def transaction_2(engine):
    """Transaction 2: Locks Task B -> sleeps -> Tries to lock Task A."""
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with async_session() as session:
            async with session.begin():
                print("[Transaction 2] BEGIN")
                print("[Transaction 2] Locking Task B...")
                await session.execute(
                    text("UPDATE task SET status = 'IN_PROGRESS' WHERE id = :id"),
                    {"id": TASK_B_ID}
                )
                print("[Transaction 2] Task B locked. Sleeping 1 second...")
                await asyncio.sleep(1.0)

                print("[Transaction 2] Attempting to lock Task A...")
                await session.execute(
                    text("UPDATE task SET status = 'DONE' WHERE id = :id"),
                    {"id": TASK_A_ID}
                )
                print("[Transaction 2] SUCCESS (No deadlock)")
    except Exception as e:
        print(f"\n❌ [Transaction 2 Error]: {type(e).__name__}: {e}\n")


async def main():
    print("=" * 60)
    print("PostgreSQL Row Lock & Deadlock Simulation")
    print("=" * 60)

    engine = create_async_engine(DATABASE_URL, echo=False)

    try:
        await setup_test_data(engine)

        print("\nStarting Transaction 1 and Transaction 2 concurrently...\n")
        await asyncio.gather(
            transaction_1(engine),
            transaction_2(engine)
        )
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
