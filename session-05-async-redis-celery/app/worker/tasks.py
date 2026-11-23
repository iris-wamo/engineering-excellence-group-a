"""Celery tasks."""

from sqlalchemy import text

from app.worker.celery_app import celery_app
from app.worker.db import WorkerSessionLocal, run_async


@celery_app.task(name="taskflow.ping")
def ping() -> str:
    """Round-trip check: client -> broker -> worker -> result backend."""
    return "pong"


async def _select_one() -> int:
    async with WorkerSessionLocal() as session:
        result = await session.execute(text("SELECT 1"))
        return int(result.scalar_one())


@celery_app.task(name="taskflow.db_ping")
def db_ping() -> int:
    """Check that the worker's own session factory reaches PostgreSQL."""
    return run_async(_select_one())
