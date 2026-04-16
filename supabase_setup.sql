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
    user_id BIGINT,
    name TEXT,
    tracks JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP DEFAULT NOW()
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

-- Create policies for service role access
CREATE POLICY "Service role full access" ON groups FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON sudo_users FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON gbanned FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Service role full access" ON group_bans FOR ALL USING (true) WITH CHECK (true);

-- global_music_index table: Custom universal catalog cache
CREATE TABLE IF NOT EXISTS global_music_index (
    query_key TEXT PRIMARY KEY,
    track_id TEXT,
    title TEXT,
    artist TEXT,
    duration INTEGER,
    thumbnail TEXT,
    source TEXT,
    last_played TIMESTAMP DEFAULT NOW()
);

-- Create indexes for fast searching and auto-pruning
CREATE INDEX IF NOT EXISTS idx_music_title ON global_music_index(title);
CREATE INDEX IF NOT EXISTS idx_music_last_played ON global_music_index(last_played);
-- Enable trigram extension for substring/similarity indexes (if not already enabled)
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- GIN trigram index to accelerate LIKE '%%keyword%%' and similarity searches on title
CREATE INDEX IF NOT EXISTS idx_music_title_trgm ON global_music_index USING gin (title gin_trgm_ops);

-- Enable Row Level Security (RLS)
ALTER TABLE global_music_index ENABLE ROW LEVEL SECURITY;

-- Create policies for service role access
CREATE POLICY "Service role full access" ON global_music_index FOR ALL USING (true) WITH CHECK (true);
