-- Soul King Telegram Mini App schema additions (Supabase/Postgres)
-- Run after supabase_setup.sql

-- 1) Individual mini app sessions
CREATE TABLE IF NOT EXISTS public.mini_app_sessions (
    user_id BIGINT PRIMARY KEY,
    recent_tracks JSONB NOT NULL DEFAULT '[]'::jsonb,
    preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
    last_chat_id BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mini_app_sessions_updated_at
    ON public.mini_app_sessions (updated_at DESC);

-- 2) Lobby snapshots for cold-start restoration
CREATE TABLE IF NOT EXISTS public.lobby_snapshots (
    chat_id BIGINT PRIMARY KEY,
    now_playing JSONB,
    queue JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'idle',
    position_seconds INTEGER NOT NULL DEFAULT 0,
    participants JSONB NOT NULL DEFAULT '[]'::jsonb,
    version BIGINT NOT NULL DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lobby_snapshots_updated_at
    ON public.lobby_snapshots (updated_at DESC);

-- Keep updated_at fresh on write
CREATE OR REPLACE FUNCTION public.touch_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_mini_app_sessions_touch_updated_at ON public.mini_app_sessions;
CREATE TRIGGER trg_mini_app_sessions_touch_updated_at
BEFORE UPDATE ON public.mini_app_sessions
FOR EACH ROW
EXECUTE FUNCTION public.touch_updated_at();

DROP TRIGGER IF EXISTS trg_lobby_snapshots_touch_updated_at ON public.lobby_snapshots;
CREATE TRIGGER trg_lobby_snapshots_touch_updated_at
BEFORE UPDATE ON public.lobby_snapshots
FOR EACH ROW
EXECUTE FUNCTION public.touch_updated_at();

-- Enable RLS
ALTER TABLE public.mini_app_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.lobby_snapshots ENABLE ROW LEVEL SECURITY;

-- Service role full access (backend)
DROP POLICY IF EXISTS "Service role full access" ON public.mini_app_sessions;
CREATE POLICY "Service role full access"
ON public.mini_app_sessions
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access" ON public.lobby_snapshots;
CREATE POLICY "Service role full access"
ON public.lobby_snapshots
FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Optional authenticated read policy for future Supabase-auth frontend usage.
-- Keep disabled unless you map Telegram user_id to authenticated users.
-- CREATE POLICY "Authenticated read own mini_app_sessions"
-- ON public.mini_app_sessions
-- FOR SELECT
-- TO authenticated
-- USING ((auth.jwt() ->> 'telegram_user_id')::BIGINT = user_id);

NOTIFY pgrst, 'reload schema';

