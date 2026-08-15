"""fix domain role trigger field selection

Revision ID: 6ad7b482c1e9
Revises: 014c57378b65
Create Date: 2026-08-09 20:00:00
"""
from collections.abc import Sequence
from pathlib import Path

from alembic import op


revision: str = "6ad7b482c1e9"
down_revision: str | None = "014c57378b65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0002_fix_validate_domain_role.sql"
    sql = sql_path.read_text(encoding="utf-8").replace("%", "%%")
    op.get_bind().exec_driver_sql(sql)


def downgrade() -> None:
    # The previous implementation fails for assignment and bank-account rows.
    pass
