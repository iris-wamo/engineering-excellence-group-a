"""Role vocabulary shared by models, services and auth dependencies."""

from __future__ import annotations

import enum


class UserRole(enum.StrEnum):
    """Global role stored on ``user.role``.

    - admin: full control of every user, project, task and import.
    - manager: may create projects (becoming their manager) and be assigned
      to existing projects by an admin.
    - member: default for every signup; works inside projects they belong to.
    """

    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"


class ProjectRole(enum.StrEnum):
    """Per-project role stored on ``project_member.member_role``."""

    MANAGER = "manager"
    MEMBER = "member"
