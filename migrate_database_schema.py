import os
import sqlite3
import psycopg2
from urllib.parse import urlparse

def migrate_sqlite():
    db_path = "./data/bot.db"
    if not os.path.exists(db_path):
        print("SQLite DB not found.")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='global_music_index'")
        if not cur.fetchone():
            return

        print("Migrating SQLite...")

        # Backup old table
        cur.execute("DROP TABLE IF EXISTS global_music_index_old")
        cur.execute("ALTER TABLE global_music_index RENAME TO global_music_index_old")

        # Create new table
        cur.execute("""
            CREATE TABLE global_music_index (
                query_key TEXT PRIMARY KEY,
                jamendo_track_id INTEGER,
                title TEXT,
                artist TEXT,
                duration INTEGER,
                thumbnail_url TEXT,
                audio_url TEXT,
                last_played TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        print("Cleared stale SQLite tracks.")

        # Update lobby_snapshots to clear queues
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='lobby_snapshots'")
        if cur.fetchone():
            cur.execute("UPDATE lobby_snapshots SET queue = '[]', now_playing = NULL")

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='mini_app_sessions'")
        if cur.fetchone():
            cur.execute("UPDATE mini_app_sessions SET recent_tracks = '[]'")

        conn.commit()
    except Exception as e:
        print(f"SQLite migration failed: {e}")
    finally:
        conn.close()

def migrate_neon():
    neon_url = os.environ.get("NEON_DATABASE_URL")
    if not neon_url:
        print("NEON_DATABASE_URL not found.")
        return

    try:
        conn = psycopg2.connect(neon_url)
        conn.autocommit = True
        cur = conn.cursor()

        print("Migrating Neon PostgreSQL...")

        cur.execute("DROP TABLE IF EXISTS music_index_old CASCADE")
        cur.execute("ALTER TABLE IF EXISTS music_index RENAME TO music_index_old")

        cur.execute("""
            CREATE TABLE music_index (
                id SERIAL PRIMARY KEY,
                jamendo_track_id INTEGER UNIQUE NOT NULL,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                duration INTEGER,
                thumbnail_url TEXT,
                audio_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("DROP TABLE IF EXISTS play_history_old CASCADE")
        cur.execute("ALTER TABLE IF EXISTS play_history RENAME TO play_history_old")

        cur.execute("""
            CREATE TABLE play_history (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT NOT NULL,
                jamendo_track_id INTEGER NOT NULL,
                title TEXT,
                artist TEXT,
                played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Clear queues
        cur.execute("UPDATE queues SET queue_data = '[]'::jsonb")

        print("Neon migration completed.")

    except Exception as e:
        print(f"Neon migration failed: {e}")

if __name__ == "__main__":
    migrate_sqlite()
    migrate_neon()
