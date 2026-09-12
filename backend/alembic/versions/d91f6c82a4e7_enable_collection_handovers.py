"""enable collection handovers without an assigned bank

Revision ID: d91f6c82a4e7
Revises: b84e2a9c7f31
Create Date: 2026-09-12 14:30:00
"""
from collections.abc import Sequence
from pathlib import Path

from alembic import op


revision: str = "d91f6c82a4e7"
down_revision: str | None = "b84e2a9c7f31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0004_enable_collection_handovers.sql"
    op.get_bind().exec_driver_sql(sql_path.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("ALTER TABLE public.deposit_batches ALTER COLUMN bank_snapshot DROP DEFAULT")
    op.execute("ALTER TABLE public.deposit_batches ALTER COLUMN bank_account_id SET NOT NULL")
