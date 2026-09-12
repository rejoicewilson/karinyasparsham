ALTER TABLE public.deposit_batches
  ALTER COLUMN bank_account_id DROP NOT NULL;

ALTER TABLE public.deposit_batches
  ALTER COLUMN bank_snapshot SET DEFAULT '{}'::jsonb;

COMMENT ON TABLE public.deposit_batches IS
  'Collection handover batches. Legacy deposit rows and column names are retained for compatibility.';

COMMENT ON COLUMN public.deposit_batches.declared_deposit_amount IS
  'Amount the agent declares as handed over to the administrator.';

COMMENT ON COLUMN public.deposit_batches.deposited_at IS
  'Legacy column storing the handover date and time for new records.';

COMMENT ON COLUMN public.deposit_batches.agent_message IS
  'Optional note supplied by the agent for the handover.';
