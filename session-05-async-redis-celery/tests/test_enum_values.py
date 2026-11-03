from app.models.project import ProjectStatus
from app.models.task import TaskPriority, TaskStatus


def test_project_status_values_match_database_enum() -> None:
    assert ProjectStatus.ACTIVE.value == "ACTIVE"
    assert ProjectStatus.INACTIVE.value == "INACTIVE"
    assert ProjectStatus.ARCHIVED.value == "ARCHIVED"


def test_task_enum_values_match_database_enum() -> None:
    assert TaskStatus.TODO.value == "TODO"
    assert TaskStatus.IN_PROGRESS.value == "IN_PROGRESS"
    assert TaskStatus.IN_REVIEW.value == "IN_REVIEW"
    assert TaskStatus.DONE.value == "DONE"
    assert TaskStatus.CANCELLED.value == "CANCELLED"

    assert TaskPriority.LOW.value == "LOW"
    assert TaskPriority.MEDIUM.value == "MEDIUM"
    assert TaskPriority.HIGH.value == "HIGH"
    assert TaskPriority.URGENT.value == "URGENT"
