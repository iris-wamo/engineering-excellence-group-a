from __future__ import annotations

from uuid import UUID

ADMIN_ID = UUID("11111111-1111-1111-1111-111111111111")
MANAGER_ID = UUID("22222222-2222-2222-2222-222222222222")
DEVELOPER_ID = UUID("33333333-3333-3333-3333-333333333333")

USERS = [
    {
        "id": ADMIN_ID,
        "name": "Admin User",
        "username": "admin",
        "email": "admin@example.com",
        "password_hash": "test-password-hash",
        "role": "ADMIN",
    },
    {
        "id": MANAGER_ID,
        "name": "Project Manager",
        "username": "manager",
        "email": "manager@example.com",
        "password_hash": "test-password-hash",
        "role": "MANAGER",
    },
    {
        "id": DEVELOPER_ID,
        "name": "Developer User",
        "username": "developer",
        "email": "developer@example.com",
        "password_hash": "test-password-hash",
        "role": "DEVELOPER",
    },
]
