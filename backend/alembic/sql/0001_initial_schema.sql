-- Karunya Sparsham initial Supabase schema
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
CREATE EXTENSION IF NOT EXISTS citext WITH SCHEMA extensions;
SET search_path TO public, extensions;
CREATE TYPE user_role AS ENUM ('ADMIN', 'AGENT', 'MEMBER');
CREATE TYPE account_status AS ENUM ('ACTIVE', 'INACTIVE', 'DECEASED', 'LOCKED');
CREATE TYPE membership_type AS ENUM ('REGULAR', 'PERMANENT');
CREATE TYPE death_case_status AS ENUM ('OPEN', 'CLOSED', 'CANCELLED');
CREATE TYPE collection_type AS ENUM ('DEATH_CONTRIBUTION', 'PERMANENT_MEMBERSHIP');
CREATE TYPE collection_method AS ENUM ('CASH', 'UPI', 'BANK_TRANSFER', 'OTHER');
CREATE TYPE collection_status AS ENUM ('RECORDED', 'BATCHED', 'VERIFIED', 'VOIDED');
CREATE TYPE deposit_status AS ENUM ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED');
CREATE TYPE notification_type AS ENUM ('DEATH_CASE_CREATED', 'PAYMENT_VERIFIED', 'DEPOSIT_REJECTED', 'PASSWORD_RESET', 'SYSTEM');

CREATE TABLE monthly_case_counters (
	sequence_month DATE NOT NULL, 
	last_sequence INTEGER NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_monthly_case_counters PRIMARY KEY (sequence_month), 
	CONSTRAINT ck_monthly_case_counters_nonnegative_sequence CHECK (last_sequence >= 0)
);

CREATE TABLE notification_events (
	type notification_type NOT NULL, 
	title TEXT NOT NULL, 
	body_template TEXT NOT NULL, 
	template_data JSONB DEFAULT '{}'::jsonb NOT NULL, 
	deep_link TEXT, 
	related_entity_type TEXT, 
	related_entity_id UUID, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	CONSTRAINT pk_notification_events PRIMARY KEY (id)
);

CREATE TABLE taluks (
	code CITEXT NOT NULL, 
	name TEXT NOT NULL, 
	district TEXT, 
	is_active BOOLEAN DEFAULT true NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	CONSTRAINT pk_taluks PRIMARY KEY (id), 
	CONSTRAINT uq_taluks_code UNIQUE (code), 
	CONSTRAINT uq_taluks_name UNIQUE (name)
);

CREATE TABLE profiles (
	auth_user_id UUID NOT NULL, 
	login_id CITEXT NOT NULL, 
	auth_email_alias CITEXT NOT NULL, 
	role user_role NOT NULL, 
	full_name TEXT NOT NULL, 
	phone TEXT, 
	account_status account_status DEFAULT 'ACTIVE'::account_status NOT NULL, 
	must_change_password BOOLEAN DEFAULT true NOT NULL, 
	last_login_at TIMESTAMP WITH TIME ZONE, 
	created_by UUID, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	CONSTRAINT pk_profiles PRIMARY KEY (id), 
	CONSTRAINT uq_profiles_auth_user_id UNIQUE (auth_user_id), 
	CONSTRAINT fk_profiles_auth_user_id_users FOREIGN KEY(auth_user_id) REFERENCES auth.users (id) ON DELETE RESTRICT, 
	CONSTRAINT uq_profiles_login_id UNIQUE (login_id), 
	CONSTRAINT uq_profiles_auth_email_alias UNIQUE (auth_email_alias), 
	CONSTRAINT fk_profiles_created_by_profiles FOREIGN KEY(created_by) REFERENCES profiles (id) ON DELETE RESTRICT
);

