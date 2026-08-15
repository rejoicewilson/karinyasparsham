ALTER TABLE public.taluks
ADD COLUMN IF NOT EXISTS version integer NOT NULL DEFAULT 1;

DROP TRIGGER IF EXISTS taluks_updated ON public.taluks;
CREATE TRIGGER taluks_updated
BEFORE UPDATE ON public.taluks
FOR EACH ROW EXECUTE FUNCTION public.set_updated_at('versioned');
