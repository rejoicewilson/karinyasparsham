"""initial financial ledger schema

Revision ID: 014c57378b65
Revises: 
Create Date: 2026-08-09 11:32:54.805169
"""
from collections.abc import Sequence
from pathlib import Path

from alembic import context, op
import sqlalchemy as sa


revision: str = '014c57378b65'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0001_initial_schema.sql"
    sql = sql_path.read_text(encoding="utf-8")
    if context.is_offline_mode():
        op.execute(sql)
    else:
        op.get_bind().exec_driver_sql(sql.replace("%", "%%"))


def downgrade() -> None:
    sql = """
    DROP VIEW IF EXISTS public.case_obligation_balances;
    DROP TABLE IF EXISTS public.idempotency_keys CASCADE;
    DROP TABLE IF EXISTS public.notification_outbox CASCADE;
    DROP TABLE IF EXISTS public.push_subscriptions CASCADE;
    DROP TABLE IF EXISTS public.notification_recipients CASCADE;
    DROP TABLE IF EXISTS public.notification_events CASCADE;
    DROP TABLE IF EXISTS public.deposit_items CASCADE;
    DROP TABLE IF EXISTS public.deposit_batches CASCADE;
    DROP TABLE IF EXISTS public.collection_transactions CASCADE;
    DROP TABLE IF EXISTS public.permanent_membership_accounts CASCADE;
    DROP TABLE IF EXISTS public.case_obligations CASCADE;
    DROP TABLE IF EXISTS public.death_cases CASCADE;
    DROP TABLE IF EXISTS public.monthly_case_counters CASCADE;
    DROP TABLE IF EXISTS public.bank_accounts CASCADE;
    DROP TABLE IF EXISTS public.members CASCADE;
    DROP TABLE IF EXISTS public.agent_taluk_assignments CASCADE;
    DROP TABLE IF EXISTS public.taluks CASCADE;
    DROP TABLE IF EXISTS public.app_settings CASCADE;
    DROP TABLE IF EXISTS public.audit_logs CASCADE;
    DROP TABLE IF EXISTS public.profiles CASCADE;
    DROP TYPE IF EXISTS public.notification_type;
    DROP TYPE IF EXISTS public.deposit_status;
    DROP TYPE IF EXISTS public.collection_status;
    DROP TYPE IF EXISTS public.collection_method;
    DROP TYPE IF EXISTS public.collection_type;
    DROP TYPE IF EXISTS public.death_case_status;
    DROP TYPE IF EXISTS public.membership_type;
    DROP TYPE IF EXISTS public.account_status;
    DROP TYPE IF EXISTS public.user_role;
    DROP FUNCTION IF EXISTS public.validate_domain_role();
    DROP FUNCTION IF EXISTS public.create_member_permanent_account();
    DROP FUNCTION IF EXISTS public.prevent_audit_mutation();
    DROP FUNCTION IF EXISTS public.prevent_ledger_delete();
    DROP FUNCTION IF EXISTS public.set_updated_at();
    """
    if context.is_offline_mode():
        op.execute(sql)
    else:
        op.get_bind().exec_driver_sql(sql)
