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
                # Music index table (cached tracks)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS music_index (
                        id SERIAL PRIMARY KEY,
                        track_id VARCHAR(255) UNIQUE NOT NULL,
                        platform VARCHAR(50) NOT NULL,
                        title TEXT NOT NULL,
                        artist TEXT NOT NULL,
                        duration INTEGER,
                        thumbnail TEXT,
                        stream_url TEXT,
                        file_id TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
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
                        track_id VARCHAR(255) NOT NULL,
                        title TEXT,
                        artist TEXT,
                        played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
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
                    ON music_index(track_id)
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_music_index_platform 
                    ON music_index(platform)
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

                self.conn.commit()
                logger.info("Neon Database tables initialized.")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error initializing Neon tables: {e}")
            raise
    
    async def get_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get a track by ID from the music index."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM music_index WHERE track_id = %s",
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
                    "SELECT id FROM music_index WHERE track_id = %s",
                    (track_data.get('track_id'),)
                )
                existing = cur.fetchone()
                
                if existing:
                    # Update existing
                    cur.execute("""
                        UPDATE music_index 
                        SET title = %s, artist = %s, duration = %s, 
                            thumbnail = %s, stream_url = %s, file_id = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE track_id = %s
                    """, (
                        track_data.get('title'),
                        track_data.get('artist'),
                        track_data.get('duration'),
                        track_data.get('thumbnail'),
                        track_data.get('stream_url'),
                        track_data.get('file_id'),
                        track_data.get('track_id')
                    ))
                else:
                    # Insert new
                    cur.execute("""
                        INSERT INTO music_index 
                        (track_id, platform, title, artist, duration, thumbnail, stream_url, file_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        track_data.get('track_id'),
                        track_data.get('platform', 'unknown'),
                        track_data.get('title'),
                        track_data.get('artist'),
                        track_data.get('duration'),
                        track_data.get('thumbnail'),
                        track_data.get('stream_url'),
                        track_data.get('file_id')
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
                    INSERT INTO play_history (chat_id, track_id, title, artist)
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

    async def save_jamendo_token(self, user_id: int, token: Dict[str, Any]) -> bool:
        """Save Jamendo token for user in playlists table."""
        try:
            import json
            with self.conn.cursor() as cur:
                cur.execute("UPDATE playlists SET jamendo_token = %s WHERE creator_user_id = %s", (json.dumps(token), user_id))
                self.conn.commit()
                return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error saving jamendo token in Neon: {e}")
            return False

    async def get_jamendo_token(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get Jamendo token for a user."""
        try:
            with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT jamendo_token FROM playlists WHERE creator_user_id = %s AND jamendo_token IS NOT NULL LIMIT 1", (user_id,))
                result = cur.fetchone()
                return dict(result['jamendo_token']) if result and result.get('jamendo_token') else None
        except Exception as e:
            logger.error(f"Error getting jamendo token from Neon: {e}")
            return None


def init_neon(database_url: str):
    """Initialize Neon database singleton."""
    global neon_db
    neon_db = NeonDatabase(database_url)
    logger.info("Neon Database initialized.")

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
