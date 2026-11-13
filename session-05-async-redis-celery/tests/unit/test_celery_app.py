"""Celery configuration and worker DB isolation, without a broker or database."""

from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.db.database import AsyncSessionLocal, engine
from app.worker.celery_app import celery_app
from app.worker.db import WorkerSessionLocal, run_async, worker_engine
from app.worker.tasks import ping


def test_broker_and_backend_use_separate_redis_databases():
    assert celery_app.conf.broker_url == settings.CELERY_BROKER_URL
    assert celery_app.conf.result_backend == settings.CELERY_RESULT_BACKEND
    assert settings.CELERY_BROKER_URL.endswith("/1")
    assert settings.CELERY_RESULT_BACKEND.endswith("/2")


def test_only_json_is_serialized_or_accepted():
    conf = celery_app.conf
    assert conf.task_serializer == "json"
    assert conf.result_serializer == "json"
    assert list(conf.accept_content) == ["json"]
    assert list(conf.result_accept_content) == ["json"]


def test_delivery_and_time_limit_settings():
    conf = celery_app.conf
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.task_time_limit == settings.CELERY_TASK_TIME_LIMIT
    assert conf.task_soft_time_limit == settings.CELERY_TASK_SOFT_TIME_LIMIT
    assert conf.task_soft_time_limit < conf.task_time_limit


def test_tasks_are_registered():
    assert "taskflow.ping" in celery_app.tasks
    assert "taskflow.db_ping" in celery_app.tasks


def test_ping_runs_in_process():
    assert ping.apply().get() == "pong"


def test_worker_has_its_own_unpooled_session_factory():
    assert WorkerSessionLocal is not AsyncSessionLocal
    assert worker_engine is not engine
    assert isinstance(worker_engine.pool, NullPool)
    assert WorkerSessionLocal.kw["bind"] is worker_engine


def test_run_async_drives_a_coroutine_from_sync_code():
    async def answer() -> int:
        return 42

    assert run_async(answer()) == 42
    # A second call gets a fresh event loop and still works.
    assert run_async(answer()) == 42
