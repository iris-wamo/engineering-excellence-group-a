from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID, uuid5

from seeds.projects import PROJECT_1_ID, PROJECT_2_ID
from seeds.users import ADMIN_ID, DEVELOPER_ID, MANAGER_ID

# ---------------------------------------------------------------------------
# Fixed IDs for the small, realistic seed data
# ---------------------------------------------------------------------------

TASK_1_ID = UUID("aaaaaaaa-1111-1111-1111-111111111111")
TASK_2_ID = UUID("aaaaaaaa-2222-2222-2222-222222222222")
TASK_3_ID = UUID("bbbbbbbb-3333-3333-3333-333333333333")

ACTIVITY_1_ID = UUID("aaaa1111-1111-1111-1111-111111111111")
ACTIVITY_2_ID = UUID("aaaa2222-2222-2222-2222-222222222222")

NOTIFICATION_1_ID = UUID("bbbb1111-1111-1111-1111-111111111111")

ASSIGNMENT_HISTORY_1_ID = UUID("cccc1111-1111-1111-1111-111111111111")

STATUS_HISTORY_1_ID = UUID("dddd1111-1111-1111-1111-111111111111")

STATUS_HISTORY_2_ID = UUID("dddd2222-2222-2222-2222-222222222222")


# ---------------------------------------------------------------------------
# Realistic seed tasks
# ---------------------------------------------------------------------------

NOW = datetime.utcnow()

BASE_TASKS = [
    {
        "id": TASK_1_ID,
        "project_id": PROJECT_1_ID,
        "assigned_to": DEVELOPER_ID,
        "assigned_by": MANAGER_ID,
        "title": "Create homepage",
        "description": "Implement the new homepage design.",
        "priority": "HIGH",
        "status": "IN_PROGRESS",
        "estimated_time": 480,
        "deadline": NOW + timedelta(days=7),
        "created_at": NOW,
        "updated_at": NOW,
    },
    {
        "id": TASK_2_ID,
        "project_id": PROJECT_1_ID,
        "assigned_to": DEVELOPER_ID,
        "assigned_by": MANAGER_ID,
        "title": "Add authentication",
        "description": "Implement login and registration.",
        "priority": "MEDIUM",
        "status": "TODO",
        "estimated_time": 360,
        "deadline": NOW + timedelta(days=10),
        "created_at": NOW,
        "updated_at": NOW,
    },
    {
        "id": TASK_3_ID,
        "project_id": PROJECT_2_ID,
        "assigned_to": DEVELOPER_ID,
        "assigned_by": ADMIN_ID,
        "title": "Setup mobile project",
        "description": "Create the initial mobile application structure.",
        "priority": "URGENT",
        "status": "IN_REVIEW",
        "estimated_time": 240,
        "deadline": NOW + timedelta(days=5),
        "created_at": NOW,
        "updated_at": NOW,
    },
]


# ---------------------------------------------------------------------------
# Performance seed data
# ---------------------------------------------------------------------------

PERFORMANCE_TASK_COUNT = 100_000

PERFORMANCE_NAMESPACE = UUID("12345678-1234-5678-1234-567812345678")

STATUSES = [
    "TODO",
    "IN_PROGRESS",
    "IN_REVIEW",
    "DONE",
    "CANCELLED",
]

PRIORITIES = [
    "LOW",
    "MEDIUM",
    "HIGH",
    "URGENT",
]

SEED_USERS = [
    ADMIN_ID,
    MANAGER_ID,
    DEVELOPER_ID,
]

SEED_PROJECTS = [
    PROJECT_1_ID,
    PROJECT_2_ID,
]


def performance_task_id(index: int) -> UUID:
    """Generate a deterministic UUID for a performance task."""
    return uuid5(
        PERFORMANCE_NAMESPACE,
        f"performance-task-{index}",
    )


def generate_performance_tasks(
    count: int = PERFORMANCE_TASK_COUNT,
) -> list[dict]:
    """Generate deterministic tasks for query-performance testing."""
    now = datetime.utcnow()

    tasks = []

    for i in range(count):
        assigned_to = SEED_USERS[i % len(SEED_USERS)]
        project_id = SEED_PROJECTS[i % len(SEED_PROJECTS)]
        status = STATUSES[i % len(STATUSES)]
        priority = PRIORITIES[i % len(PRIORITIES)]

        created_at = now - timedelta(minutes=i)

        tasks.append(
            {
                "id": performance_task_id(i),
                "project_id": project_id,
                "assigned_to": assigned_to,
                "assigned_by": MANAGER_ID,
                "title": f"Performance Task {i + 1}",
                "description": (f"Generated performance test task {i + 1}"),
                "priority": priority,
                "status": status,
                "estimated_time": 30 + (i % 480),
                "deadline": now + timedelta(days=i % 30),
                "created_at": created_at,
                "updated_at": created_at,
            }
        )

    return tasks


# ---------------------------------------------------------------------------
# Complete task collection
# ---------------------------------------------------------------------------

TASKS = BASE_TASKS + generate_performance_tasks()


# ---------------------------------------------------------------------------
# Activity logs
# ---------------------------------------------------------------------------

ACTIVITY_LOGS = [
    {
        "id": ACTIVITY_1_ID,
        "task_id": TASK_1_ID,
        "actor_id": MANAGER_ID,
        "action": "TASK_ASSIGNED",
        "details": {
            "assigned_to": str(DEVELOPER_ID),
            "task": "Create homepage",
        },
        "created_at": NOW,
    },
    {
        "id": ACTIVITY_2_ID,
        "task_id": TASK_3_ID,
        "actor_id": ADMIN_ID,
        "action": "TASK_CREATED",
        "details": {
            "priority": "URGENT",
        },
        "created_at": NOW,
    },
]


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

NOTIFICATIONS = [
    {
        "id": NOTIFICATION_1_ID,
        "recipient_id": DEVELOPER_ID,
        "task_id": TASK_1_ID,
        "type": "TASK_ASSIGNED",
        "message": "You have been assigned a new task: Create homepage",
        "is_read": False,
        "created_at": NOW,
    }
]


# ---------------------------------------------------------------------------
# Task assignment history
# ---------------------------------------------------------------------------

TASK_ASSIGNMENT_HISTORY = [
    {
        "id": ASSIGNMENT_HISTORY_1_ID,
        "task_id": TASK_1_ID,
        "previous_assignee_id": None,
        "new_assignee_id": DEVELOPER_ID,
        "assigned_by_id": MANAGER_ID,
        "created_at": NOW,
    }
]


# ---------------------------------------------------------------------------
# Task status history
# ---------------------------------------------------------------------------

TASK_STATUS_HISTORY = [
    {
        "id": STATUS_HISTORY_1_ID,
        "task_id": TASK_1_ID,
        "previous_status": "TODO",
        "new_status": "IN_PROGRESS",
        "changed_by_id": DEVELOPER_ID,
        "created_at": NOW,
    },
    {
        "id": STATUS_HISTORY_2_ID,
        "task_id": TASK_3_ID,
        "previous_status": "IN_PROGRESS",
        "new_status": "IN_REVIEW",
        "changed_by_id": DEVELOPER_ID,
        "created_at": NOW,
    },
]
