"""Task status transition domain workflow.

Holds the business rules for moving a task through its lifecycle:

    todo -> in_progress -> in_review -> done

Design notes:
- Pure domain logic: no FastAPI/HTTP, no database, no repository access.
- Invalid transitions raise the domain-level ``InvalidTransitionError``;
  translating that into an HTTP response is the service layer's job.
- The service layer orchestrates (auth, persistence, audit trail); this
  workflow only decides whether a state change is legal.
"""

from __future__ import annotations

from typing import ClassVar

from app.models.task import TaskStatus


class InvalidTransitionError(Exception):
    """Domain error: a status change violates the workflow rules.

    Carries structured fields so callers (services/API) can build a
    consistent error response without the workflow knowing about HTTP.
    """

    def __init__(
        self,
        current: TaskStatus,
        target: TaskStatus,
        allowed: frozenset[TaskStatus],
    ) -> None:
        self.current = current
        self.target = target
        self.allowed = allowed
        allowed_list = (
            ", ".join(sorted(s.value for s in allowed))
            if allowed
            else "none (terminal state)"
        )
        super().__init__(
            f"Invalid task status transition {current.value} -> {target.value}; "
            f"allowed from {current.value}: {allowed_list}"
        )


class TaskStatusWorkflow:
    """Task status transition engine — the single source of truth for moves."""

    # todo -> in_progress -> in_review -> done; DONE and CANCELLED are terminal.
    TRANSITIONS: ClassVar[dict[TaskStatus, frozenset[TaskStatus]]] = {
        TaskStatus.TODO: frozenset({TaskStatus.IN_PROGRESS}),
        TaskStatus.IN_PROGRESS: frozenset({TaskStatus.IN_REVIEW}),
        TaskStatus.IN_REVIEW: frozenset({TaskStatus.DONE}),
        TaskStatus.DONE: frozenset(),
        TaskStatus.CANCELLED: frozenset(),
    }

    START: TaskStatus = TaskStatus.TODO
    FINAL: TaskStatus = TaskStatus.DONE

    @classmethod
    def allowed_next(cls, status: TaskStatus) -> frozenset[TaskStatus]:
        """Statuses that may directly follow `status`."""
        return cls.TRANSITIONS.get(status, frozenset())

    @classmethod
    def is_terminal(cls, status: TaskStatus) -> bool:
        """True when no transition can leave this status."""
        return not cls.allowed_next(status)

    @classmethod
    def can_transition(cls, current: TaskStatus, target: TaskStatus) -> bool:
        """True when `current -> target` is a legal workflow step."""
        if current == target:
            return False
        return target in cls.allowed_next(current)

    @classmethod
    def validate(cls, current: TaskStatus, target: TaskStatus) -> None:
        """Accept a legal transition; reject an illegal one.

        Raises:
            InvalidTransitionError: when `current -> target` breaks the rules.
        """
        if not cls.can_transition(current, target):
            raise InvalidTransitionError(
                current=current,
                target=target,
                allowed=cls.allowed_next(current),
            )
