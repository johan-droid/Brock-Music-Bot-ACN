-- Supabase SQL Setup for Music Bot
-- Run this in Supabase SQL Editor to create required tables
-- NOTE: PostgreSQL-only migration script (Supabase/Postgres). Do not parse as SQL Server/T-SQL.

-- Advisory lock wrappers exposed through PostgREST RPC.
-- Supabase RPC can only call SQL functions, not native pg_* functions directly.
CREATE OR REPLACE FUNCTION public.try_lock(p_key BIGINT)
RETURNS BOOLEAN
LANGUAGE SQL
AS $$
    SELECT pg_try_advisory_lock(p_key);
$$;

CREATE OR REPLACE FUNCTION public.try_unlock(p_key BIGINT)
RETURNS BOOLEAN
LANGUAGE SQL
AS $$
    SELECT pg_advisory_unlock(p_key);
$$;

-- groups table: Stores group/chat settings
CREATE TABLE IF NOT EXISTS groups (
    id BIGINT PRIMARY KEY,
    title TEXT,
    lang TEXT DEFAULT 'en',
    is_active BOOLEAN DEFAULT TRUE,
    joined_at TIMESTAMP DEFAULT NOW(),
    settings JSONB DEFAULT '{"play_on_join": true, "max_queue": 100, "vol_default": 100, "loop_mode": "none", "quality": "high", "thumb_mode": true}'::jsonb
);

-- sudo_users table: Admin users with special privileges
CREATE TABLE IF NOT EXISTS sudo_users (
    id BIGINT PRIMARY KEY,
    name TEXT,
    added_by BIGINT,
    added_at TIMESTAMP DEFAULT NOW()
);

-- gbanned table: Globally banned users
CREATE TABLE IF NOT EXISTS gbanned (
    id BIGINT PRIMARY KEY,
    reason TEXT,
    banned_by BIGINT,
    banned_at TIMESTAMP DEFAULT NOW()
);

-- group_bans table: Users banned in specific groups
CREATE TABLE IF NOT EXISTS group_bans (
    chat_id BIGINT,
    user_id BIGINT,
    banned_at TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (chat_id, user_id)
);

