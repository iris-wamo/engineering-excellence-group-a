from fastapi import HTTPException, status


class EmailAlreadyExistsError(HTTPException):
    """Raised when a user attempts to register with an email that is already taken."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "EMAIL_ALREADY_EXISTS",
                    "message": "User with this email already exists",
                }
            },
        )


class UsernameAlreadyExistsError(HTTPException):
    """Raised when a user attempts to register with a username that is already taken."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "USERNAME_ALREADY_EXISTS",
                    "message": "User with this username already exists",
                }
            },
        )


class UserNotFoundError(HTTPException):
    """Raised when a requested user cannot be found by ID or query."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "USER_NOT_FOUND",
                    "message": "User not found",
                }
            },
        )


class ProjectNotFoundError(HTTPException):
    """Raised when a requested project cannot be found by ID."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "PROJECT_NOT_FOUND",
                    "message": "Project not found",
                }
            },
        )


class TaskNotFoundError(HTTPException):
    """Raised when a requested task cannot be found by ID."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "TASK_NOT_FOUND",
                    "message": "Task not found",
                }
            },
        )


class AssigneeNotFoundError(HTTPException):
    """Raised when a referenced assignee cannot be found by ID."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "ASSIGNEE_NOT_FOUND",
                    "message": "Assignee not found",
                }
            },
        )


class AssignedByNotFoundError(HTTPException):
    """Raised when the assigning user cannot be found by ID."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "ASSIGNED_BY_NOT_FOUND",
                    "message": "Assigning user not found",
                }
            },
        )


class InvalidStatusTransitionError(HTTPException):
    """Raised when a task status change violates the allowed workflow (todo -> in_progress -> review -> done)."""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "INVALID_STATUS_TRANSITION",
                    "message": (
                        f"Cannot transition task status from '{current}' to '{target}'"
                    ),
                }
            },
        )


class MissingUserHeaderError(HTTPException):
    """Raised when the X-User-ID header identifying the acting user is absent."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "MISSING_USER_HEADER",
                    "message": "X-User-ID header is required for this operation",
                }
            },
        )


class CurrentUserNotFoundError(HTTPException):
    """Raised when the X-User-ID header does not match any existing user."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "CURRENT_USER_NOT_FOUND",
                    "message": "Current user not found",
                }
            },
        )


class StatusChangeForbiddenError(HTTPException):
    """Raised when the acting user may not change a task's status (RBAC rule)."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "STATUS_CHANGE_FORBIDDEN",
                    "message": (
                        "Only the assignee, a project owner/manager, or an admin "
                        "can change a task's status"
                    ),
                }
            },
        )


class SimulatedAssignmentFailureError(HTTPException):
    """Raised when simulating a mid-transaction failure for rollback testing and demo."""

    def __init__(
        self, message: str = "Simulated mid-transaction failure triggered"
    ) -> None:
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "SIMULATED_TRANSACTION_FAILURE",
                    "message": message,
                }
            },
        )
