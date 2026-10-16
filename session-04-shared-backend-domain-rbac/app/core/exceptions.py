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


class InvalidStatusTransitionError(HTTPException):
    """Raised when a task status change violates the allowed workflow."""

    def __init__(
        self,
        current: str,
        target: str,
        allowed: list[str] | None = None,
    ) -> None:
        allowed_statuses = allowed or []
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "INVALID_STATUS_TRANSITION",
                    "message": (
                        f"Cannot transition task status from '{current}' to '{target}'. "
                        f"Allowed transitions from '{current}': {allowed_statuses}"
                    ),
                }
            },
        )


class NotAuthenticatedError(HTTPException):
    """Raised when the bearer token is missing, invalid, expired or names no user."""

    def __init__(self, message: str = "Not authenticated") -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": message,
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


class InvalidCredentialsError(HTTPException):
    """Raised when login receives an unknown username/email or a wrong password."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "INVALID_CREDENTIALS",
                    "message": "Incorrect username/email or password",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenError(HTTPException):
    """Raised when an authenticated user's role does not allow the action."""

    def __init__(
        self, message: str = "You do not have permission to perform this action"
    ) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": message,
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
                        "Only the assignee, a manager of the project, or an admin "
                        "can change a task's status; only managers and admins "
                        "can cancel a task"
                    ),
                }
            },
        )


class InvalidRoleAssignmentError(HTTPException):
    """Raised when a user cannot take the requested role (e.g. a member as manager)."""

    def __init__(self, message: str) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": {
                    "code": "INVALID_ROLE_ASSIGNMENT",
                    "message": message,
                }
            },
        )


class CannotChangeOwnRoleError(HTTPException):
    """Raised when an admin tries to change their own global role."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "CANNOT_CHANGE_OWN_ROLE",
                    "message": "Admins cannot change their own role",
                }
            },
        )


class AlreadyProjectMemberError(HTTPException):
    """Raised when adding a user who already belongs to the project."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "code": "ALREADY_PROJECT_MEMBER",
                    "message": "User is already a member of this project",
                }
            },
        )


class ProjectMemberNotFoundError(HTTPException):
    """Raised when removing a user who is not a member of the project."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "PROJECT_MEMBER_NOT_FOUND",
                    "message": "User is not a member of this project",
                }
            },
        )


class AssigneeNotInProjectError(HTTPException):
    """Raised when a task would be assigned to someone outside its project."""

    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "error": {
                    "code": "ASSIGNEE_NOT_IN_PROJECT",
                    "message": "Assignee must be a member of the task's project",
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
