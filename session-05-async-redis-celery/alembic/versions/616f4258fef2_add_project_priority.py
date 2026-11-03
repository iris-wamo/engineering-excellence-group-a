"""add project priority

Revision ID: 616f4258fef2
Revises: b8e3484c1e83
Create Date: 2026-08-31 00:58:18.753623

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "616f4258fef2"
down_revision = "b8e3484c1e83"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade schema."""

    project_priority = postgresql.ENUM(
        "LOW",
        "MEDIUM",
        "HIGH",
        name="projectpriority",
    )

    # 1. Create PostgreSQL enum type
    project_priority.create(op.get_bind(), checkfirst=True)

    # 2. Add priority column as nullable
    op.add_column(
        "project",
        sa.Column(
            "priority",
            project_priority,
            nullable=True,
        ),
    )

    # 3. Backfill existing projects
    op.execute(
        """
        UPDATE project
        SET priority = (
            CASE
                WHEN deadline IS NULL THEN 'LOW'
                WHEN deadline <= NOW() + INTERVAL '3 days' THEN 'HIGH'
                WHEN deadline <= NOW() + INTERVAL '15 days' THEN 'MEDIUM'
                ELSE 'LOW'
            END
        )::projectpriority
        WHERE priority IS NULL
        """
    )

    # 4. Make priority required
    op.alter_column(
        "project",
        "priority",
        nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    # 1. Drop column using the enum
    op.drop_column("project", "priority")

    # 2. Drop the PostgreSQL enum type
    op.execute("DROP TYPE IF EXISTS projectpriority")
