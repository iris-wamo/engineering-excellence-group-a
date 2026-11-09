"""Add an optional timezone-aware task due date and lookup index.

Revision ID: d7b2a91c6e40
Revises: c4a7e2f19b3d
"""

import sqlalchemy as sa
from alembic import op

revision = "d7b2a91c6e40"
down_revision = "c4a7e2f19b3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add due_date without requiring values for existing tasks."""
    op.add_column(
        "task",
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_due_date", "task", ["due_date"])


def downgrade() -> None:
    """Remove the index before dropping its column."""
    op.drop_index("ix_task_due_date", table_name="task")
    op.drop_column("task", "due_date")
