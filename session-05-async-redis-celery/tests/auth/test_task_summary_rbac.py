"""GET /tasks/summary scoping against the test DB."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.api.dependencies.deps import get_session_factory
from app.main import app
from tests.auth.conftest import World


async def _summary(client: AsyncClient, headers: dict[str, str], mode: str) -> dict:
    response = await client.get(
        "/tasks/summary", params={"mode": mode}, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["async", "blocking"])
async def test_summary_is_scoped_to_caller(
    client: AsyncClient, session_factory, world: World, mode: str
):
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()

    # carol's task: overdue. dave's task: past due but cancelled, so not overdue.
    for task_id in (world.carol_task_id, world.dave_task_id):
        res = await client.patch(
            f"/tasks/{task_id}", json={"due_date": past}, headers=world.alice.headers
        )
        assert res.status_code == 200, res.text
    res = await client.patch(
        f"/tasks/{world.dave_task_id}/status",
        json={"status": "cancelled"},
        headers=world.alice.headers,
    )
    assert res.status_code == 200, res.text

    alice = await _summary(client, world.alice.headers, mode)
    assert alice["total"] == 2
    assert alice["by_status"]["todo"] == 1
    assert alice["by_status"]["cancelled"] == 1
    assert alice["overdue"] == 1
    assert alice["assigned_to_me"] == 0

    carol = await _summary(client, world.carol.headers, mode)
    assert carol["total"] == 2
    assert carol["assigned_to_me"] == 1

    for outsider in (world.bob, world.erin):
        body = await _summary(client, outsider.headers, mode)
        assert body["total"] == 0
        assert body["overdue"] == 0
        assert body["assigned_to_me"] == 0

    # admins see every project, so at least this one
    admin = await _summary(client, world.admin.headers, mode)
    assert admin["total"] >= 2
    assert admin["overdue"] >= 1
