"""Celery application: Redis broker (DB 1), Redis result backend (DB 2).

Start a worker with:
    celery -A app.worker.celery_app worker --loglevel=INFO
"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "taskflow",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    # JSON only: never unpickle broker messages or results.
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_accept_content=["json"],
    # Ack after the task finishes so a crashed worker's message is redelivered.
    # Tasks must therefore be idempotent.
    task_acks_late=True,
    # Requeue (instead of failing) when the worker process is killed mid-task.
    task_reject_on_worker_lost=True,
    # Reserve one message per process at a time so long tasks don't hoard work.
    worker_prefetch_multiplier=1,
    # Soft limit raises SoftTimeLimitExceeded for cleanup; hard limit kills the process.
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
)
