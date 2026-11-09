"""Validate due-date input and partial-update semantics without database services."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.task import TaskCreate, TaskResponse, TaskUpdate


@pytest.mark.parametrize("due_date", [None, datetime.now(UTC) + timedelta(days=1)])
def test_create_accepts_optional_or_future_due_date(due_date):
    payload = TaskCreate(title="Due-date test", project_id=uuid4(), due_date=due_date)
    assert payload.due_date == due_date


def test_create_can_omit_due_date():
    payload = TaskCreate(title="No due date", project_id=uuid4())
    assert payload.due_date is None


@pytest.mark.parametrize("offset_hours", [-5, 0, 5])
def test_create_rejects_past_instants_in_different_timezones(offset_hours):
    past = (datetime.now(UTC) - timedelta(minutes=1)).astimezone(
        timezone(timedelta(hours=offset_hours))
    )
    with pytest.raises(ValidationError, match="due_date must not be in the past"):
        TaskCreate(title="Past due date", project_id=uuid4(), due_date=past)


def test_create_accepts_future_iso_timestamp_with_offset():
    future = (datetime.now(UTC) + timedelta(days=1)).astimezone(
        timezone(timedelta(hours=5))
    )
    payload = TaskCreate.model_validate(
        {
            "title": "Future due date",
            "project_id": str(uuid4()),
            "due_date": future.isoformat(),
        }
    )
    assert payload.due_date == future


@pytest.mark.parametrize("schema", [TaskCreate, TaskUpdate])
def test_inputs_reject_datetime_without_timezone(schema):
    with pytest.raises(ValidationError, match="timezone info"):
        schema.model_validate(
            {
                "title": "Missing timezone",
                "project_id": str(uuid4()),
                "due_date": "2030-01-01T12:00:00",
            }
        )


def test_update_distinguishes_omission_from_explicit_null():
    assert TaskUpdate().model_dump(exclude_unset=True) == {}
    assert TaskUpdate(due_date=None).model_dump(exclude_unset=True) == {
        "due_date": None
    }


def test_update_and_response_allow_an_overdue_date():
    past = datetime.now(UTC) - timedelta(days=1)
    assert TaskUpdate(due_date=past).due_date == past
    response = TaskResponse(
        id=uuid4(),
        title="Overdue task",
        description=None,
        priority="medium",
        status="todo",
        project_id=uuid4(),
        assignee_id=None,
        estimated_time=None,
        deadline=None,
        due_date=past,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    assert response.due_date == past
