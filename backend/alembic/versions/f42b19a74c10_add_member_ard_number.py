"""add optional member ARD number

Revision ID: f42b19a74c10
Revises: d91f6c82a4e7
Create Date: 2026-09-19 12:00:00
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f42b19a74c10"
down_revision: str | None = "d91f6c82a4e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("members", sa.Column("ard_no", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_members_ard_no_digits",
        "members",
        "ard_no IS NULL OR ard_no ~ '^[0-9]+$'",
    )
    op.create_index("ix_members_ard_no", "members", ["ard_no"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_members_ard_no", table_name="members")
    op.drop_constraint("ck_members_ard_no_digits", "members", type_="check")
    op.drop_column("members", "ard_no")
