"""Neon Database (PostgreSQL) support for the music bot."""

import os
import json
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)

# Global singleton
neon_db: Optional['NeonDatabase'] = None


class NeonDatabase:
    """Neon PostgreSQL database wrapper for bot data."""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.conn = None
        self._connect()
        self._init_tables()
    
    def _connect(self):
        """Establish connection to Neon Database."""
        try:
            self.conn = psycopg2.connect(self.database_url)
            self.conn.autocommit = False
            logger.info("Connected to Neon Database.")
        except Exception as e:
            logger.error(f"Failed to connect to Neon Database: {e}")
            raise
    
    def _init_tables(self):
        """Initialize database tables if they don't exist."""
        try:
            with self.conn.cursor() as cur:
                # Check if music_index has old column track_id
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'music_index' AND column_name = 'track_id'
                    )
                """)
                if cur.fetchone()[0]:
                    logger.info("Outdated music_index table found. Renaming to music_index_old.")
                    cur.execute("DROP TABLE IF EXISTS music_index_old CASCADE")
                    cur.execute("ALTER TABLE music_index RENAME TO music_index_old")

                # Check if play_history has old column track_id
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns 
                        WHERE table_name = 'play_history' AND column_name = 'track_id'
                    )
                """)
                if cur.fetchone()[0]:
                    logger.info("Outdated play_history table found. Renaming to play_history_old.")
                    cur.execute("DROP TABLE IF EXISTS play_history_old CASCADE")
                    cur.execute("ALTER TABLE play_history RENAME TO play_history_old")

                # Music index table (cached tracks)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS music_index (
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

                cur.execute("""
                    ALTER TABLE IF EXISTS music_index
                    ADD COLUMN IF NOT EXISTS jamendo_track_id INTEGER
                """)
                
                # Queues table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS queues (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        queue_data JSONB NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(chat_id)
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS groups (
                        id BIGINT PRIMARY KEY,
                        title TEXT,
                        lang TEXT DEFAULT 'en',
                        is_active BOOLEAN DEFAULT TRUE,
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        settings JSONB DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Chats table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS chats (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT UNIQUE NOT NULL,
                        title TEXT,
                        username TEXT,
                        type VARCHAR(50),
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Play history table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS play_history (
                        id SERIAL PRIMARY KEY,
                        chat_id BIGINT NOT NULL,
                        jamendo_track_id INTEGER NOT NULL,
                        title TEXT,
                        artist TEXT,
                        played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                cur.execute("""
                    ALTER TABLE IF EXISTS play_history
                    ADD COLUMN IF NOT EXISTS jamendo_track_id INTEGER
                """)

                # Global bans table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS gbanned (
                        id BIGINT PRIMARY KEY,
                        reason TEXT,
                        banned_by BIGINT,
                        banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS groupbans (
                        chat_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (chat_id, user_id)
                    )
                """)

                # Sudo users table
                cur.execute("""
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
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS show_tracks (
                        id SERIAL PRIMARY KEY,
                        show_id INTEGER REFERENCES radio_shows(id) ON DELETE CASCADE,
                        jamendo_track_id INTEGER,
                        position INTEGER,
                        added_by BIGINT,
                        added_at TIMESTAMP DEFAULT NOW()
                    )
                """)

                cur.execute("CREATE INDEX IF NOT EXISTS idx_radio_shows_chat ON radio_shows(chat_id)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_radio_shows_time ON radio_shows(schedule_day_of_week, schedule_time)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_show_tracks_show ON show_tracks(show_id)")

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS sudo_users (
                        id BIGINT PRIMARY KEY,
                        name TEXT,
                        added_by BIGINT,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Create indexes
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_music_index_track_id 
                    ON music_index(jamendo_track_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_music_index_platform 
                    ON music_index(artist)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_queues_chat_id 
                    ON queues(chat_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_chats_chat_id 
                    ON chats(chat_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_play_history_chat_id 
                    ON play_history(chat_id)
                """)
                

                # Playlists table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS playlists (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        creator_user_id BIGINT NOT NULL,
                        jamendo_playlist_id TEXT,
                        is_collaborative BOOLEAN DEFAULT FALSE,
                        is_public BOOLEAN DEFAULT FALSE,
                        jamendo_token JSONB,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                # Playlist tracks table
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS playlist_tracks (
                        id SERIAL PRIMARY KEY,
                        playlist_id INTEGER REFERENCES playlists(id) ON DELETE CASCADE,
                        jamendo_track_id TEXT NOT NULL,
                        position INTEGER,
                        added_by BIGINT,
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_playlists_creator ON playlists(creator_user_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_playlist_tracks_playlist ON playlist_tracks(playlist_id)
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS anon_requests (
                        id SERIAL PRIMARY KEY,
                        track_id TEXT,
                        requested_by TEXT,
                        chat_id BIGINT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                cur.execute("""
                    CREATE TABLE IF NOT EXISTS vote_sessions (
                        message_id BIGINT PRIMARY KEY,
                        track_id TEXT,
                        chat_id BIGINT,
                        yes_votes INTEGER DEFAULT 0,
                        no_votes INTEGER DEFAULT 0,
                        expired BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)

                self.conn.commit()
                logger.info("Neon Database tables initialized.")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error initializing Neon tables: {e}")
            raise
    
    async def get_track(self, track_id: int) -> Optional[Dict[str, Any]]:
        """Get a track by ID from the music index."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM music_index WHERE jamendo_track_id = %s",
                    (track_id,)
                )
                result = cur.fetchone()
                if result:
                    return dict(result)
                return None
        except Exception as e:
            logger.error(f"Error getting track from Neon: {e}")
            return None
    
    async def save_track(self, track_data: Dict[str, Any]) -> bool:
        """Save or update a track in the music index."""
        try:
            with self.conn.cursor() as cur:
                # Check if track exists
                cur.execute(
                    "SELECT id FROM music_index WHERE jamendo_track_id = %s",
                    (track_data.get('jamendo_track_id'),)
                )
                existing = cur.fetchone()
                
                if existing:
                    # Update existing
                    cur.execute("""
                        UPDATE music_index 
                        SET title = %s, artist = %s, duration = %s, 
                            thumbnail_url = %s, audio_url = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE jamendo_track_id = %s
                    """, (
                        track_data.get('title'),
                        track_data.get('artist'),
                        track_data.get('duration'),
                        track_data.get('thumbnail_url'),
                        track_data.get('audio_url'),
                        track_data.get('jamendo_track_id')
                    ))
                else:
                    # Insert new
                    cur.execute("""
                        INSERT INTO music_index
                        (jamendo_track_id, title, artist, duration, thumbnail_url, audio_url)
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (
                        track_data.get('jamendo_track_id'),
                        track_data.get('title'),
                        track_data.get('artist'),
                        track_data.get('duration'),
                        track_data.get('thumbnail_url'),
                        track_data.get('audio_url')
                    ))
                
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error saving track to Neon: {e}")
            return False
    
    async def search_tracks(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search tracks by title or artist."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM music_index 
                    WHERE title ILIKE %s OR artist ILIKE %s
                    ORDER BY created_at DESC
                    LIMIT %s
                """, (f'%{query}%', f'%{query}%', limit))
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error searching tracks in Neon: {e}")
            return []
    
    async def get_queue(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """Get queue for a chat."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM queues WHERE chat_id = %s",
                    (chat_id,)
                )
                result = cur.fetchone()
                if result:
                    return dict(result)
                return None
        except Exception as e:
            logger.error(f"Error getting queue from Neon: {e}")
            return None
    
    async def save_queue(self, chat_id: int, queue_data: Dict[str, Any]) -> bool:
        """Save or update queue for a chat."""
        try:
            with self.conn.cursor() as cur:
                # Convert queue_data to JSON string if it's a dict
                if isinstance(queue_data, dict):
                    queue_data = json.dumps(queue_data)
                
                cur.execute("""
                    INSERT INTO queues (chat_id, queue_data)
                    VALUES (%s, %s)
                    ON CONFLICT (chat_id) 
                    DO UPDATE SET queue_data = EXCLUDED.queue_data, 
                                  updated_at = CURRENT_TIMESTAMP
                """, (chat_id, queue_data))
                
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error saving queue to Neon: {e}")
            return False
    
    async def delete_queue(self, chat_id: int) -> bool:
        """Delete queue for a chat."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM queues WHERE chat_id = %s", (chat_id,))
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error deleting queue from Neon: {e}")
            return False
    
    async def add_chat(self, chat_id: int, title: str = None, 
                       username: str = None, chat_type: str = None) -> bool:
        """Add or update a chat."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO chats (chat_id, title, username, type)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (chat_id) 
                    DO UPDATE SET title = EXCLUDED.title,
                                  username = EXCLUDED.username,
                                  type = EXCLUDED.type,
                                  updated_at = CURRENT_TIMESTAMP
                """, (chat_id, title, username, chat_type))
                
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error adding chat to Neon: {e}")
            return False
    
    async def get_active_chats(self) -> List[Dict[str, Any]]:
        """Get all active chats."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM chats WHERE is_active = TRUE")
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error getting active chats from Neon: {e}")
            return []
    
    async def log_play(self, chat_id: int, track_id: str, 
                       title: str = None, artist: str = None) -> bool:
        """Log a play event."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO play_history (chat_id, jamendo_track_id, title, artist)
                    VALUES (%s, %s, %s, %s)
                """, (chat_id, track_id, title, artist))
                
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error logging play to Neon: {e}")
            return False
    
    def health_check(self) -> bool:
        """Check database connection health."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
                return True
        except Exception as e:
            logger.error(f"Neon health check failed: {e}")
            return False

    async def is_gbanned(self, user_id: int) -> bool:
        """Check if user is globally banned."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1 FROM gbanned WHERE id = %s", (user_id,))
                return cur.fetchone() is not None
        except Exception as e:
            logger.debug(f"is_gbanned check error: {e}")
            return False

    async def is_sudo(self, user_id: int) -> bool:
        """Check if user is sudo."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1 FROM sudo_users WHERE id = %s", (user_id,))
                return cur.fetchone() is not None
        except Exception as e:
            logger.debug(f"is_sudo check error: {e}")
            return False

    @staticmethod
    def _default_group_settings() -> Dict[str, Any]:
        return {
            "play_on_join": True,
            "max_queue": 100,
            "vol_default": 100,
            "loop_mode": "none",
            "quality": "high",
            "thumb_mode": True,
        }

    @staticmethod
    def _merge_dotted_settings(settings: Dict[str, Any], dotted_key: str, value: Any) -> None:
        parts = dotted_key.split(".")[1:]
        target = settings
        for part in parts[:-1]:
            if part not in target or not isinstance(target[part], dict):
                target[part] = {}
            target = target[part]
        if parts:
            target[parts[-1]] = value

    async def get_group(self, chat_id: int) -> dict:
        """Get group settings or create defaults for a chat."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM groups WHERE id = %s", (chat_id,))
                row = cur.fetchone()
                if not row:
                    settings = self._default_group_settings()
                    cur.execute(
                        "INSERT INTO groups (id, title, is_active, settings) VALUES (%s, %s, %s, %s::jsonb)",
                        (chat_id, "", True, json.dumps(settings)),
                    )
                    self.conn.commit()
                    return {
                        "_id": chat_id,
                        "title": "",
                        "lang": "en",
                        "is_active": True,
                        "settings": settings,
                    }

                settings = row.get("settings") or {}
                if isinstance(settings, str):
                    try:
                        settings = json.loads(settings)
                    except Exception:
                        settings = {}
                return {
                    "_id": row["id"],
                    "title": row.get("title") or "",
                    "lang": row.get("lang") or "en",
                    "is_active": bool(row.get("is_active")),
                    "settings": settings if isinstance(settings, dict) else {},
                }
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error getting group from Neon: {e}")
            return {
                "_id": chat_id,
                "title": "",
                "lang": "en",
                "is_active": True,
                "settings": self._default_group_settings(),
            }

    async def update_group(self, chat_id: int, updates: dict):
        """Update group settings and metadata."""
        try:
            current = await self.get_group(chat_id)
            settings = dict(current.get("settings") or {})

            if "settings" in updates and isinstance(updates["settings"], dict):
                settings.update(updates["settings"])

            for key, value in updates.items():
                if key.startswith("settings."):
                    self._merge_dotted_settings(settings, key, value)

            update_fields = ["settings = %s::jsonb", "updated_at = CURRENT_TIMESTAMP"]
            params: List[Any] = [json.dumps(settings)]

            if "title" in updates:
                update_fields.append("title = %s")
                params.append(updates["title"])
            if "is_active" in updates:
                update_fields.append("is_active = %s")
                params.append(bool(updates["is_active"]))
            if "lang" in updates:
                update_fields.append("lang = %s")
                params.append(updates["lang"])

            params.append(chat_id)
            with self.conn.cursor() as cur:
                cur.execute(
                    f"UPDATE groups SET {', '.join(update_fields)} WHERE id = %s",
                    tuple(params),
                )
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error updating group in Neon: {e}")

    async def set_group_active(self, chat_id: int, active: bool):
        await self.update_group(chat_id, {"is_active": active})

    async def add_sudo(self, user_id: int, name: str, added_by: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sudo_users (id, name, added_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        added_by = EXCLUDED.added_by,
                        added_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, name, added_by),
                )
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error adding sudo in Neon: {e}")

    async def remove_sudo(self, user_id: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM sudo_users WHERE id = %s", (user_id,))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error removing sudo in Neon: {e}")

    async def get_sudo_users(self) -> list:
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM sudo_users ORDER BY added_at DESC")
                return [{"_id": r["id"], "name": r.get("name"), "added_by": r.get("added_by")} for r in cur.fetchall()]
        except Exception as e:
            logger.error(f"Error getting sudo users from Neon: {e}")
            return []

    async def gban_user(self, user_id: int, reason: str, banned_by: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO gbanned (id, reason, banned_by)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        reason = EXCLUDED.reason,
                        banned_by = EXCLUDED.banned_by,
                        banned_at = CURRENT_TIMESTAMP
                    """,
                    (user_id, reason, banned_by),
                )
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error gbanning user in Neon: {e}")

    async def ungban_user(self, user_id: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM gbanned WHERE id = %s", (user_id,))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error ungbanning user in Neon: {e}")

    async def ban_user(self, chat_id: int, user_id: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO groupbans (chat_id, user_id)
                    VALUES (%s, %s)
                    ON CONFLICT (chat_id, user_id) DO NOTHING
                    """,
                    (chat_id, user_id),
                )
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error banning user in Neon: {e}")

    async def unban_user(self, chat_id: int, user_id: int):
        try:
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM groupbans WHERE chat_id = %s AND user_id = %s", (chat_id, user_id))
                self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error unbanning user in Neon: {e}")

    async def is_banned(self, chat_id: int, user_id: int) -> bool:
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1 FROM groupbans WHERE chat_id = %s AND user_id = %s", (chat_id, user_id))
                return cur.fetchone() is not None
        except Exception as e:
            logger.debug(f"is_banned check error: {e}")
            return False

    async def get_stats(self) -> dict:
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM groups")
                total_groups = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM groups WHERE is_active = TRUE")
                active_groups = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM sudo_users")
                sudo_count = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM gbanned")
                gban_count = cur.fetchone()[0]
            return {
                "total_groups": total_groups,
                "active_groups": active_groups,
                "sudo_users": sudo_count,
                "gbanned_users": gban_count,
            }
        except Exception as e:
            logger.error(f"Error getting stats from Neon: {e}")
            return {}

    async def get_all_groups(self) -> list:
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT id FROM groups WHERE is_active = TRUE")
                return [{"_id": row["id"]} for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Error getting groups from Neon: {e}")
            return []

    async def prune_inactive_data(self) -> int:
        try:
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM groups WHERE is_active = FALSE")
                deleted_count = cur.rowcount or 0
                self.conn.commit()
                return deleted_count
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error pruning inactive Neon data: {e}")
            return 0

    async def search_global_music_index(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        rows = await self.search_tracks(query, limit)
        for row in rows:
            row.setdefault("stream_url", row.get("audio_url") or "")
            row.setdefault("url", row.get("audio_url") or "")
            row.setdefault("thumbnail", row.get("thumbnail_url"))
            row.setdefault("track_id", row.get("jamendo_track_id"))
            row.setdefault("source", "global_index")
            row.setdefault("metadata", {})
            row.setdefault("sources", [])
        return rows

    async def save_track_to_index(self, query: str, track: dict):
        track_id = track.get("id") or track.get("track_id") or track.get("jamendo_track_id")
        if track_id is None:
            track_id = abs(hash(query or track.get("title") or track.get("url") or "")) % 2147483647
        track_data = {
            "jamendo_track_id": track_id,
            "title": track.get("title") or "Unknown",
            "artist": track.get("artist") or track.get("uploader") or "Unknown Artist",
            "duration": track.get("duration") or 0,
            "thumbnail_url": track.get("thumbnail_url") or track.get("thumbnail") or track.get("thumb"),
            "audio_url": track.get("url") or track.get("stream_url") or "",
        }
        return await self.save_track(track_data)



    async def create_playlist(self, name: str, user_id: int) -> int:
        """Create a new playlist."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "INSERT INTO playlists (name, creator_user_id) VALUES (%s, %s) RETURNING id",
                    (name, user_id)
                )
                result = cur.fetchone()
                self.conn.commit()
                return result['id'] if result else -1
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error creating playlist in Neon: {e}")
            return -1

    async def get_user_playlists(self, user_id: int) -> List[Dict[str, Any]]:
        """Get playlists for a user."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM playlists WHERE creator_user_id = %s", (user_id,))
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Error getting user playlists from Neon: {e}")
            return []

    async def get_playlist_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get playlist by name."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM playlists WHERE name = %s", (name,))
                result = cur.fetchone()
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"Error getting playlist by name from Neon: {e}")
            return None

    async def get_playlist_tracks(self, playlist_id: int) -> List[Dict[str, Any]]:
        """Get tracks in a playlist."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT * FROM playlist_tracks WHERE playlist_id = %s ORDER BY position, id", (playlist_id,))
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            logger.error(f"Error getting playlist tracks from Neon: {e}")
            return []

    async def add_track_to_playlist(self, playlist_id: int, track_id: str, added_by: int) -> bool:
        """Add a track to a playlist."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT MAX(position) FROM playlist_tracks WHERE playlist_id = %s", (playlist_id,))
                max_pos = cur.fetchone()[0]
                pos = (max_pos + 1) if max_pos is not None else 1

                cur.execute(
                    "INSERT INTO playlist_tracks (playlist_id, jamendo_track_id, position, added_by) VALUES (%s, %s, %s, %s)",
                    (playlist_id, track_id, pos, added_by)
                )
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error adding track to playlist in Neon: {e}")
            return False

    async def remove_track_from_playlist(self, playlist_id: int, position: int) -> bool:
        """Remove a track from a playlist by position."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("DELETE FROM playlist_tracks WHERE playlist_id = %s AND position = %s", (playlist_id, position))
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error removing track from playlist in Neon: {e}")
            return False

    async def toggle_playlist_collab(self, playlist_id: int, is_collab: bool) -> bool:
        """Toggle collaborative mode for a playlist."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("UPDATE playlists SET is_collaborative = %s WHERE id = %s", (is_collab, playlist_id))
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error toggling playlist collab in Neon: {e}")
            return False

    # Radio Shows Implementation for Neon
    async def create_radio_show(self, chat_id: int, host_user_id: int, show_name: str, description: str, day: int, time: str, genre: str, duration: int) -> int:
        """Create a new radio show."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO radio_shows (chat_id, host_user_id, show_name, description, schedule_day_of_week, schedule_time, genre_tags, duration_minutes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (chat_id, host_user_id, show_name, description, day, time, genre, duration))
                show_id = cur.fetchone()[0]
                self.conn.commit()
                return show_id
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error creating radio show in Neon: {e}")
            return -1

    async def add_track_to_show(self, show_id: int, track_id: int, added_by: int) -> bool:
        """Add a track to a radio show."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("SELECT MAX(position) FROM show_tracks WHERE show_id = %s", (show_id,))
                row = cur.fetchone()
                pos = row[0] if row[0] is not None else 0

                cur.execute("""
                    INSERT INTO show_tracks (show_id, jamendo_track_id, position, added_by)
                    VALUES (%s, %s, %s, %s)
                """, (show_id, track_id, pos + 1, added_by))
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error adding track to show in Neon: {e}")
            return False

    async def get_upcoming_shows(self, chat_id: int) -> List[Dict[str, Any]]:
        """Get all upcoming shows for a chat."""
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM radio_shows WHERE chat_id = %s AND is_active = TRUE ORDER BY schedule_day_of_week, schedule_time", (chat_id,))
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error getting upcoming shows from Neon: {e}")
            return []

    async def get_show_tracks(self, show_id: int) -> List[Dict[str, Any]]:
        """Get all tracks for a radio show."""
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM show_tracks WHERE show_id = %s ORDER BY position", (show_id,))
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error getting show tracks from Neon: {e}")
            return []

    async def get_shows_by_time(self, day: int, time: str) -> List[Dict[str, Any]]:
        """Get all shows scheduled for a specific time."""
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM radio_shows WHERE schedule_day_of_week = %s AND schedule_time = %s AND is_active = TRUE", (day, time))
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error getting shows by time from Neon: {e}")
            return []

    async def delete_show(self, show_id: int) -> bool:
        """Delete a radio show (and its tracks via cascade)."""
        try:
            with self.conn.cursor() as cur:
                # show_tracks will be deleted due to CASCADE
                cur.execute("DELETE FROM radio_shows WHERE id = %s", (show_id,))
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error deleting radio show in Neon: {e}")
            return False

    async def get_past_shows(self, chat_id: int) -> List[Dict[str, Any]]:
        """Get past shows for a chat."""
        try:
            with self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute("SELECT * FROM radio_shows WHERE chat_id = %s AND is_active = FALSE ORDER BY created_at DESC", (chat_id,))
                results = cur.fetchall()
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error getting past shows from Neon: {e}")
            return []

    async def set_show_inactive(self, show_id: int) -> bool:
        """Mark a show as inactive (past)."""
        try:
            with self.conn.cursor() as cur:
                cur.execute("UPDATE radio_shows SET is_active = FALSE WHERE id = %s", (show_id,))
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error setting show inactive in Neon: {e}")
            return False


def init_neon(database_url: str):
    """Initialize Neon database singleton."""
    global neon_db
    neon_db = NeonDatabase(database_url)
    logger.info("Neon Database initialized.")

