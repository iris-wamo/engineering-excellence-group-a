"""Task summary: async (concurrent) vs blocking (sequential) mode."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.auth.permissions import is_admin
from app.core.config import settings
from app.db.database import SessionFactory
from app.models.task import TaskStatus
from app.models.user import User
from app.repositories.task_repository import TaskRepository
from app.schemas.task_summary import (
    ExternalResult,
    ExternalStatus,
    SummaryMode,
    TaskSummaryResponse,
)


class SimulatedExternalError(RuntimeError):
    """Fake external service failure."""


@dataclass(frozen=True)
class ExternalCallConfig:
    delay_seconds: float
    timeout_seconds: float
    fail: bool = False

    @classmethod
    def from_settings(
        cls, *, delay: float | None = None, fail: bool | None = None
    ) -> ExternalCallConfig:
        return cls(
            delay_seconds=(
                settings.SUMMARY_EXTERNAL_DELAY_SECONDS if delay is None else delay
            ),
            timeout_seconds=settings.SUMMARY_EXTERNAL_TIMEOUT_SECONDS,
            fail=settings.SUMMARY_EXTERNAL_FAIL if fail is None else fail,
        )


def _payload() -> dict[str, Any]:
    return {"service": "reporting", "healthy": True}


async def call_external_async(config: ExternalCallConfig) -> dict[str, Any]:
    """Fake call that doesn't block the event loop."""
    await asyncio.sleep(config.delay_seconds)
    if config.fail:
        raise SimulatedExternalError("simulated external failure")
    return _payload()


async def call_external_blocking(config: ExternalCallConfig) -> dict[str, Any]:
    """Fake call that blocks the event loop on purpose.

    wait_for can't interrupt time.sleep, so it applies its own timeout
    (like requests' timeout=).
    """
    time.sleep(min(config.delay_seconds, config.timeout_seconds))
    if config.delay_seconds > config.timeout_seconds:
        raise TimeoutError("blocking client timed out")
    if config.fail:
        raise SimulatedExternalError("simulated external failure")
    return _payload()


async def run_external(
    config: ExternalCallConfig, *, blocking: bool = False
) -> ExternalResult:
    """Run the external call with a timeout; never raises."""
    call = call_external_blocking if blocking else call_external_async
    started = time.perf_counter()
    try:
        data = await asyncio.wait_for(call(config), timeout=config.timeout_seconds)
    except TimeoutError:
        return ExternalResult(status=ExternalStatus.TIMEOUT, elapsed_ms=_ms(started))
    except SimulatedExternalError as exc:
        return ExternalResult(
            status=ExternalStatus.ERROR, elapsed_ms=_ms(started), detail=str(exc)
        )
    return ExternalResult(status=ExternalStatus.OK, elapsed_ms=_ms(started), data=data)


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)


class TaskSummaryService:
    @staticmethod
    async def get_summary(
        session_factory: SessionFactory,
        actor: User,
        *,
        mode: SummaryMode,
        external: ExternalCallConfig,
    ) -> TaskSummaryResponse:
        """Non-admins only see tasks in their projects."""
        scope = None if is_admin(actor) else actor.id
        now = datetime.now(UTC)

        async def by_status() -> dict[TaskStatus, int]:
            async with session_factory() as db:
                return await TaskRepository.count_by_status(db, member_user_id=scope)

        async def overdue() -> int:
            async with session_factory() as db:
                return await TaskRepository.count_overdue(
                    db, now=now, member_user_id=scope
                )

        async def assigned() -> int:
            async with session_factory() as db:
                return await TaskRepository.count_assigned_to(
                    db, actor.id, member_user_id=scope
                )

        started = time.perf_counter()
        if mode is SummaryMode.ASYNC:
            counts, overdue_count, assigned_count, ext = await asyncio.gather(
                by_status(), overdue(), assigned(), run_external(external)
            )
        else:
            counts = await by_status()
            overdue_count = await overdue()
            assigned_count = await assigned()
            ext = await run_external(external, blocking=True)

        by_status_api = {s.value.lower(): counts.get(s, 0) for s in TaskStatus}
        return TaskSummaryResponse(
            mode=mode,
            by_status=by_status_api,
            total=sum(by_status_api.values()),
            overdue=overdue_count,
            assigned_to_me=assigned_count,
            external=ext,
            elapsed_ms=_ms(started),
        )