-- playlists table: User saved playlists (optional)
CREATE TABLE IF NOT EXISTS playlists (
    id SERIAL PRIMARY KEY,
    creator_user_id BIGINT,
    name TEXT,
    jamendo_playlist_id TEXT,
    is_collaborative BOOLEAN DEFAULT FALSE,
    is_public BOOLEAN DEFAULT FALSE,
    jamendo_token JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- playlist_tracks table
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id SERIAL PRIMARY KEY,
    playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
    jamendo_track_id TEXT NOT NULL,
    position INTEGER,
    added_by BIGINT,
    added_at TIMESTAMP DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX IF NOT EXISTS idx_groups_active ON groups(is_active);
CREATE INDEX IF NOT EXISTS idx_gbanned_id ON gbanned(id);
CREATE INDEX IF NOT EXISTS idx_group_bans_chat ON group_bans(chat_id);
CREATE INDEX IF NOT EXISTS idx_group_bans_user ON group_bans(user_id);
CREATE INDEX IF NOT EXISTS idx_sudo_users_id ON sudo_users(id);

-- Insert default owner as sudo user (replace YOUR_USER_ID with actual Telegram user ID)
-- INSERT INTO sudo_users (id, name, added_by) VALUES (YOUR_USER_ID, 'Owner', YOUR_USER_ID);

-- Enable Row Level Security (RLS) - recommended for production
ALTER TABLE groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE sudo_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE gbanned ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_bans ENABLE ROW LEVEL SECURITY;

-- Create policies for service role access (Idempotent)
DROP POLICY IF EXISTS "Service role full access" ON groups;
CREATE POLICY "Service role full access" ON groups FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access" ON sudo_users;
CREATE POLICY "Service role full access" ON sudo_users FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access" ON gbanned;
CREATE POLICY "Service role full access" ON gbanned FOR ALL TO service_role USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Service role full access" ON group_bans;
CREATE POLICY "Service role full access" ON group_bans FOR ALL TO service_role USING (true) WITH CHECK (true);

-- global_music_index table: Custom universal catalog cache
CREATE TABLE IF NOT EXISTS global_music_index (
    query_key TEXT PRIMARY KEY,
    jamendo_track_id INTEGER,
    title TEXT,
    artist TEXT,
    duration INTEGER,
    thumbnail_url TEXT,

    audio_url TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    last_played TIMESTAMP DEFAULT NOW()
);

-- Backward-compatible schema evolution for existing projects.
ALTER TABLE IF EXISTS global_music_index
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE IF EXISTS global_music_index
    ADD COLUMN IF NOT EXISTS sources JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE IF EXISTS global_music_index
    ADD COLUMN IF NOT EXISTS stream_url TEXT;

UPDATE global_music_index
SET stream_url = COALESCE(
    NULLIF(stream_url, ''),
    NULLIF(metadata->>'stream_url', ''),
    NULLIF(metadata->>'url', ''),
    NULLIF(sources->0->>'url', '')
)
WHERE stream_url IS NULL OR stream_url = '';

-- Enable trigram extension for substring/similarity indexes (if not already enabled)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Fast fuzzy search RPC for catalog-first lookup.
CREATE OR REPLACE FUNCTION public.search_music_index(p_query TEXT, p_limit INTEGER DEFAULT 5)
RETURNS TABLE (
    query_key TEXT,
    jamendo_track_id INTEGER,
    title TEXT,
    artist TEXT,
    duration INTEGER,
    thumbnail_url TEXT,

    audio_url TEXT,
    metadata JSONB,
    sources JSONB,
    last_played TIMESTAMP
)
LANGUAGE SQL
AS $$
    SELECT
        g.query_key,
        g.track_id,
        g.title,
        g.artist,
        g.duration,
        g.thumbnail,
        g.source,
        g.stream_url,
        g.metadata,
        g.sources,
        g.last_played
    FROM global_music_index g
    WHERE
        g.title ILIKE '%' || p_query || '%'
        OR g.artist ILIKE '%' || p_query || '%'
        OR similarity(g.title, p_query) > 0.2
    ORDER BY similarity(g.title, p_query) DESC, g.last_played DESC
    LIMIT GREATEST(1, COALESCE(p_limit, 5));
$$;

-- Create indexes for fast searching and auto-pruning
CREATE INDEX IF NOT EXISTS idx_music_title ON global_music_index(title);
CREATE INDEX IF NOT EXISTS idx_music_last_played ON global_music_index(last_played);
-- GIN trigram index to accelerate LIKE '%%keyword%%' and similarity searches on title
CREATE INDEX IF NOT EXISTS idx_music_title_trgm ON global_music_index USING gin (title gin_trgm_ops);

-- Enable Row Level Security (RLS)
ALTER TABLE global_music_index ENABLE ROW LEVEL SECURITY;

-- Create policies for service role access (Idempotent)
DROP POLICY IF EXISTS "Service role full access" ON global_music_index;
CREATE POLICY "Service role full access" ON global_music_index FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Refresh PostgREST schema cache so new columns become visible without waiting for a restart.
NOTIFY pgrst, 'reload schema';

-- radio_shows table: Stores scheduled radio shows
CREATE TABLE IF NOT EXISTS radio_shows (
    id SERIAL PRIMARY KEY,
    chat_id BIGINT,
    host_user_id BIGINT,
    show_name TEXT,
    description TEXT,
    schedule_day_of_week INTEGER,
    schedule_time TEXT,
    genre_tags TEXT,
    duration_minutes INTEGER,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- show_tracks table: Stores tracks for a scheduled radio show
CREATE TABLE IF NOT EXISTS show_tracks (
    id SERIAL PRIMARY KEY,
    show_id INTEGER REFERENCES radio_shows(id) ON DELETE CASCADE,
    jamendo_track_id INTEGER,
    position INTEGER,
    added_by BIGINT,
    added_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_radio_shows_chat ON radio_shows(chat_id);
CREATE INDEX IF NOT EXISTS idx_radio_shows_time ON radio_shows(schedule_day_of_week, schedule_time);
CREATE INDEX IF NOT EXISTS idx_show_tracks_show ON show_tracks(show_id);
