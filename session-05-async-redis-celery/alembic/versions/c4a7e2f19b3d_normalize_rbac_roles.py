"""normalize rbac roles

Moves role values to the admin / manager / member vocabulary, guards them with
CHECK constraints, and makes every project owner a manager of their project so
the old "owner can manage" rule keeps working under membership-based RBAC.

Revision ID: c4a7e2f19b3d
Revises: 616f4258fef2
Create Date: 2026-10-17 12:00:00.000000

"""

from alembic import op

revision = "c4a7e2f19b3d"
down_revision = "616f4258fef2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""

    # 1. Global roles: ADMIN -> admin, MANAGER -> manager, anything else
    #    (legacy "user", "DEVELOPER", ...) -> member.
    op.execute(
        """
        UPDATE "user"
        SET role = CASE UPPER(role)
            WHEN 'ADMIN' THEN 'admin'
            WHEN 'MANAGER' THEN 'manager'
            ELSE 'member'
        END
        """
    )
    op.alter_column("user", "role", server_default="member")
    op.create_check_constraint(
        "ck_user_role_valid", "user", "role IN ('admin', 'manager', 'member')"
    )

    # 2. Project roles: OWNER / MANAGER -> manager, anything else -> member.
    op.execute(
        """
        UPDATE project_member
        SET member_role = CASE UPPER(member_role)
            WHEN 'OWNER' THEN 'manager'
            WHEN 'MANAGER' THEN 'manager'
            ELSE 'member'
        END
        """
    )
    op.alter_column("project_member", "member_role", server_default="member")
    op.create_check_constraint(
        "ck_project_member_role_valid",
        "project_member",
        "member_role IN ('manager', 'member')",
    )

    # 3. Every project owner manages their own project.
    op.execute(
        """
        INSERT INTO project_member (project_id, user_id, member_role)
        SELECT id, owner_id, 'manager' FROM project
        ON CONFLICT (project_id, user_id)
        DO UPDATE SET member_role = 'manager'
        """
    )

    # 4. Owners who manage a project need the global manager role to create
    #    more; admins keep admin.
    op.execute(
        """
        UPDATE "user" SET role = 'manager'
        WHERE role = 'member'
          AND id IN (SELECT owner_id FROM project)
        """
    )

    # 5. Membership lookups by user ("my projects") run on every request.
    op.create_index("ix_project_member_user_id", "project_member", ["user_id"])


def downgrade() -> None:
    """Downgrade schema.

    Role values go back to the legacy upper-case spelling. Owner membership
    rows added in step 3 are kept: they are valid data under the old rules.
    """

    op.drop_index("ix_project_member_user_id", table_name="project_member")

    op.drop_constraint("ck_project_member_role_valid", "project_member", type_="check")
    op.alter_column("project_member", "member_role", server_default=None)
    op.execute(
        """
        UPDATE project_member
        SET member_role = CASE member_role
            WHEN 'manager' THEN 'MANAGER'
            ELSE 'member'
        END
        """
    )

    op.drop_constraint("ck_user_role_valid", "user", type_="check")
    op.alter_column("user", "role", server_default=None)
    op.execute(
        """
        UPDATE "user"
        SET role = CASE role
            WHEN 'admin' THEN 'ADMIN'
            WHEN 'manager' THEN 'MANAGER'
            ELSE 'user'
        END
        """
    )