CREATE TABLE agent_taluk_assignments (
	agent_profile_id UUID NOT NULL, 
	taluk_id UUID NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	CONSTRAINT pk_agent_taluk_assignments PRIMARY KEY (id), 
	CONSTRAINT fk_agent_taluk_assignments_agent_profile_id_profiles FOREIGN KEY(agent_profile_id) REFERENCES profiles (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_agent_taluk_assignments_taluk_id_taluks FOREIGN KEY(taluk_id) REFERENCES taluks (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_agent_taluk_assignments_created_by_profiles FOREIGN KEY(created_by) REFERENCES profiles (id) ON DELETE RESTRICT
);
CREATE UNIQUE INDEX uq_active_agent_per_taluk ON agent_taluk_assignments (taluk_id) WHERE ends_at IS NULL;
CREATE UNIQUE INDEX uq_active_taluk_per_agent ON agent_taluk_assignments (agent_profile_id) WHERE ends_at IS NULL;

CREATE TABLE app_settings (
	key CITEXT NOT NULL, 
	value JSONB NOT NULL, 
	description TEXT, 
	updated_by UUID, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	CONSTRAINT pk_app_settings PRIMARY KEY (id), 
	CONSTRAINT uq_app_settings_key UNIQUE (key), 
	CONSTRAINT fk_app_settings_updated_by_profiles FOREIGN KEY(updated_by) REFERENCES profiles (id)
);

CREATE TABLE audit_logs (
	actor_profile_id UUID, 
	actor_role user_role, 
	action TEXT NOT NULL, 
	entity_type TEXT NOT NULL, 
	entity_id UUID, 
	before_data JSONB, 
	after_data JSONB, 
	request_id UUID NOT NULL, 
	ip_hash TEXT, 
	metadata JSONB DEFAULT '{}'::jsonb NOT NULL, 
	user_agent TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	CONSTRAINT pk_audit_logs PRIMARY KEY (id), 
	CONSTRAINT fk_audit_logs_actor_profile_id_profiles FOREIGN KEY(actor_profile_id) REFERENCES profiles (id)
);
CREATE INDEX ix_audit_actor_created ON audit_logs (actor_profile_id, created_at DESC);
CREATE INDEX ix_audit_entity_created ON audit_logs (entity_type, entity_id, created_at DESC);

CREATE TABLE bank_accounts (
	taluk_id UUID NOT NULL, 
	agent_profile_id UUID NOT NULL, 
	bank_name TEXT NOT NULL, 
	branch_name TEXT NOT NULL, 
	account_holder_name TEXT NOT NULL, 
	account_number_ciphertext TEXT NOT NULL, 
	account_number_last4 VARCHAR(4) NOT NULL, 
	ifsc_code CITEXT NOT NULL, 
	starts_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	ends_at TIMESTAMP WITH TIME ZONE, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	CONSTRAINT pk_bank_accounts PRIMARY KEY (id), 
	CONSTRAINT ck_bank_accounts_last4_digits CHECK (account_number_last4 ~ '^[0-9]{4}$'), 
	CONSTRAINT ck_bank_accounts_ifsc_format CHECK (ifsc_code ~* '^[A-Z]{4}0[A-Z0-9]{6}$'), 
	CONSTRAINT fk_bank_accounts_taluk_id_taluks FOREIGN KEY(taluk_id) REFERENCES taluks (id), 
	CONSTRAINT fk_bank_accounts_agent_profile_id_profiles FOREIGN KEY(agent_profile_id) REFERENCES profiles (id), 
	CONSTRAINT fk_bank_accounts_created_by_profiles FOREIGN KEY(created_by) REFERENCES profiles (id)
);
CREATE UNIQUE INDEX uq_active_bank_per_taluk ON bank_accounts (taluk_id) WHERE ends_at IS NULL;

CREATE TABLE idempotency_keys (
	actor_profile_id UUID NOT NULL, 
	operation TEXT NOT NULL, 
	key UUID NOT NULL, 
	request_hash VARCHAR(64) NOT NULL, 
	response_status INTEGER, 
	response_body JSONB, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	expires_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	CONSTRAINT pk_idempotency_keys PRIMARY KEY (id), 
	CONSTRAINT uq_idempotency_actor_operation_key UNIQUE (actor_profile_id, operation, key), 
	CONSTRAINT fk_idempotency_keys_actor_profile_id_profiles FOREIGN KEY(actor_profile_id) REFERENCES profiles (id)
);
CREATE INDEX ix_idempotency_expiry ON idempotency_keys (expires_at);

CREATE TABLE members (
	profile_id UUID NOT NULL, 
	member_code CITEXT NOT NULL, 
	taluk_id UUID NOT NULL, 
	joined_on DATE NOT NULL, 
	membership_type membership_type DEFAULT 'REGULAR'::membership_type NOT NULL, 
	permanent_since TIMESTAMP WITH TIME ZONE, 
	deceased_at TIMESTAMP WITH TIME ZONE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	CONSTRAINT pk_members PRIMARY KEY (id), 
	CONSTRAINT uq_members_profile_id UNIQUE (profile_id), 
	CONSTRAINT fk_members_profile_id_profiles FOREIGN KEY(profile_id) REFERENCES profiles (id) ON DELETE RESTRICT, 
	CONSTRAINT uq_members_member_code UNIQUE (member_code), 
	CONSTRAINT fk_members_taluk_id_taluks FOREIGN KEY(taluk_id) REFERENCES taluks (id) ON DELETE RESTRICT
);
CREATE INDEX ix_members_taluk_id ON members (taluk_id);

CREATE TABLE notification_recipients (
	event_id UUID NOT NULL, 
	profile_id UUID NOT NULL, 
	recipient_payload JSONB DEFAULT '{}'::jsonb NOT NULL, 
	read_at TIMESTAMP WITH TIME ZONE, 
	push_status VARCHAR(20) DEFAULT 'PENDING' NOT NULL, 
	push_attempts INTEGER DEFAULT 0 NOT NULL, 
	last_attempt_at TIMESTAMP WITH TIME ZONE, 
	failure_code TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	CONSTRAINT pk_notification_recipients PRIMARY KEY (id), 
	CONSTRAINT uq_notification_event_recipient UNIQUE (event_id, profile_id), 
	CONSTRAINT fk_notification_recipients_event_id_notification_events FOREIGN KEY(event_id) REFERENCES notification_events (id), 
	CONSTRAINT fk_notification_recipients_profile_id_profiles FOREIGN KEY(profile_id) REFERENCES profiles (id)
);
CREATE INDEX ix_notifications_profile_read_created ON notification_recipients (profile_id, read_at, created_at DESC);

CREATE TABLE push_subscriptions (
	profile_id UUID NOT NULL, 
	endpoint TEXT NOT NULL, 
	p256dh_ciphertext TEXT NOT NULL, 
	auth_ciphertext TEXT NOT NULL, 
	device_label TEXT, 
	user_agent TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	last_used_at TIMESTAMP WITH TIME ZONE, 
	revoked_at TIMESTAMP WITH TIME ZONE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	CONSTRAINT pk_push_subscriptions PRIMARY KEY (id), 
	CONSTRAINT fk_push_subscriptions_profile_id_profiles FOREIGN KEY(profile_id) REFERENCES profiles (id), 
	CONSTRAINT uq_push_subscriptions_endpoint UNIQUE (endpoint)
);
CREATE INDEX ix_push_subscriptions_profile_active ON push_subscriptions (profile_id) WHERE revoked_at IS NULL;

CREATE TABLE death_cases (
	case_number CITEXT NOT NULL, 
	deceased_member_id UUID NOT NULL, 
	death_date DATE NOT NULL, 
	title TEXT NOT NULL, 
	details TEXT NOT NULL, 
	photo_object_path TEXT NOT NULL, 
	sequence_month DATE NOT NULL, 
	monthly_sequence INTEGER NOT NULL, 
	default_amount NUMERIC(12, 2) NOT NULL, 
	contribution_amount NUMERIC(12, 2) NOT NULL, 
	is_amount_overridden BOOLEAN DEFAULT false NOT NULL, 
	override_reason TEXT, 
	status death_case_status DEFAULT 'OPEN'::death_case_status NOT NULL, 
	created_by UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	closed_at TIMESTAMP WITH TIME ZONE, 
	cancelled_at TIMESTAMP WITH TIME ZONE, 
	version INTEGER DEFAULT 1 NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	CONSTRAINT pk_death_cases PRIMARY KEY (id), 
	CONSTRAINT uq_death_case_month_sequence UNIQUE (sequence_month, monthly_sequence), 
	CONSTRAINT ck_death_cases_positive_sequence CHECK (monthly_sequence > 0), 
	CONSTRAINT ck_death_cases_positive_amounts CHECK (default_amount > 0 AND contribution_amount > 0), 
	CONSTRAINT ck_death_cases_override_reason_required CHECK ((is_amount_overridden AND nullif(btrim(override_reason), '') IS NOT NULL) OR (NOT is_amount_overridden AND override_reason IS NULL)), 
	CONSTRAINT uq_death_cases_case_number UNIQUE (case_number), 
	CONSTRAINT fk_death_cases_deceased_member_id_members FOREIGN KEY(deceased_member_id) REFERENCES members (id), 
	CONSTRAINT fk_death_cases_created_by_profiles FOREIGN KEY(created_by) REFERENCES profiles (id)
);
CREATE INDEX ix_death_cases_status_created ON death_cases (status, created_at DESC);
CREATE INDEX ix_death_cases_created_desc ON death_cases (created_at DESC);

CREATE TABLE deposit_batches (
	deposit_number CITEXT NOT NULL, 
	agent_profile_id UUID NOT NULL, 
	taluk_id UUID NOT NULL, 
	bank_account_id UUID NOT NULL, 
	bank_snapshot JSONB NOT NULL, 
	calculated_total NUMERIC(12, 2) DEFAULT 0 NOT NULL, 
	declared_deposit_amount NUMERIC(12, 2) DEFAULT 0 NOT NULL, 
	deposited_at TIMESTAMP WITH TIME ZONE, 
	bank_reference TEXT, 
	receipt_object_path TEXT, 
	agent_message TEXT, 
	status deposit_status DEFAULT 'DRAFT'::deposit_status NOT NULL, 
	submitted_at TIMESTAMP WITH TIME ZONE, 
	reviewed_by UUID, 
	reviewed_at TIMESTAMP WITH TIME ZONE, 
	rejection_reason TEXT, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	CONSTRAINT pk_deposit_batches PRIMARY KEY (id), 
	CONSTRAINT ck_deposit_batches_nonnegative_totals CHECK (calculated_total >= 0 AND declared_deposit_amount >= 0), 
	CONSTRAINT ck_deposit_batches_rejection_audit_required CHECK ((status = 'REJECTED' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND nullif(btrim(rejection_reason), '') IS NOT NULL) OR status <> 'REJECTED'), 
	CONSTRAINT ck_deposit_batches_approval_exact_match CHECK ((status = 'APPROVED' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND calculated_total = declared_deposit_amount) OR status <> 'APPROVED'), 
	CONSTRAINT uq_deposit_batches_deposit_number UNIQUE (deposit_number), 
	CONSTRAINT fk_deposit_batches_agent_profile_id_profiles FOREIGN KEY(agent_profile_id) REFERENCES profiles (id), 
	CONSTRAINT fk_deposit_batches_taluk_id_taluks FOREIGN KEY(taluk_id) REFERENCES taluks (id), 
	CONSTRAINT fk_deposit_batches_bank_account_id_bank_accounts FOREIGN KEY(bank_account_id) REFERENCES bank_accounts (id), 
	CONSTRAINT fk_deposit_batches_reviewed_by_profiles FOREIGN KEY(reviewed_by) REFERENCES profiles (id)
);
CREATE INDEX ix_deposits_status_submitted ON deposit_batches (status, submitted_at);
CREATE INDEX ix_deposits_agent_created ON deposit_batches (agent_profile_id, created_at DESC);

CREATE TABLE notification_outbox (
	recipient_id UUID NOT NULL, 
	status VARCHAR(20) DEFAULT 'PENDING' NOT NULL, 
	attempt_count INTEGER DEFAULT 0 NOT NULL, 
	next_attempt_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	last_error TEXT, 
	locked_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	CONSTRAINT pk_notification_outbox PRIMARY KEY (id), 
	CONSTRAINT ck_notification_outbox_valid_status CHECK (status IN ('PENDING','PROCESSING','SENT','FAILED')), 
	CONSTRAINT uq_notification_outbox_recipient_id UNIQUE (recipient_id), 
	CONSTRAINT fk_notification_outbox_recipient_id_notification_recipients FOREIGN KEY(recipient_id) REFERENCES notification_recipients (id)
);
CREATE INDEX ix_outbox_due ON notification_outbox (status, next_attempt_at) WHERE status IN ('PENDING','FAILED');

CREATE TABLE permanent_membership_accounts (
	member_id UUID NOT NULL, 
	target_amount NUMERIC(12, 2) DEFAULT 15000.00 NOT NULL, 
	collected_amount NUMERIC(12, 2) DEFAULT 0 NOT NULL, 
	verified_amount NUMERIC(12, 2) DEFAULT 0 NOT NULL, 
	achieved_at TIMESTAMP WITH TIME ZONE, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	CONSTRAINT pk_permanent_membership_accounts PRIMARY KEY (id), 
	CONSTRAINT ck_permanent_membership_accounts_amount_invariants CHECK (target_amount > 0 AND collected_amount >= 0 AND verified_amount >= 0 AND verified_amount <= collected_amount AND collected_amount <= target_amount), 
	CONSTRAINT uq_permanent_membership_accounts_member_id UNIQUE (member_id), 
	CONSTRAINT fk_permanent_membership_accounts_member_id_members FOREIGN KEY(member_id) REFERENCES members (id)
);

CREATE TABLE case_obligations (
	death_case_id UUID NOT NULL, 
	member_id UUID NOT NULL, 
	taluk_id_snapshot UUID NOT NULL, 
	responsible_agent_id UUID NOT NULL, 
	original_agent_id UUID NOT NULL, 
	required_amount NUMERIC(12, 2) NOT NULL, 
	collected_amount NUMERIC(12, 2) DEFAULT 0 NOT NULL, 
	verified_amount NUMERIC(12, 2) DEFAULT 0 NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	version INTEGER DEFAULT 1 NOT NULL, 
	CONSTRAINT pk_case_obligations PRIMARY KEY (id), 
	CONSTRAINT uq_case_obligation_member UNIQUE (death_case_id, member_id), 
	CONSTRAINT ck_case_obligations_amount_invariants CHECK (required_amount > 0 AND collected_amount >= 0 AND verified_amount >= 0 AND verified_amount <= collected_amount AND collected_amount <= required_amount), 
	CONSTRAINT fk_case_obligations_death_case_id_death_cases FOREIGN KEY(death_case_id) REFERENCES death_cases (id), 
	CONSTRAINT fk_case_obligations_member_id_members FOREIGN KEY(member_id) REFERENCES members (id), 
	CONSTRAINT fk_case_obligations_taluk_id_snapshot_taluks FOREIGN KEY(taluk_id_snapshot) REFERENCES taluks (id), 
	CONSTRAINT fk_case_obligations_responsible_agent_id_profiles FOREIGN KEY(responsible_agent_id) REFERENCES profiles (id), 
	CONSTRAINT fk_case_obligations_original_agent_id_profiles FOREIGN KEY(original_agent_id) REFERENCES profiles (id)
);
CREATE INDEX ix_obligations_open_balance ON case_obligations (responsible_agent_id) WHERE collected_amount < required_amount;
CREATE INDEX ix_obligations_member_case ON case_obligations (member_id, death_case_id);
CREATE INDEX ix_obligations_agent_updated ON case_obligations (responsible_agent_id, updated_at);

CREATE TABLE collection_transactions (
	receipt_number CITEXT NOT NULL, 
	collection_type collection_type NOT NULL, 
	member_id UUID NOT NULL, 
	agent_profile_id UUID NOT NULL, 
	taluk_id UUID NOT NULL, 
	case_obligation_id UUID, 
	permanent_account_id UUID, 
	amount NUMERIC(12, 2) NOT NULL, 
	method collection_method NOT NULL, 
	external_reference TEXT, 
	note TEXT, 
	collected_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	status collection_status DEFAULT 'RECORDED'::collection_status NOT NULL, 
	created_by UUID NOT NULL, 
	voided_by UUID, 
	voided_at TIMESTAMP WITH TIME ZONE, 
	void_reason TEXT, 
	client_request_id UUID NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	CONSTRAINT pk_collection_transactions PRIMARY KEY (id), 
	CONSTRAINT uq_collection_actor_request UNIQUE (agent_profile_id, client_request_id), 
	CONSTRAINT ck_collection_transactions_positive_amount CHECK (amount > 0), 
	CONSTRAINT ck_collection_transactions_target_matches_type CHECK ((collection_type = 'DEATH_CONTRIBUTION' AND case_obligation_id IS NOT NULL AND permanent_account_id IS NULL) OR (collection_type = 'PERMANENT_MEMBERSHIP' AND permanent_account_id IS NOT NULL AND case_obligation_id IS NULL)), 
	CONSTRAINT ck_collection_transactions_void_audit_required CHECK ((status = 'VOIDED' AND voided_by IS NOT NULL AND voided_at IS NOT NULL AND nullif(btrim(void_reason), '') IS NOT NULL) OR status <> 'VOIDED'), 
	CONSTRAINT uq_collection_transactions_receipt_number UNIQUE (receipt_number), 
	CONSTRAINT fk_collection_transactions_member_id_members FOREIGN KEY(member_id) REFERENCES members (id), 
	CONSTRAINT fk_collection_transactions_agent_profile_id_profiles FOREIGN KEY(agent_profile_id) REFERENCES profiles (id), 
	CONSTRAINT fk_collection_transactions_taluk_id_taluks FOREIGN KEY(taluk_id) REFERENCES taluks (id), 
	CONSTRAINT fk_collection_transactions_case_obligation_id_case_obligations FOREIGN KEY(case_obligation_id) REFERENCES case_obligations (id), 
	CONSTRAINT fk_collection_transactions_permanent_account_id_permane_791c FOREIGN KEY(permanent_account_id) REFERENCES permanent_membership_accounts (id), 
	CONSTRAINT fk_collection_transactions_created_by_profiles FOREIGN KEY(created_by) REFERENCES profiles (id), 
	CONSTRAINT fk_collection_transactions_voided_by_profiles FOREIGN KEY(voided_by) REFERENCES profiles (id)
);
CREATE INDEX ix_collections_member_date ON collection_transactions (member_id, collected_at DESC);
CREATE INDEX ix_collections_agent_status_date ON collection_transactions (agent_profile_id, status, collected_at);

CREATE TABLE deposit_items (
	deposit_batch_id UUID NOT NULL, 
	collection_transaction_id UUID NOT NULL, 
	amount_snapshot NUMERIC(12, 2) NOT NULL, 
	released_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID DEFAULT gen_random_uuid() NOT NULL, 
	CONSTRAINT pk_deposit_items PRIMARY KEY (id), 
	CONSTRAINT ck_deposit_items_positive_amount CHECK (amount_snapshot > 0), 
	CONSTRAINT fk_deposit_items_deposit_batch_id_deposit_batches FOREIGN KEY(deposit_batch_id) REFERENCES deposit_batches (id), 
	CONSTRAINT fk_deposit_items_collection_transaction_id_collection_t_81e0 FOREIGN KEY(collection_transaction_id) REFERENCES collection_transactions (id)
);
CREATE UNIQUE INDEX uq_active_deposit_item_collection ON deposit_items (collection_transaction_id) WHERE released_at IS NULL;
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
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at('versioned');
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
DECLARE target_profile_id uuid;
BEGIN
  expected_role := TG_ARGV[0]::user_role;
  IF TG_TABLE_NAME = 'members' THEN
    target_profile_id := NEW.profile_id;
  ELSE
    target_profile_id := NEW.agent_profile_id;
  END IF;
  SELECT role INTO actual_role FROM public.profiles
  WHERE id = target_profile_id;
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
