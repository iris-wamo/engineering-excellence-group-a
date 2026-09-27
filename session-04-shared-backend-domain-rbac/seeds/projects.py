from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from seeds.users import ADMIN_ID, MANAGER_ID

PROJECT_1_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PROJECT_2_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

PROJECTS = [
    {
        "id": PROJECT_1_ID,
        "title": "Website Redesign",
        "slug": "website-redesign",
        "description": "Redesign the company website.",
        "status": "ACTIVE",
        "deadline": datetime.utcnow() + timedelta(days=30),
        "owner_id": MANAGER_ID,
    },
    {
        "id": PROJECT_2_ID,
        "title": "Mobile Application",
        "slug": "mobile-application",
        "description": "Build the new mobile application.",
        "status": "ACTIVE",
        "deadline": datetime.utcnow() + timedelta(days=60),
        "owner_id": ADMIN_ID,
    },
]

PROJECT_MEMBERS = [
    {"project_id": PROJECT_1_ID, "user_id": MANAGER_ID, "member_role": "OWNER"},
    {
        "project_id": PROJECT_1_ID,
        "user_id": UUID("33333333-3333-3333-3333-333333333333"),
        "member_role": "DEVELOPER",
    },
    {"project_id": PROJECT_2_ID, "user_id": ADMIN_ID, "member_role": "OWNER"},
    {
        "project_id": PROJECT_2_ID,
        "user_id": UUID("33333333-3333-3333-3333-333333333333"),
        "member_role": "DEVELOPER",
    },
]
