"""Generate the immutable SQL payload for migration 0001 from current v1 metadata."""

from pathlib import Path
import sys

from sqlalchemy import create_mock_engine


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models import Base  # noqa: E402


statements: list[str] = []


def emit(sql, *multiparams, **params):
    compiled = sql.compile(dialect=engine.dialect)
    statements.append(str(compiled).rstrip() + ";")


engine = create_mock_engine("postgresql://", emit)
public_tables = [table for table in Base.metadata.sorted_tables if table.schema in (None, "public")]
Base.metadata.create_all(engine, tables=public_tables, checkfirst=False)

prefix = """-- Karunya Sparsham initial Supabase schema
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA extensions;
SET search_path TO public, extensions;
"""

hardening = """
-- Controlled updated_at/version maintenance.
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  NEW.updated_at = now();
  IF TG_ARGV[0] = 'versioned' THEN
    NEW.version = OLD.version + 1;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER profiles_updated BEFORE UPDATE ON public.profiles
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at('versioned');
CREATE TRIGGER taluks_updated BEFORE UPDATE ON public.taluks
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER members_updated BEFORE UPDATE ON public.members
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at('versioned');
CREATE TRIGGER obligations_updated BEFORE UPDATE ON public.case_obligations
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at('versioned');
CREATE TRIGGER permanent_accounts_updated BEFORE UPDATE ON public.permanent_membership_accounts
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at('versioned');
CREATE TRIGGER collections_updated BEFORE UPDATE ON public.collection_transactions
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER deposits_updated BEFORE UPDATE ON public.deposit_batches
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at('versioned');
CREATE TRIGGER outbox_updated BEFORE UPDATE ON public.notification_outbox
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
CREATE TRIGGER settings_updated BEFORE UPDATE ON public.app_settings
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at('versioned');

-- Financial and audit rows are never physically deleted.
CREATE OR REPLACE FUNCTION public.prevent_ledger_delete()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  RAISE EXCEPTION 'Hard deletion is not allowed for %', TG_TABLE_NAME
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

CREATE TRIGGER no_delete_death_cases BEFORE DELETE ON public.death_cases
FOR EACH ROW EXECUTE FUNCTION public.prevent_ledger_delete();
CREATE TRIGGER no_delete_obligations BEFORE DELETE ON public.case_obligations
FOR EACH ROW EXECUTE FUNCTION public.prevent_ledger_delete();
CREATE TRIGGER no_delete_collections BEFORE DELETE ON public.collection_transactions
FOR EACH ROW EXECUTE FUNCTION public.prevent_ledger_delete();
CREATE TRIGGER no_delete_deposits BEFORE DELETE ON public.deposit_batches
FOR EACH ROW EXECUTE FUNCTION public.prevent_ledger_delete();
CREATE TRIGGER no_delete_deposit_items BEFORE DELETE ON public.deposit_items
FOR EACH ROW EXECUTE FUNCTION public.prevent_ledger_delete();
CREATE TRIGGER no_delete_permanent_accounts BEFORE DELETE ON public.permanent_membership_accounts
FOR EACH ROW EXECUTE FUNCTION public.prevent_ledger_delete();

CREATE OR REPLACE FUNCTION public.prevent_audit_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  RAISE EXCEPTION 'Audit logs are append-only'
    USING ERRCODE = 'integrity_constraint_violation';
END;
$$;
CREATE TRIGGER audit_logs_append_only BEFORE UPDATE OR DELETE ON public.audit_logs
FOR EACH ROW EXECUTE FUNCTION public.prevent_audit_mutation();

-- Every new member receives a separate permanent-membership account.
CREATE OR REPLACE FUNCTION public.create_member_permanent_account()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
  INSERT INTO public.permanent_membership_accounts (member_id)
  VALUES (NEW.id)
  ON CONFLICT (member_id) DO NOTHING;
  RETURN NEW;
END;
$$;
CREATE TRIGGER member_permanent_account AFTER INSERT ON public.members
FOR EACH ROW EXECUTE FUNCTION public.create_member_permanent_account();

-- Role integrity at organization boundaries.
CREATE OR REPLACE FUNCTION public.validate_domain_role()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
DECLARE expected_role user_role;
DECLARE actual_role user_role;
BEGIN
  expected_role := TG_ARGV[0]::user_role;
  SELECT role INTO actual_role FROM public.profiles
  WHERE id = CASE WHEN TG_TABLE_NAME = 'members' THEN NEW.profile_id ELSE NEW.agent_profile_id END;
  IF actual_role IS DISTINCT FROM expected_role THEN
    RAISE EXCEPTION 'Profile role must be %', expected_role
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
CREATE TRIGGER member_profile_role BEFORE INSERT OR UPDATE OF profile_id ON public.members
FOR EACH ROW EXECUTE FUNCTION public.validate_domain_role('MEMBER');
CREATE TRIGGER assignment_agent_role BEFORE INSERT OR UPDATE OF agent_profile_id ON public.agent_taluk_assignments
FOR EACH ROW EXECUTE FUNCTION public.validate_domain_role('AGENT');
CREATE TRIGGER bank_agent_role BEFORE INSERT OR UPDATE OF agent_profile_id ON public.bank_accounts
FOR EACH ROW EXECUTE FUNCTION public.validate_domain_role('AGENT');

CREATE VIEW public.case_obligation_balances
WITH (security_invoker = true) AS
SELECT
  o.*,
  o.required_amount - o.collected_amount AS amount_still_to_collect,
  o.collected_amount - o.verified_amount AS amount_awaiting_verification,
  o.required_amount - o.verified_amount AS verified_balance,
  CASE
    WHEN o.collected_amount = 0 THEN 'UNPAID'
    WHEN o.collected_amount < o.required_amount THEN 'PARTIALLY_PAID'
    WHEN o.verified_amount < o.required_amount THEN 'AWAITING_VERIFICATION'
    ELSE 'VERIFIED'
  END AS display_status
FROM public.case_obligations o;

INSERT INTO public.app_settings (key, value, description)
VALUES
  ('financial_rules', '{"first_three_amount":"200.00","later_case_amount":"100.00","permanent_target":"15000.00","timezone":"Asia/Kolkata"}'::jsonb, 'Controlled financial defaults'),
  ('upload_limits', '{"death_case_photo_mb":10,"deposit_receipt_mb":10}'::jsonb, 'Private upload size limits'),
  ('notification_templates', '{"version":1}'::jsonb, 'Notification template version')
ON CONFLICT (key) DO NOTHING;

-- Private Supabase Storage buckets. Reads and writes require server-issued signed URLs.
INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES
  ('death-case-photos', 'death-case-photos', false, 10485760, ARRAY['image/jpeg','image/png','image/webp']),
  ('deposit-receipts', 'deposit-receipts', false, 10485760, ARRAY['image/jpeg','image/png','image/webp','application/pdf'])
ON CONFLICT (id) DO UPDATE SET
  public = false,
  file_size_limit = EXCLUDED.file_size_limit,
  allowed_mime_types = EXCLUDED.allowed_mime_types;

-- Default-deny Data API access. FastAPI is the sole application boundary.
DO $$
DECLARE table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'profiles','taluks','agent_taluk_assignments','members','bank_accounts',
    'monthly_case_counters','death_cases','case_obligations',
    'permanent_membership_accounts','collection_transactions','deposit_batches',
    'deposit_items','notification_events','notification_recipients',
    'push_subscriptions','notification_outbox','audit_logs','app_settings','idempotency_keys'
  ] LOOP
    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon, authenticated', table_name);
  END LOOP;
END;
$$;
REVOKE ALL ON public.case_obligation_balances FROM anon, authenticated;
"""

output = ROOT / "backend" / "alembic" / "sql" / "0001_initial_schema.sql"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(prefix + "\n".join(statements) + hardening, encoding="utf-8")
print(f"Generated {output} ({len(public_tables)} tables, {len(statements)} DDL statements)")
