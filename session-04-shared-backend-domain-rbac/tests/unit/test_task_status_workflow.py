"""Unit tests for the task status transition domain workflow.

Pure domain tests: no database, no HTTP client — the workflow must be
testable in isolation per the Session 4 workflow SLO.
"""

import pytest

from app.models.task import TaskStatus
from app.workflows.task_status_workflow import (
    InvalidTransitionError,
    TaskStatusWorkflow,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (TaskStatus.TODO, TaskStatus.IN_PROGRESS),
        (TaskStatus.IN_PROGRESS, TaskStatus.IN_REVIEW),
        (TaskStatus.IN_REVIEW, TaskStatus.DONE),
    ],
)
def test_valid_transitions_are_accepted(current, target):
    assert TaskStatusWorkflow.can_transition(current, target) is True
    TaskStatusWorkflow.validate(current, target)  # must not raise


@pytest.mark.parametrize(
    ("current", "target"),
    [
        # skipping steps
        (TaskStatus.TODO, TaskStatus.IN_REVIEW),
        (TaskStatus.TODO, TaskStatus.DONE),
        (TaskStatus.IN_PROGRESS, TaskStatus.DONE),
        # backwards moves
        (TaskStatus.DONE, TaskStatus.IN_REVIEW),
        (TaskStatus.IN_PROGRESS, TaskStatus.TODO),
        # terminal states are frozen
        (TaskStatus.DONE, TaskStatus.TODO),
        (TaskStatus.CANCELLED, TaskStatus.IN_PROGRESS),
        # same status is not a transition
        (TaskStatus.TODO, TaskStatus.TODO),
    ],
)
def test_invalid_transitions_are_rejected(current, target):
    assert TaskStatusWorkflow.can_transition(current, target) is False
    with pytest.raises(InvalidTransitionError):
        TaskStatusWorkflow.validate(current, target)


def test_rejection_error_is_consistent_and_structured():
    with pytest.raises(InvalidTransitionError) as exc_info:
        TaskStatusWorkflow.validate(TaskStatus.TODO, TaskStatus.DONE)

    err = exc_info.value
    assert err.current == TaskStatus.TODO
    assert err.target == TaskStatus.DONE
    assert err.allowed == frozenset({TaskStatus.IN_PROGRESS})
    # One consistent message shape for every invalid transition
    message = str(err)
    assert "TODO -> DONE" in message
    assert "IN_PROGRESS" in message


def test_error_is_domain_level_not_http():
    """The workflow must not leak FastAPI/HTTP types."""
    from fastapi import HTTPException

    assert not issubclass(InvalidTransitionError, HTTPException)
    assert not hasattr(InvalidTransitionError, "status_code")
    assert not hasattr(InvalidTransitionError, "detail")

    # No fastapi import anywhere in the workflow module
    import app.workflows.task_status_workflow as workflow_module

    assert "fastapi" not in vars(workflow_module)


def test_terminal_states_have_no_outgoing_edges():
    assert TaskStatusWorkflow.is_terminal(TaskStatus.DONE) is True
    assert TaskStatusWorkflow.is_terminal(TaskStatus.CANCELLED) is True
    assert TaskStatusWorkflow.is_terminal(TaskStatus.TODO) is False


def test_workflow_knows_the_full_allowed_graph():
    """Every status in the enum must be covered by the workflow map."""
    assert set(TaskStatusWorkflow.TRANSITIONS) == set(TaskStatus)
    assert TaskStatusWorkflow.allowed_next(TaskStatus.TODO) == frozenset(
        {TaskStatus.IN_PROGRESS}
    )
    assert TaskStatusWorkflow.allowed_next(TaskStatus.DONE) == frozenset()
    assert TaskStatusWorkflow.START == TaskStatus.TODO
    assert TaskStatusWorkflow.FINAL == TaskStatus.DONE
