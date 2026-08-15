"""add optimistic version to taluks

Revision ID: b84e2a9c7f31
Revises: 6ad7b482c1e9
Create Date: 2026-08-09 20:10:00
"""
from collections.abc import Sequence
from pathlib import Path

from alembic import op


revision: str = "b84e2a9c7f31"
down_revision: str | None = "6ad7b482c1e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0003_add_taluk_version.sql"
    op.get_bind().exec_driver_sql(sql_path.read_text(encoding="utf-8"))


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS taluks_updated ON public.taluks")
    op.execute("ALTER TABLE public.taluks DROP COLUMN IF EXISTS version")
    op.execute(
        "CREATE TRIGGER taluks_updated BEFORE UPDATE ON public.taluks "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )
