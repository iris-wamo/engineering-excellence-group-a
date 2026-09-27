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
