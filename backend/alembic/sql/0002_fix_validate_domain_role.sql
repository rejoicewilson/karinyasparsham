CREATE OR REPLACE FUNCTION public.validate_domain_role()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE expected_role public.user_role;
DECLARE actual_role public.user_role;
DECLARE target_profile_id uuid;
BEGIN
  expected_role := TG_ARGV[0]::public.user_role;
  IF TG_TABLE_NAME = 'members' THEN
    target_profile_id := NEW.profile_id;
  ELSE
    target_profile_id := NEW.agent_profile_id;
  END IF;

  SELECT role INTO actual_role
  FROM public.profiles
  WHERE id = target_profile_id;

  IF actual_role IS DISTINCT FROM expected_role THEN
    RAISE EXCEPTION 'Profile role must be %', expected_role
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$;
